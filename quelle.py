"""Bildquelle: Tapo-RTSP-Stream (immer nur das neueste Bild) oder Videodatei zum Testen."""
import os
import threading
import time

# Niedrige Latenz für RTSP: TCP, kein Puffer. Muss vor dem Öffnen gesetzt sein.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0",
)
import cv2  # noqa: E402


def rtsp_url(cfg):
    user = os.environ.get("TAPO_USER")
    pw = os.environ.get("TAPO_PASS")
    if not user or not pw:
        raise SystemExit("TAPO_USER und TAPO_PASS als Umgebungsvariablen setzen (Kamerakonto der Tapo).")
    from urllib.parse import quote
    return f"rtsp://{quote(user, safe='')}:{quote(pw, safe='')}@{cfg['host']}:{cfg['port']}/{cfg['stream']}"


class RtspQuelle:
    """Liest in eigenem Thread und behält nur das jüngste Bild -> keine wachsende Verzögerung."""

    def __init__(self, url):
        self.url = url
        self._frame = None
        self._t = 0.0
        self._neu = False
        self._lock = threading.Lock()
        self._stop = False
        threading.Thread(target=self._lauf, daemon=True).start()

    def _lauf(self):
        while not self._stop:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                print("[Tapo] Stream nicht erreichbar, neuer Versuch in 3 s …")
                time.sleep(3)
                continue
            print("[Tapo] verbunden")
            while not self._stop:
                ok, frame = cap.read()
                if not ok:
                    print("[Tapo] Verbindung verloren, verbinde neu …")
                    break
                with self._lock:
                    self._frame, self._t, self._neu = frame, time.monotonic(), True
            cap.release()

    def lesen(self):
        """Liefert (zeitstempel_s, bild) des neuesten Bildes oder (None, None) wenn noch keins neu ist."""
        with self._lock:
            if not self._neu:
                return None, None
            self._neu = False
            return self._t, self._frame

    def schliessen(self):
        self._stop = True


class DateiQuelle:
    """Videodatei Bild für Bild; Zeitstempel aus Bildnummer/FPS (für reproduzierbare Tests)."""

    def __init__(self, pfad):
        self.cap = cv2.VideoCapture(pfad)
        if not self.cap.isOpened():
            raise SystemExit(f"Datei nicht lesbar: {pfad}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.n = 0
        self.ende = False

    def lesen(self):
        ok, frame = self.cap.read()
        if not ok:
            self.ende = True
            return None, None
        t = self.n / self.fps
        self.n += 1
        return t, frame

    def schliessen(self):
        self.cap.release()
