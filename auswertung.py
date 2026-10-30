"""Auswertung der Zählung: Anteil zu schnell, V85, Verteilung, Tagesverlauf.

python auswertung.py                                   # ganze Messung
python auswertung.py --von "2026-11-02" --bis "2026-11-09"
python auswertung.py --veroeffentlichen               # Bericht nach docs/ kopieren und auf GitHub pushen
python auswertung.py --veroeffentlichen --alle 60     # Live-Modus: jede Stunde aktualisieren
Ergebnis: Zusammenfassung in der Konsole + messungen/bericht.html
"""
import argparse
import csv
import html
import os
import shutil
import subprocess
import time
import tomllib
from collections import Counter, defaultdict
from datetime import datetime


def perzentil(werte, p):
    s = sorted(werte)
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100
    i = int(k)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


def kennzahlen(werte, limit, grenze):
    n = len(werte)
    if n == 0:
        return dict(n=0, ueber_limit=0, zu_schnell=0, p_limit=0, p_zu=0, v50=0, v85=0, vmax=0)
    ul = sum(v > limit for v in werte)
    zu = sum(v > grenze for v in werte)
    return dict(n=n, ueber_limit=ul, zu_schnell=zu, p_limit=100 * ul / n, p_zu=100 * zu / n,
                v50=perzentil(werte, 50), v85=perzentil(werte, 85), vmax=max(werte))


def argumente():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.local.toml" if os.path.exists("config.local.toml") else "config.toml")
    ap.add_argument("--von", help="z. B. 2026-11-02 oder '2026-11-02 06:00' (Standard: [auswertung] ab)")
    ap.add_argument("--bis", help="exklusiv, z. B. 2026-11-09")
    ap.add_argument("--veroeffentlichen", action="store_true", help="Bericht nach docs/ kopieren und pushen")
    ap.add_argument("--alle", type=int, metavar="MIN", help="Live-Modus: alle MIN Minuten wiederholen")
    return ap.parse_args()


