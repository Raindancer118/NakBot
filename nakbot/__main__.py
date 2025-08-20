# nakbot/__main__.py
import io, re, time, sys, os, pathlib, logging, requests, urllib3, socket
from requests.exceptions import ConnectionError, HTTPError, Timeout
from PyPDF2 import PdfReader
from plyer import notification

# ── Logging & TLS-Warnungen ───────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
urllib3.disable_warnings()
requests.packages.urllib3.disable_warnings()

# ── Konstante Defaults ─────────
DEFAULT_PAUSE = 600

LOGIN_URL = ("https://cis.nordakademie.de/"
             "?tx_felogin_login%5Baction%5D=login"
             "&tx_felogin_login%5Bcontroller%5D=Login")
OVERVIEW_URL = "https://cis.nordakademie.de/mein-profil/mein-postfach/leistungsuebersicht"
TRANSCRIPT_URL = ("https://cis.nordakademie.de/mein-profil/mein-postfach/leistungsuebersicht"
                  "?tx_nagrades_nagradesmodules%5Baction%5D=transcript"
                  "&tx_nagrades_nagradesmodules%5Bcontroller%5D=Notenverwaltung"
                  "&tx_nagrades_nagradesmodules%5BcurriculumId%5D=161"
                  "&tx_nagrades_nagradesmodules%5Blang%5D=de"
                  "&cHash=8260f27159a08bb9c66a7a4d1dd669b9")
PID = "706@f6c1611250fb5040d7c1b2438b0c8473daa7431e"
HEAD = {"User-Agent": "Mozilla/5.0", "Connection": "close"}

COUNTER_FILE = pathlib.Path(sys.argv[0]).resolve().parent / "attempt_counter.txt"
MODULES_PATH = pathlib.Path(sys.argv[0]).resolve().parent / "modules.txt"

def load_credentials() -> tuple[str, str]:
    """
    Reihenfolge:
    1) ENV: NAKBOT_USERNAME / NAKBOT_PASSWORD
    2) Datei im Projektordner: ./.config/nakbot/credentials.toml
    3) Datei im Home: ~/.config/nakbot/credentials.toml
    """
    # 1) ENV prüfen
    u = os.getenv("NAKBOT_USERNAME")
    p = os.getenv("NAKBOT_PASSWORD")
    if u and p:
        logging.info("Credentials: per ENV gefunden.")
        return u, p
    else:
        logging.info("Credentials: keine ENV-Variablen gesetzt.")

    # 2) Projektordner prüfen
    project_root = pathlib.Path(__file__).resolve().parent.parent
    project_conf = project_root / ".config" / "nakbot" / "credentials.toml"
    logging.info(f"Credentials: prüfe Projektpfad {project_conf}")
    if project_conf.exists():
        cred_path = project_conf
    else:
        # 3) Fallback: Home
        home_conf = pathlib.Path.home() / ".config" / "nakbot" / "credentials.toml"
        logging.info(f"Credentials: Projektdatei fehlt – probiere {home_conf}")
        cred_path = home_conf

    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore

    try:
        data = tomllib.loads(cred_path.read_text(encoding="utf-8"))
    except Exception as e:
        logging.error(f"Credentials-Datei {cred_path} konnte nicht gelesen werden: {e}")
        raise

    u = str(data.get("username", "")).strip()
    p = str(data.get("password", "")).strip()

    if not u or not p:
        logging.error(f"Credentials-Datei {cred_path} unvollständig: username={bool(u)} password={bool(p)}")
        raise RuntimeError(f"Credentials unvollständig in {cred_path}")

    logging.info(f"Credentials: erfolgreich geladen aus Datei {cred_path}")
    return u, p

# ── GUI/IPC Helpers ───────────────────────────────────
def _gui_send(key: str, value: str):
    sock_path = os.environ.get("GUI_STATUS")
    if not sock_path:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock_path)
            s.sendall(f"{key}:{value}\n".encode())
    except Exception:
        pass

def _gui_progress(kb: int):
    sock_path = os.environ.get("GUI_PROGRESS")
    if not sock_path:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock_path)
            s.sendall(f"{kb}\n".encode())
    except Exception:
        pass

def toast(title: str, msg: str) -> None:
    notification.notify(title=title, message=msg, timeout=5)

# ── Dynamische Pause ───────────────
def get_dynamic_pause(default: int = DEFAULT_PAUSE) -> int:
    sock_path = os.environ.get("PAUSE_SOCKET")
    if not sock_path:
        return default
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock_path)
            s.sendall(b"REQ\n")
            s.settimeout(1)
            data = s.recv(32).decode().strip()
            return int(data)
    except Exception:
        return default

