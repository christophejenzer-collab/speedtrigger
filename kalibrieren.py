"""Messlinien per Mausklick setzen: 4 Klicks = A-Start, A-Ende, B-Start, B-Ende.
r = zurücksetzen, s = speichern in config.toml, q = abbrechen.
"""
import re
import sys
import time
import tomllib

import cv2

from quelle import DateiQuelle, RtspQuelle, rtsp_url

CFG = "config.toml"


def main():
    with open(CFG, "rb") as f:
        cfg = tomllib.load(f)
    quelle = DateiQuelle(sys.argv[1]) if len(sys.argv) > 1 else RtspQuelle(rtsp_url(cfg["tapo"]))
    print("Warte auf Bild …")
    bild = None
    for _ in range(300):
        _, b = quelle.lesen()
        if b is not None:
            bild = b
            break
        time.sleep(0.05)
    quelle.schliessen()
    if bild is None:
        raise SystemExit("Kein Bild erhalten.")

    h, w = bild.shape[:2]
    punkte = []

    def klick(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN and len(punkte) < 4:
            punkte.append((x, y))

    cv2.namedWindow("Kalibrieren")
    cv2.setMouseCallback("Kalibrieren", klick)
    while True:
        anzeige = bild.copy()
        hinweis = ["A-Start", "A-Ende", "B-Start", "B-Ende", "s = speichern"][len(punkte)]
        cv2.putText(anzeige, f"Klick: {hinweis}   (r = reset, q = abbrechen)", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        for i, p in enumerate(punkte):
            cv2.circle(anzeige, p, 5, (0, 255, 0), -1)
        if len(punkte) >= 2:
            cv2.line(anzeige, punkte[0], punkte[1], (0, 200, 255), 2)
        if len(punkte) == 4:
            cv2.line(anzeige, punkte[2], punkte[3], (255, 120, 0), 2)
        cv2.imshow("Kalibrieren", anzeige)
        k = cv2.waitKey(30) & 0xFF
        if k == ord("q"):
            return
        if k == ord("r"):
            punkte.clear()
        if k == ord("s") and len(punkte) == 4:
            break
    cv2.destroyAllWindows()

    n = [(round(x / w, 4), round(y / h, 4)) for x, y in punkte]
    fmt = lambda a, b: f"[[{a[0]}, {a[1]}], [{b[0]}, {b[1]}]]"
    with open(CFG, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"^linie_a\s*=.*$", f"linie_a      = {fmt(n[0], n[1])}", text, flags=re.M)
    text = re.sub(r"^linie_b\s*=.*$", f"linie_b      = {fmt(n[2], n[3])}", text, flags=re.M)
    with open(CFG, "w", encoding="utf-8") as f:
        f.write(text)
    print("Gespeichert. Jetzt in config.toml 'distanz_m' auf die real gemessene Distanz A–B setzen!")


if __name__ == "__main__":
    main()
