"""SpeedTrigger: Tapo misst Geschwindigkeit, Canon EOS löst aus.

Start:   python speedtrigger.py
Test:    python speedtrigger.py --quelle video.mp4      (eigene Aufnahme statt Livebild)
Tasten:  q = beenden, t = Testauslösung
"""
import argparse
import csv
import os
import time
import tomllib

import cv2

from kamera import kamera_erstellen
from messung import Messung
from quelle import DateiQuelle, RtspQuelle, rtsp_url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.local.toml" if os.path.exists("config.local.toml") else "config.toml")
    ap.add_argument("--quelle", help="Videodatei statt Tapo-Livebild (zum Testen)")
    ap.add_argument("--ohne-fenster", action="store_true")
    args = ap.parse_args()

    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)

    quelle = DateiQuelle(args.quelle) if args.quelle else RtspQuelle(rtsp_url(cfg["tapo"]))
    kamera = kamera_erstellen(cfg["kamera"])
    messung = Messung(cfg["messung"])
    fenster = cfg["ausgabe"]["fenster"] and not args.ohne_fenster

    ordner = cfg["ausgabe"]["ordner"]
    os.makedirs(ordner, exist_ok=True)
    log_pfad = os.path.join(ordner, "log.csv")
    neu = not os.path.exists(log_pfad)
    log = open(log_pfad, "a", newline="", encoding="utf-8")
    schreiber = csv.writer(log, delimiter=";")
    if neu:
        schreiber.writerow(["zeit", "kmh", "richtung", "ueber_schwelle", "foto"])

    letzte_ausl = -1e9
    cooldown = cfg["kamera"]["cooldown_s"]
    mit_foto = cfg["kamera"]["typ"] != "aus"
    modus = "TESTMODUS mit Kamera" if mit_foto else "Zählmodus (keine Bilder)"
    print(f"Läuft – {modus}. Schwelle {cfg['messung']['schwelle_kmh']} km/h, Distanz {cfg['messung']['distanz_m']} m")

    try:
        while True:
            t, bild = quelle.lesen()
            if bild is None:
                if isinstance(quelle, DateiQuelle) and quelle.ende:
                    break
                time.sleep(0.005)
                continue

            for e in messung.verarbeiten(t, bild):
                ueber = e["kmh"] >= cfg["messung"]["schwelle_kmh"]
                ausl = mit_foto and e["ausloesen"] and (t - letzte_ausl) >= cooldown
                if ausl:
                    kamera.ausloesen()
                    letzte_ausl = t
                    messung.spuren[e["id"]].ausgeloest = True
                    # Tapo-Schnappschuss nur im Testmodus, im Zählmodus werden keine Bilder gespeichert
                    cv2.imwrite(os.path.join(ordner, f"{time.strftime('%Y%m%d_%H%M%S')}_{e['kmh']:.0f}kmh.jpg"), bild)
                zeit = time.strftime("%Y-%m-%d %H:%M:%S")
                schreiber.writerow([zeit, f"{e['kmh']:.1f}", e["richtung"], "ja" if ueber else "nein", "ja" if ausl else "nein"])
                log.flush()
                print(f"{zeit}  {e['kmh']:5.1f} km/h ({e['richtung']})" + ("  -> FOTO" if ausl else ""))

            if fenster:
                cv2.imshow("SpeedTrigger", messung.zeichnen(bild))
                taste = cv2.waitKey(1) & 0xFF
                if taste == ord("q"):
                    break
                if taste == ord("t"):
                    kamera.ausloesen()
    except KeyboardInterrupt:
        pass
    finally:
        quelle.schliessen()
        kamera.schliessen()
        log.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
