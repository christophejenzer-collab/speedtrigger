# SpeedTrigger

Verkehrszählung mit Geschwindigkeitsmessung aus dem Livebild einer **TP-Link Tapo**-Kamera – mit optionaler Auslösung einer **Canon EOS** über das Canon EDSDK für Testfahrten.

Ziel: herausfinden, welcher Anteil der Fahrzeuge in einem Strassenabschnitt schneller fährt als erlaubt – ohne Bilder der Fahrzeuge zu speichern.

🌐 Projektseite: https://christophejenzer-collab.github.io/speedtrigger/

## So funktioniert es
1. Im Tapo-Bild werden zwei Messlinien A und B gesetzt, deren reale Distanz vor Ort gemessen wird.
2. Fahrzeuge werden per Hintergrundsubtraktion erkannt und verfolgt.
3. Aus der Zeit zwischen Linie A und B ergibt sich die Geschwindigkeit. Der Überquerungszeitpunkt wird zwischen zwei Bildern interpoliert, das gleicht die tiefe Bildrate der Tapo aus.
4. Jede Messung landet in `messungen/log.csv`, die Auswertung erzeugt daraus einen HTML-Bericht.

## Betriebsarten
| `[kamera] typ` | Zweck | Bilder |
|---|---|---|
| `"aus"` | **Zählmodus**: jedes Fahrzeug wird mit km/h und Richtung erfasst | keine |
| `"edsdk"` | **Testlauf**: zusätzlich EOS-Foto über `schwelle_kmh` (z. B. eigene Kontrollfahrt) | ja |
| `"dummy"` | Test ohne Kamera, Auslösung nur im Log | keine |

Testläufe mit eigenem Ordner (`[ausgabe] ordner = "testlauf"`), damit sie die Statistik nicht verfälschen.

## Voraussetzungen
- Windows 10/11, Python 3.11+ (64-bit)
- `pip install -r requirements.txt`
- Tapo-Kamera mit RTSP und eingerichtetem **Kamerakonto** (Tapo-App → Erweiterte Einstellungen)
- Nur für den Testlauf: **Canon EDSDK** (kostenlos nach Registrierung im Canon Developer Programme, nicht Teil dieses Repositorys), EOS per USB, EOS Utility geschlossen. Getestete Zielmodelle: EOS R, EOS 500D.

## Einrichten
```powershell
$env:TAPO_USER="..."; $env:TAPO_PASS="..."   # Kamerakonto der Tapo
python kalibrieren.py                        # Linie A und B anklicken, mit s speichern
```
Eigene Werte (IP der Tapo, gemessene Distanz `distanz_m`) gehören in eine Kopie `config.local.toml`. Sie wird automatisch verwendet, falls vorhanden, und von Git ignoriert:
```powershell
copy config.toml config.local.toml
```

```powershell
python speedtrigger.py                       # Zählung starten (q = beenden)
python auswertung.py                         # Bericht erzeugen
python auswertung.py --von 2026-11-02 --bis 2026-11-09
```

## Auswertung
Anzahl Fahrzeuge, Anteil über Limit, Anteil zu schnell (Limit + Toleranz), V50/V85/Vmax, je Richtung, Verteilung und Tagesverlauf. Empfehlung: mindestens 7 volle Tage messen.
V85 ist die Geschwindigkeit, die 85 % der Fahrzeuge nicht überschreiten – die übliche Kennzahl in der Verkehrsplanung.

## Genauigkeit und Grenzen
- Kein geeichtes Messgerät – Werte sind Richtwerte, nicht für Bussen oder Anzeigen verwendbar.
- Vor dem Einsatz mit Kontrollfahrten kalibrieren (Geschwindigkeit per GPS-App, nicht Tacho).
- Tapo seitlich zur Strasse montieren, Messstrecke 15–20 m.
- Nachts sind Fehlmessungen durch Scheinwerfer und Infrarot-Umschaltung möglich.
- Der RTSP-Stream hat 0,5–2 s Verzögerung: Für den Testlauf die EOS auf eine Stelle **nach** Linie B richten (Vorlauf ≈ Geschwindigkeit in m/s × Verzögerung).

## Datenschutz
Im Zählmodus werden keine Bilder gespeichert, nur Zeit, Geschwindigkeit und Richtung. Wer Fahrzeuge oder Personen im öffentlichen Raum fotografiert, bearbeitet Personendaten (in der Schweiz nach DSG) und ist selbst für die Rechtmässigkeit verantwortlich.

## Dateien
| Datei | Zweck |
|---|---|
| `speedtrigger.py` | Hauptprogramm |
| `messung.py` | Bewegungserkennung, Tracking, Linienmessung |
| `quelle.py` | Tapo-RTSP (nur neuestes Bild) / Videodatei |
| `kamera.py` | EDSDK-Ansteuerung per ctypes, Dummy, Zählmodus |
| `kalibrieren.py` | Messlinien per Mausklick setzen |
| `auswertung.py` | Statistik und HTML-Bericht |
| `docs/` | Projektseite (GitHub Pages) |

## Hinweis
Privates Projekt. Canon, EOS und EDSDK sind Marken der Canon Inc.; Tapo ist eine Marke von TP-Link. Keine Verbindung zu oder Unterstützung durch diese Unternehmen.

## Lizenz
MIT – siehe [LICENSE](LICENSE).
