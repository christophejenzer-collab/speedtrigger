"""Bewegungserkennung + Tracking + Geschwindigkeitsmessung über zwei Messlinien.

Prinzip ("Lichtschranke im Bild"): Zeit t_A beim Überqueren von Linie A, t_B bei Linie B.
v = distanz_m / |t_B - t_A|. Der Überquerungszeitpunkt wird zwischen zwei Bildern linear
interpoliert, das reduziert den Fehler durch die niedrige Bildrate der Tapo deutlich.
"""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

ARBEITSBREITE = 640  # intern herunterskaliert -> schneller, robuster


def _seite(linie, p):
    """Vorzeichenbehafteter Abstand von Punkt p zur Geraden durch die Linie."""
    (x1, y1), (x2, y2) = linie
    laenge = math.hypot(x2 - x1, y2 - y1) or 1.0
    return ((x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)) / laenge


def _innerhalb(linie, p, toleranz=0.05):
    """Liegt die Projektion von p auf die Linie innerhalb des Segments (mit etwas Toleranz)?"""
    (x1, y1), (x2, y2) = linie
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy or 1.0
    u = ((p[0] - x1) * dx + (p[1] - y1) * dy) / l2
    return -toleranz <= u <= 1 + toleranz


@dataclass
class Spur:
    id: int
    t: float
    p: tuple
    t_a: float = None
    t_b: float = None
    zuletzt: float = 0.0
    kmh: float = None
    richtung: str = None
    ausgeloest: bool = False
    box: tuple = None
    vx: float = 0.0  # Geschwindigkeit im Bild (px/s) für Vorhersage bei Verdeckung
    vy: float = 0.0
    verlauf: list = field(default_factory=list)