# ── Module laden ───────────────────
def load_modules() -> dict:
    try:
        lines = [line.strip() for line in MODULES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        patterns = {m: re.compile(rf"{re.escape(m)}\s+([^\s]+)", re.I) for m in lines}
        logging.info(f"{len(patterns)} Modul(e) geladen aus modules.txt")
        return patterns
    except FileNotFoundError:
        logging.error("modules.txt nicht gefunden.")
        return {}

# ── Login ──────────────────────────
def login(sess: requests.Session, username: str, password: str, retries: int = 3, limit_s: int = 20) -> None:
    _gui_send("STATUS", "Logging in…")
    for attempt in range(1, retries + 1):
        try:
            logging.info(f"Logon … (Versuch {attempt})")
            t0 = time.time()

            sess.post(LOGIN_URL, data={
                "user": username, "pass": password,
                "logintype": "login", "pid": PID, "referer": OVERVIEW_URL
            }, headers=HEAD, verify=False, timeout=limit_s)

            resp = sess.get(OVERVIEW_URL, headers=HEAD, verify=False, timeout=limit_s)

            if time.time() - t0 > limit_s:
                raise Timeout("Login dauerte zu lange")

            if "Benutzeranmeldung" in resp.text:
                toast("Login failed", "Check credentials")
                _gui_send("LOGIN", "FAIL")
                raise RuntimeError("bad credentials")

            logging.info("Logged in ✓")
            _gui_send("LOGIN", "OK")
            _gui_send("STATUS", "Idle")
            return

        except (Timeout, ConnectionError) as err:
            logging.warning(f"Login-Timeout: {err} – neuer Versuch …")
            time.sleep(2)

    _gui_send("LOGIN", "FAIL")
    raise RuntimeError("Login failed after retries")

# ── Counter ────────────────────────
def load_counter() -> int:
    try:
        return int(COUNTER_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0

def save_counter(value: int) -> None:
    COUNTER_FILE.write_text(f"{value}\n")

# ── PDF Download/Parsing ───────────
_last_printed_kb = 0

def _print_progress(done_bytes: int) -> None:
    global _last_printed_kb
    done_kb = done_bytes // 1024
    while _last_printed_kb < done_kb:
        sys.stdout.write("│")
        _last_printed_kb += 1
    sys.stdout.flush()

def stream_pdf(sess: requests.Session, retries: int = 3) -> io.BytesIO:
    logging.info("Verbindung zum Transcript wird aufgebaut …")
    _gui_send("STATUS", "Downloading Transcript")

    for attempt in range(1, retries + 1):
        try:
            logging.info(f"Download-Versuch {attempt} …")
            with sess.get(TRANSCRIPT_URL, headers=HEAD, stream=True, timeout=30, verify=False) as r:
                r.raise_for_status()

                global _last_printed_kb
                _last_printed_kb = 0

                buf = io.BytesIO()
                size = 0

                for chunk in r.iter_content(1024):
                    buf.write(chunk)
                    size += len(chunk)

                    kb = size // 1024
                    _print_progress(size)
                    _gui_progress(kb)

                buf.seek(0)
                sys.stdout.write("\n")
                logging.info(f"PDF erfolgreich geladen ({size/1024:.1f} kB) ✓")
                _gui_progress(0)
                return buf

        except (ConnectionError, HTTPError) as err:
            logging.warning(f"Download-Fehler: {err} – nächster Versuch …")
            _gui_send("STATUS", "Waiting for Server Response")
            time.sleep(2 ** attempt)

    raise RuntimeError("PDF download failed")

def pdf_text(buf: io.BytesIO) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(buf).pages)

def check_modules(sess: requests.Session, patterns: dict) -> None:
    logging.info("Analysiere PDF …")
    _gui_send("STATUS", "Parsing PDF")

    buf = stream_pdf(sess)
    try:
        text = pdf_text(buf)
    finally:
        buf.close()

    for module, pattern in patterns.items():
        m = pattern.search(text)
        if not m:
            logging.info(f"{module}: Zeile fehlt")
            continue

        grade = m.group(1).strip()
        if grade == "#":
            logging.info(f"{module}: noch #")
        else:
            msg = f"{module}: {grade}"
            logging.info(msg)
            toast("Grade update", msg)

    _gui_send("STATUS", "Idle")

# ── Main ───────────────────────────
def main():
    attempts = load_counter()
    reload_interval = 5
    error_count = 0
    patterns = load_modules()

    if not patterns:
        logging.error("Keine gültigen Module geladen – beende Bot.")
        _gui_send("STATUS", "Keine Module")
        return

    # Credentials laden
    try:
        username, password = load_credentials()
    except Exception as err:
        logging.error(f"Credentials-Fehler: {err}")
        _gui_send("STATUS", "Credentials fehlen/fehlerhaft")
        return

    session = requests.Session()

    try:
        login(session, username, password)
    except RuntimeError as err:
        logging.error(f"Login fehlgeschlagen: {err}")
        return

    # Lokale Pause-Variable statt globalem PAUSE
    pause = DEFAULT_PAUSE

    while True:
        pause = get_dynamic_pause(default=pause)

        attempts += 1
        save_counter(attempts)

        if attempts % reload_interval == 1:
            patterns = load_modules()
            if not patterns:
                logging.warning("Keine Module geladen – überspringe Durchlauf.")
                _gui_send("STATUS", "Keine Module")
                time.sleep(pause)
                continue

        if error_count > 0:
            logging.info("Versuche erneuten Login wegen vorherigem Fehler …")
            _gui_send("STATUS", "Reauthenticating…")
            try:
                login(session, username, password)
                error_count = 0
            except RuntimeError as err:
                logging.error(f"Login erneut fehlgeschlagen: {err}")
                time.sleep(pause)
                continue

        logging.info(f"Check #{attempts}")

        try:
            check_modules(session, patterns)
            error_count = 0
        except Exception as err:
            logging.warning(f"Fehler bei der Analyse: {err}")
            _gui_send("STATUS", "Fehler bei Analyse")
            error_count += 1

        time.sleep(pause)

if __name__ == "__main__":
    main()