def bericht(args):
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    limit = cfg["auswertung"]["limit_kmh"]
    grenze = limit + cfg["auswertung"]["toleranz_kmh"]
    ordner = cfg["ausgabe"]["ordner"]

    ab = args.von or cfg["auswertung"].get("ab")  # Start der gültigen Messung (z. B. nach Kalibrierung)
    von = datetime.fromisoformat(ab) if ab else None
    bis = datetime.fromisoformat(args.bis) if args.bis else None

    daten = []
    with open(os.path.join(ordner, "log.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            t = datetime.fromisoformat(r["zeit"])
            if (von and t < von) or (bis and t >= bis):
                continue
            daten.append((t, float(r["kmh"]), r["richtung"]))
    # Unplausible Werte (z. B. Fehlzuordnungen bei Dunkelheit) nachträglich verwerfen
    plaus = cfg["messung"].get("max_kmh", 1e9)
    verworfen = [d for d in daten if d[1] > plaus]
    daten = [d for d in daten if d[1] <= plaus]
    if not daten:
        raise SystemExit("Keine Messungen im gewählten Zeitraum.")

    alle = [v for _, v, _ in daten]
    gesamt = kennzahlen(alle, limit, grenze)
    pro_richtung = {r: kennzahlen([v for _, v, rr in daten if rr == r], limit, grenze)
                    for r in sorted({r for *_, r in daten})}
    pro_stunde = defaultdict(list)
    for t, v, _ in daten:
        pro_stunde[t.hour].append(v)
    klassen = Counter(min(int(v // 5) * 5, 70) for v in alle)
    t0, t1 = min(d[0] for d in daten), max(d[0] for d in daten)
    tage = max((t1 - t0).total_seconds() / 86400, 1 / 1440)

    # --- Konsole ----------------------------------------------------------------------
    dauer = f"{tage:.1f} Tage" if tage >= 1 else f"{tage * 24:.1f} Stunden"
    schnitt = f"Ø {gesamt['n'] / tage:.0f} pro Tag" if tage >= 1 else "Tagesschnitt erst ab 1 Tag Messdauer"
    print(f"Zeitraum: {t0:%d.%m.%Y %H:%M} – {t1:%d.%m.%Y %H:%M}  ({dauer})")
    print(f"Fahrzeuge: {gesamt['n']}  ({schnitt})")
    print(f"Über {limit:.0f} km/h:            {gesamt['ueber_limit']:5d}  = {gesamt['p_limit']:.1f} %")
    print(f"Zu schnell (> {grenze:.0f} km/h):    {gesamt['zu_schnell']:5d}  = {gesamt['p_zu']:.1f} %")
    if verworfen:
        stunden_v = Counter(f"{d[0]:%H}" for d in verworfen)
        print(f"Verworfen (> {plaus:.0f} km/h, unplausibel): {len(verworfen)}  –  nach Stunde: "
              + ", ".join(f"{h} Uhr: {n}" for h, n in sorted(stunden_v.items())))
    print(f"V50 {gesamt['v50']:.1f}  |  V85 {gesamt['v85']:.1f}  |  Vmax {gesamt['vmax']:.1f} km/h")

    # --- HTML-Bericht -----------------------------------------------------------------
    def zeile(name, k):
        return (f"<tr><td>{html.escape(name)}</td><td>{k['n']}</td><td>{k['p_limit']:.1f} %</td>"
                f"<td><b>{k['p_zu']:.1f} %</b></td><td>{k['v50']:.1f}</td><td><b>{k['v85']:.1f}</b></td>"
                f"<td>{k['vmax']:.1f}</td></tr>")

    max_h = max(len(v) for v in pro_stunde.values())
    stunden = ""
    for h in range(24):
        w = pro_stunde.get(h, [])
        k = kennzahlen(w, limit, grenze)
        breite = 100 * len(w) / max_h if w else 0
        rot = breite * k["p_zu"] / 100
        stunden += (f"<div class='r'><span class='l'>{h:02d}–{h + 1:02d}</span>"
                    f"<span class='bar'><i style='width:{breite:.1f}%'></i><i class='zu' style='width:{rot:.1f}%'></i></span>"
                    f"<span class='v'>{len(w)} · {k['p_zu']:.0f} %</span></div>")

    max_k = max(klassen.values())
    vert = ""
    for k in range(0, 75, 5):
        anz = klassen.get(k, 0)
        label = f"{k}–{k + 5}" if k < 70 else "70+"
        cls = "zu" if k >= grenze else ("grenz" if k + 5 > limit else "")
        vert += (f"<div class='r'><span class='l'>{label}</span><span class='bar'>"
                 f"<i class='{cls}' style='width:{100 * anz / max_k:.1f}%'></i></span><span class='v'>{anz}</span></div>")

    namen = {"a_nach_b": "Richtung A → B", "b_nach_a": "Richtung B → A"}
    tabelle = zeile("Total", gesamt) + "".join(zeile(namen.get(r, r), k) for r, k in pro_richtung.items())

    bericht = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="600"><title>Verkehrszählung</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--lin:#e5e5ea;--ok:#5b8def;--grenz:#f2b84b;--zu:#e5484d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151517;--fg:#f2f2f7;--mut:#a1a1a6;--lin:#2c2c2e}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:17px;margin:32px 0 10px}} .mut{{color:var(--mut)}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
.kpi div{{border:1px solid var(--lin);border-radius:10px;padding:12px}} .kpi b{{display:block;font-size:26px}}
.kpi .rot b{{color:var(--zu)}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
td,th{{padding:7px 8px;border-bottom:1px solid var(--lin);text-align:right}} td:first-child,th:first-child{{text-align:left}}
.r{{display:flex;align-items:center;gap:10px;margin:3px 0;font-variant-numeric:tabular-nums}}
.l{{width:56px;color:var(--mut);font-size:13px}} .v{{width:80px;font-size:13px}}
.bar{{flex:1;height:14px;position:relative}} .bar i{{position:absolute;left:0;top:0;bottom:0;background:var(--ok);border-radius:3px}}
.bar i.zu{{background:var(--zu)}} .bar i.grenz{{background:var(--grenz)}}
.note{{font-size:13px;color:var(--mut);margin-top:32px;border-top:1px solid var(--lin);padding-top:12px}}
</style></head><body>
<h1>Verkehrszählung – Geschwindigkeit</h1>
<div class="mut">{t0:%d.%m.%Y %H:%M} – {t1:%d.%m.%Y %H:%M} · signalisiert {limit:.0f} km/h · Messtoleranz {grenze - limit:.0f} km/h<br>Stand: {datetime.now():%d.%m.%Y %H:%M}</div>
<div class="kpi">
<div><span class="mut">Fahrzeuge</span><b>{gesamt['n']}</b><span class="mut">{schnitt}</span></div>
<div class="rot"><span class="mut">Zu schnell (&gt; {grenze:.0f})</span><b>{gesamt['p_zu']:.1f} %</b><span class="mut">{gesamt['zu_schnell']} Fahrzeuge</span></div>
<div><span class="mut">Über {limit:.0f} km/h</span><b>{gesamt['p_limit']:.1f} %</b><span class="mut">ohne Toleranz</span></div>
<div><span class="mut">V85</span><b>{gesamt['v85']:.1f}</b><span class="mut">km/h</span></div>
</div>
<h2>Übersicht</h2>
<table><tr><th></th><th>Anzahl</th><th>&gt; {limit:.0f}</th><th>&gt; {grenze:.0f}</th><th>V50</th><th>V85</th><th>Vmax</th></tr>{tabelle}</table>
<h2>Verteilung (km/h)</h2>{vert}
<h2>Tagesverlauf <span class="mut">(Anzahl · Anteil zu schnell, rot = zu schnell)</span></h2>{stunden}
<div class="note">V85 = Geschwindigkeit, die 85 % der Fahrzeuge nicht überschreiten – die übliche Kennzahl
in der Verkehrsplanung. Eigene, nicht geeichte Messung mit Videoanalyse; Werte sind Richtwerte.
Gezählt werden nur Fahrzeuge, die beide Messlinien passieren.
{f"{len(verworfen)} unplausible Messungen über {plaus:.0f} km/h wurden verworfen." if verworfen else ""}</div>
</body></html>"""
    pfad = os.path.join(ordner, "bericht.html")
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(bericht)
    print(f"Bericht: {pfad}")
    return pfad


def git(*befehl):
    r = subprocess.run(["git", *befehl], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r.stdout


def veroeffentlichen(pfad):
    """Bericht nach docs/bericht.html kopieren und nur diese Datei committen und pushen."""
    ziel = os.path.join("docs", "bericht.html")
    shutil.copyfile(pfad, ziel)
    git("add", ziel)
    if not git("status", "--porcelain", "--", ziel).strip():
        print("Webseite: keine Änderung")
        return
    git("commit", "-m", f"Live-Bericht {datetime.now():%d.%m.%Y %H:%M}", "--", ziel)
    git("pull", "--rebase", "--autostash")
    git("push")
    print("Webseite: aktualisiert -> https://christophejenzer-collab.github.io/speedtrigger/bericht.html")


def main():
    args = argumente()
    while True:
        try:
            pfad = bericht(args)
            if args.veroeffentlichen:
                veroeffentlichen(pfad)
        except (RuntimeError, SystemExit) as e:
            if not args.alle:
                raise
            print(f"Fehler, neuer Versuch beim nächsten Durchlauf: {e}")
        if not args.alle:
            break
        print(f"Nächste Aktualisierung in {args.alle} min (Ctrl+C beendet)")
        time.sleep(args.alle * 60)


if __name__ == "__main__":
    main()