class Messung:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mog = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32, detectShadows=True)
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self.spuren = {}
        self.naechste_id = 1
        self.groesse = None
        self.la = self.lb = None
        # so lange darf ein Fahrzeug verdeckt sein (Garage, Busch) und wird trotzdem wiedererkannt
        self.max_luecke = cfg.get("max_luecke_s", 1.5)

    def _init(self, h, w):
        self.groesse = (w, h)
        self.la = [(x * w, y * h) for x, y in self.cfg["linie_a"]]
        self.lb = [(x * w, y * h) for x, y in self.cfg["linie_b"]]

    def verarbeiten(self, t, bild):
        """Gibt Liste von Ereignissen zurück: dict(id, kmh, richtung, ausloesen)."""
        h0, w0 = bild.shape[:2]
        f = ARBEITSBREITE / w0
        klein = cv2.resize(bild, (ARBEITSBREITE, int(h0 * f)))
        h, w = klein.shape[:2]
        if self.groesse != (w, h):
            self._init(h, w)

        maske = self.mog.apply(klein)
        _, maske = cv2.threshold(maske, 200, 255, cv2.THRESH_BINARY)  # Schatten (127) weg
        maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, self.kernel)
        maske = cv2.dilate(maske, self.kernel, iterations=3)
        konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        min_a = self.cfg["min_flaeche"] * w * h
        objekte = []
        for k in konturen:
            if cv2.contourArea(k) < min_a:
                continue
            x, y, bw, bh = cv2.boundingRect(k)
            objekte.append(((x + bw / 2, y + bh / 2), (x, y, bw, bh)))

        ereignisse = []
        frei = set(self.spuren)
        for p, box in sorted(objekte, key=lambda o: -o[1][2] * o[1][3]):
            # Zuordnung zur vorhergesagten Position: so wird ein Auto nach einer Verdeckung
            # (z. B. hinter einem Busch) als dasselbe Fahrzeug erkannt.
            beste, dist = None, None
            for sid in frei:
                s = self.spuren[sid]
                luecke = t - s.t
                if luecke > self.max_luecke:
                    continue
                vor = (s.p[0] + s.vx * luecke, s.p[1] + s.vy * luecke)
                tor = 0.12 * w + 0.5 * math.hypot(s.vx, s.vy) * luecke
                d = math.dist(vor, p)
                if d < tor and (dist is None or d < dist):
                    beste, dist = sid, d
            if beste is None:
                s = Spur(self.naechste_id, t, p, zuletzt=t, box=box)
                self.spuren[s.id] = s
                self.naechste_id += 1
                continue
            frei.discard(beste)
            s = self.spuren[beste]
            e = self._update(s, t, p)
            s.box = box
            if e:
                ereignisse.append(e)

        for sid in [i for i, s in self.spuren.items() if t - s.zuletzt > self.max_luecke + 0.5]:
            del self.spuren[sid]
        self._skala = 1 / f
        return ereignisse

    def _kreuzung(self, linie, p0, p1, t0, t1):
        s0, s1 = _seite(linie, p0), _seite(linie, p1)
        if s0 == 0 or s0 * s1 > 0:
            return None
        anteil = abs(s0) / (abs(s0) + abs(s1))
        punkt = (p0[0] + (p1[0] - p0[0]) * anteil, p0[1] + (p1[1] - p0[1]) * anteil)
        if not _innerhalb(linie, punkt):
            return None
        return t0 + (t1 - t0) * anteil

    def _update(self, s, t, p):
        ta = self._kreuzung(self.la, s.p, p, s.t, t)
        tb = self._kreuzung(self.lb, s.p, p, s.t, t)
        if ta is not None and s.t_a is None:
            s.t_a = ta
        if tb is not None and s.t_b is None:
            s.t_b = tb
        dt = t - s.t
        if dt > 0:
            vx, vy = (p[0] - s.p[0]) / dt, (p[1] - s.p[1]) / dt
            erst = s.vx == 0 and s.vy == 0
            s.vx = vx if erst else 0.5 * s.vx + 0.5 * vx
            s.vy = vy if erst else 0.5 * s.vy + 0.5 * vy
        s.verlauf.append(p)
        s.verlauf = s.verlauf[-30:]
        s.t, s.p, s.zuletzt = t, p, t

        if s.kmh is None and s.t_a is not None and s.t_b is not None:
            dt = abs(s.t_b - s.t_a)
            if dt <= 0:
                return None
            kmh = self.cfg["distanz_m"] / dt * 3.6
            if kmh > self.cfg["max_kmh"]:
                s.kmh = -1  # unplausibel, nicht erneut auswerten
                return None
            s.kmh = kmh
            s.richtung = "a_nach_b" if s.t_a < s.t_b else "b_nach_a"
            erlaubt = self.cfg["richtung"] in ("beide", s.richtung)
            ausloesen = erlaubt and kmh >= self.cfg["schwelle_kmh"]
            return {"id": s.id, "kmh": kmh, "richtung": s.richtung, "ausloesen": ausloesen}
        return None

    def zeichnen(self, bild):
        """Overlay (Linien, Boxen, km/h) auf das Originalbild."""
        if self.la is None:
            return bild
        k = self._skala
        sc = lambda pt: (int(pt[0] * k), int(pt[1] * k))
        cv2.line(bild, sc(self.la[0]), sc(self.la[1]), (0, 200, 255), 2)
        cv2.line(bild, sc(self.lb[0]), sc(self.lb[1]), (255, 120, 0), 2)
        cv2.putText(bild, "A", sc(self.la[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 2)
        cv2.putText(bild, "B", sc(self.lb[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 120, 0), 2)
        for s in self.spuren.values():
            if not s.box:
                continue
            x, y, bw, bh = s.box
            farbe = (0, 0, 255) if s.ausgeloest else (0, 255, 0)
            cv2.rectangle(bild, sc((x, y)), sc((x + bw, y + bh)), farbe, 2)
            text = f"#{s.id}" + (f" {s.kmh:.0f} km/h" if s.kmh and s.kmh > 0 else "")
            cv2.putText(bild, text, sc((x, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, farbe, 2)
        return bild
