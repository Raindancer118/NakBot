# 🎓 NAK Notenbot

Der **NAK Notenbot** ist ein Python-Tool, das automatisch die Notenübersicht im CIS der NORDAKADEMIE abruft, Module überwacht und bei neuen Einträgen Benachrichtigungen anzeigt.  
Es kann sowohl im **Terminal** als auch über eine **grafische Benutzeroberfläche (GUI)** betrieben werden.

---

## 🚀 Features

- Automatisches Login ins CIS der NORDAKADEMIE  
- Herunterladen und Parsen des **Leistungstranskripts (PDF)**  
- Überwachung definierter **Module** (z. B. „Diskrete Mathematik II“)  
- Desktop-Benachrichtigungen bei neuen Noten  
- Konfigurierbares Prüfintervall  
- **GUI** mit Start/Stop, Fortschrittsbalken und Live-Logs  
- Automatischer Neustart bei Absturz oder Codeänderungen  

---

## 📦 Installation

### Voraussetzungen
- **Python 3.11+**
- Abhängigkeiten aus `requirements.txt`
- `shiv` (für das Erstellen von `.pyz`-Bundles)

```bash
pip install -r requirements.txt
pip install shiv

🔑 Konfiguration
Zugangsdaten

Der Bot benötigt deine NAK-Zugangsdaten.
Es gibt zwei Möglichkeiten:

    Umgebungsvariablen setzen:

export NAKBOT_USERNAME="20066"
export NAKBOT_PASSWORD="dein-passwort"

TOML-Datei erstellen:
~/.config/nakbot/credentials.toml

    username = "20066"
    password = "dein-passwort"

Module

In der Datei modules.txt legst du fest, welche Module überwacht werden sollen.
Einfach pro Zeile den Namen des Moduls angeben, wie er im Transcript steht:

Diskrete Mathematik II
Programmieren I
BWL I

▶ Nutzung
1. GUI starten

python3 gui_runner.py

    Start/Stop des Bots per Knopfdruck

    Fortschrittsanzeige beim PDF-Download

    Statusmeldungen (Login, Analyse, Fehler)

    Live-Logausgabe

2. Terminal-Version starten

python3 runner.py

    Baut bei Änderungen automatisch neu (nakbot.pyz)

    Neustart bei Absturz

🔨 Entwicklermodus (Build)

Zum Erstellen der .pyz-Datei (Standalone-Ausführung):

shiv -c nakbot -o nakbot.pyz . -r requirements.txt

Danach ausführbar mit:

python3 nakbot.pyz

📂 Projektstruktur

├── gui_runner.py      # GUI-Start
├── runner.py          # Terminal-Runner mit Autorebuild
├── setup.py           # setuptools entrypoint
├── nakbot/__main__.py # Bot-Logik
├── modules.txt        # Module, die überwacht werden
├── requirements.txt   # Abhängigkeiten
└── runner.log         # Logdatei

🖥 Deployment (z. B. GitHub)

    Quellcode ins Repo pushen

    Nutzer können das Projekt mit git clone herunterladen

    Installation über pip install -r requirements.txt

    Start via python3 gui_runner.py oder Build mit shiv

⚠️ Hinweise

    Der Bot ist nur für eigene Accounts gedacht.

    Achtung: Missbrauch (z. B. Massenabfragen) könnte gegen die Nutzungsbedingungen der NORDAKADEMIE verstoßen.