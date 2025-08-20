import os
import subprocess
import time
import pathlib
import datetime
import traceback

# ── Pfade ─────────────────────────────────────────────
SOURCE = pathlib.Path(__file__).resolve().parent
MAIN = SOURCE / "nakbot" / "__main__.py"
MODULES = SOURCE / "modules.txt"
BUILD = SOURCE / "nakbot.pyz"
REQS = SOURCE / "requirements.txt"
LOGS = SOURCE / "runner.log"

# ── Datei-Zeitstempel ─────────────────────────────────
def get_mtime(path):
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0

# ── Logging ───────────────────────────────────────────
def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    with LOGS.open("a", encoding="utf-8") as f:
        f.write(entry + "\n")

# ── Build mit shiv ────────────────────────────────────
def build():
    log("Baue neue .pyz …")
    try:
        subprocess.run([
            "shiv",
            "-c", "nakbot",
            "-o", str(BUILD),
            ".",
            "-r", str(REQS)
        ], cwd=str(SOURCE), check=True)
    except subprocess.CalledProcessError as e:
        log(f"Fehler beim Build-Vorgang mit shiv: {e}")
        traceback.print_exc()
        raise

# ── Ausführen + Logfile ───────────────────────────────
def run():
    log("Starte neue .pyz …")
    try:
        log_file = LOGS.open("a", encoding="utf-8")
        return subprocess.Popen(
            ["python3", str(BUILD)],
            stdout=log_file,
            stderr=log_file
        )
    except Exception as e:
        log(f"Fehler beim Start der .pyz: {e}")
        traceback.print_exc()
        raise

# ── Hauptfunktion ─────────────────────────────────────
def main():
    log("Runner gestartet")
    try:
        last_mtime_main = get_mtime(MAIN)
        last_mtime_modules = get_mtime(MODULES)

        if not BUILD.exists():
            log("nakbot.pyz nicht gefunden – baue neu …")
            build()

        process = run()

        while True:
            time.sleep(3)

            # ── Absturz erkannt ──
            if process.poll() is not None:
                log(f"Bot-Prozess unerwartet beendet mit Code {process.returncode} – Neustart …")
                process = run()

            # ── Codeänderung erkannt ──
            changed = False

            current_main = get_mtime(MAIN)
            if current_main != last_mtime_main:
                log("__main__.py wurde geändert.")
                changed = True
                last_mtime_main = current_main

            current_modules = get_mtime(MODULES)
            if current_modules != last_mtime_modules:
                log("modules.txt wurde geändert.")
                changed = True
                last_mtime_modules = current_modules

            if changed:
                log("Neubaue .pyz wegen Änderung …")
                process.terminate()
                process.wait()
                build()
                process = run()

    except Exception as e:
        log(f"[FATAL] Runner abgestürzt: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
