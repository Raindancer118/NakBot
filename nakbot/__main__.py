# nakbot/__main__.py
import io, re, time, sys, os, pathlib, logging, requests, urllib3, socket, inspect, errno
from requests.exceptions import ConnectionError, HTTPError, Timeout
from PyPDF2 import PdfReader
from plyer import notification

# ───────────────────────────────────────────────────────────────────────────────
# DEVLOG: Ultra-Verbose Developer Logging
# Aktivieren: set DEVLOG = True
# ───────────────────────────────────────────────────────────────────────────────

def _parse_bool(val: str | None) -> bool:
    if val is None:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on", "y"}

DEVLOG = False

# Logging-Setup
LOG_LEVEL = logging.DEBUG if DEVLOG else logging.INFO
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(message)s")
urllib3.disable_warnings()
requests.packages.urllib3.disable_warnings()

PKG_ROOT = pathlib.Path(__file__).resolve().parent           # .../nakbot
REPO_ROOT = PKG_ROOT.parent                                  # Projekt-Root
MODULE_NAME = __name__

def dlog(module: str, msg: str):
    """Developer-Log nur bei DEVLOG. Modulpräfix immer vorn dran."""
    if DEVLOG:
        logging.debug(f"[{module}] {msg}")

def _short_repr(x, maxlen: int = 120):
    try:
        s = repr(x)
    except Exception:
        s = f"<unrepr {type(x).__name__}>"
    if len(s) > maxlen:
        s = s[:maxlen-3] + "..."
    return s

# ── Tracing jeder Zeile und Variablenänderungen (nur bei DEVLOG) ───────────────
_TRACE_FRAMES: dict[int, dict] = {}

def _should_trace_file(filename: str) -> bool:
    # nur unsere Files im Repo (Performance & Signal)
    try:
        return str(filename).startswith(str(REPO_ROOT))
    except Exception:
        return False

def _locals_diff(prev: dict, curr: dict) -> tuple[dict, dict, dict]:
    """returns (added, changed, removed)"""
    added = {k: curr[k] for k in curr.keys() - prev.keys()}
    removed = {k: prev[k] for k in prev.keys() - curr.keys()}
    changed = {k: (prev[k], curr[k]) for k in curr.keys() & prev.keys() if prev[k] is not curr[k] or prev[k] != curr[k]}
    return added, changed, removed

def _trace(frame, event, arg):
    if not DEVLOG:
        return
    filename = frame.f_code.co_filename
    if not _should_trace_file(filename):
        return _trace
    mod = frame.f_globals.get("__name__", pathlib.Path(filename).name)

    if event == "call":
        try:
            args_info = inspect.getargvalues(frame)
            args_repr = {name: _short_repr(args_info.locals.get(name)) for name in (args_info.args or [])}
            if args_info.varargs:
                args_repr["*args"] = _short_repr(args_info.locals.get(args_info.varargs))
            if args_info.keywords:
                args_repr["**kwargs"] = _short_repr(args_info.locals.get(args_info.keywords))
            dlog(mod, f"CALL {frame.f_code.co_name}() @ {pathlib.Path(filename).name}:{frame.f_lineno} ARGS={args_repr}")
            _TRACE_FRAMES[id(frame)] = dict(args_info.locals)
        except Exception as e:
            dlog(mod, f"CALL {frame.f_code.co_name}() (arg parse error: {e})")
        return _trace

    if event == "line":
        try:
            prev = _TRACE_FRAMES.get(id(frame), {})
            curr = dict(frame.f_locals)
            add, chg, rem = _locals_diff(prev, curr)
            if add or chg or rem:
                parts = []
                if add:
                    parts.append("ADDED={" + ", ".join(f"{k}={_short_repr(v)}" for k,v in add.items()) + "}")
                if chg:
                    parts.append("CHANGED={" + ", ".join(f"{k}: {_short_repr(a)} -> {_short_repr(b)}" for k,(a,b) in chg.items()) + "}")
                if rem:
                    parts.append("REMOVED={" + ", ".join(f"{k}={_short_repr(v)}" for k,v in rem.items()) + "}")
                dlog(mod, f"LINE {frame.f_code.co_name}() @ {pathlib.Path(filename).name}:{frame.f_lineno} " + " ".join(parts))
            _TRACE_FRAMES[id(frame)] = curr
        except Exception as e:
            dlog(mod, f"LINE trace error: {e}")
        return _trace

    if event == "return":
        try:
            dlog(mod, f"RETURN {frame.f_code.co_name}() -> {_short_repr(arg)}")
        except Exception:
            dlog(mod, f"RETURN {frame.f_code.co_name}()")
        _TRACE_FRAMES.pop(id(frame), None)
        return _trace

    if event == "exception":
        try:
            exc_type, exc_val, exc_tb = arg
            dlog(mod, f"EXC in {frame.f_code.co_name}(): {exc_type.__name__}: {_short_repr(exc_val)}")
        except Exception:
            dlog(mod, "EXC (unrepr)")
        return _trace

    return _trace

if DEVLOG:
    sys.settrace(_trace)
    dlog(MODULE_NAME, f"DEVLOG enabled. Tracing under {REPO_ROOT}")

# ───────────────────────────────────────────────────────────────────────────────
# Konstanten / URLs / Defaults
# ───────────────────────────────────────────────────────────────────────────────
# Pausen Dauer in **Sekunden**
DEFAULT_PAUSE = 5

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

# ───────────────────────────────────────────────────────────────────────────────
# Credentials laden (ENV → ./ .config/nakbot/credentials.toml → ~/.config/...)
# ───────────────────────────────────────────────────────────────────────────────

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
        dlog(MODULE_NAME, f"ENV USERNAME={_short_repr(u)} PASSWORD=*** (versteckt)")
        return u, p
    logging.info("Credentials: keine ENV-Variablen gesetzt.")

    # 2) Projektordner prüfen
    project_conf = (REPO_ROOT / ".config" / "nakbot" / "credentials.toml")
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
        raw = cred_path.read_text(encoding="utf-8")
        dlog(MODULE_NAME, f"Credentials: lese Datei {cred_path}, size={len(raw)}")
        data = tomllib.loads(raw)
    except Exception as e:
        logging.error(f"Credentials-Datei {cred_path} konnte nicht gelesen werden: {e}")
        raise

    u = str(data.get("username", "")).strip()
    p = str(data.get("password", "")).strip()

    if not u or not p:
        logging.error(f"Credentials-Datei {cred_path} unvollständig: username={bool(u)} password={bool(p)}")
        raise RuntimeError(f"Credentials unvollständig in {cred_path}")

    logging.info(f"Credentials: erfolgreich geladen aus Datei {cred_path}")
    dlog(MODULE_NAME, f"FILE USERNAME={_short_repr(u)} PASSWORD=*** (versteckt)")
    return u, p

# ───────────────────────────────────────────────────────────────────────────────
# GUI/IPC Helpers
# ───────────────────────────────────────────────────────────────────────────────

def _gui_send(key: str, value: str):
    sock_path = os.environ.get("GUI_STATUS")
    dlog(MODULE_NAME, f"_gui_send key={key!r} value={value!r} path={sock_path}")
    if not sock_path:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock_path)
            s.sendall(f"{key}:{value}\n".encode())
    except Exception as e:
        dlog(MODULE_NAME, f"_gui_send error: {e}")

def _gui_progress(kb: int):
    sock_path = os.environ.get("GUI_PROGRESS")
    dlog(MODULE_NAME, f"_gui_progress kb={kb} path={sock_path}")
    if not sock_path:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock_path)
            s.sendall(f"{kb}\n".encode())
    except Exception as e:
        dlog(MODULE_NAME, f"_gui_progress error: {e}")

def toast(title: str, msg: str) -> None:
    dlog(MODULE_NAME, f"toast title={title!r} msg={msg!r}")
    notification.notify(title=title, message=msg, timeout=5)

# ───────────────────────────────────────────────────────────────────────────────
# Dynamische Pause (nicht blockierend, robust)
# ───────────────────────────────────────────────────────────────────────────────
def _parse_pause_seconds(raw: str) -> int:
    """
    Akzeptiert: "8", "8.0", "8s", "8000ms"
    Gibt Sekunden (int, >=0) zurück.
    """
    s = (raw or "").strip().lower()
    if not s:
        raise ValueError("empty pause")
    # ms?
    if s.endswith("ms"):
        val = float(s[:-2].strip())
        return max(0, int(round(val / 1000.0)))
    # s?
    if s.endswith("s"):
        s = s[:-1].strip()
    # n oder n.n
    val = float(s)
    return max(0, int(round(val)))


def get_dynamic_pause_seconds(current_pause_s: int) -> int:
    """
    Nicht-blockierend den GUI-Wert holen.
    Strategie:
      1) Prüfe PAUSE_SOCKET; wenn fehlt -> log & behalte current
      2) Verbinde mit Timeout 100ms
      3) Erst versuchen zu lesen (recv)
      4) Wenn nix kam, 'REQ\\n' senden und nochmal lesen
      5) Wert parsen (Sekunden), ansonsten current behalten
    """
    sock_path = os.environ.get("PAUSE_SOCKET")
    if not sock_path:
        logging.info("PAUSE: PAUSE_SOCKET nicht gesetzt – behalte %ss", current_pause_s)
        return current_pause_s
    if not os.path.exists(sock_path):
        logging.info("PAUSE: Socket existiert nicht (%s) – behalte %ss", sock_path, current_pause_s)
        return current_pause_s

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)  # nicht blockieren
            s.connect(sock_path)

            # 1) Sofort versuchen, was zu lesen
            try:
                data = s.recv(64).decode().strip()
            except socket.timeout:
                data = ""

            if not data:
                # 2) Manche GUIs antworten erst auf Anfrage
                try:
                    s.sendall(b"REQ\n")
                except Exception as e:
                    dlog(__name__, f"PAUSE send REQ error: {e}")
                try:
                    data = s.recv(64).decode().strip()
                except socket.timeout:
                    data = ""

            if data:
                dlog(__name__, f"PAUSE raw recv={data!r}")
                try:
                    val = _parse_pause_seconds(data)
                    logging.info("Pausenzeit (GUI): %s s", val)
                    return val
                except Exception as e:
                    logging.warning("PAUSE: Ungültiger Wert %r (%s) – behalte %ss", data, e, current_pause_s)
            else:
                dlog(__name__, "PAUSE: keine Daten vom Socket – behalte current")

    except Exception as e:
        logging.info("PAUSE: Socket-Fehler (%s) – behalte %ss", e, current_pause_s)

    return current_pause_s

def reactive_sleep(pause_s: int) -> int:
    """
    Schläft bis zu pause_s Sekunden, zeigt in der GUI 'Idle (<sek>)' als Countdown
    und bricht SOFORT ab, wenn die GUI eine neue Pausenzeit sendet.
    Gibt die (ggf. neue) Pausenzeit zurück.
    """
    end = time.time() + max(0, pause_s)
    last_shown = None
    check_step = 0.2  # alle 200 ms GUI abfragen / Countdown updaten

    while True:
        now = time.time()
        remaining = max(0, int(round(end - now)))  # in Sekunden, integer

        # Nur bei Änderung schicken, um Spam zu vermeiden
        if remaining != last_shown:
            _gui_send("STATUS", f"Idle ({remaining})")
            last_shown = remaining

        # Während des Wartens neuen GUI-Wert ziehen
        new_pause = get_dynamic_pause_seconds(pause_s)
        if new_pause != pause_s:
            logging.info(f"Pause unterbrochen: {pause_s}s -> {new_pause}s (GUI)")
            # Direkt mit neuer Pause weiter – Anzeige setzt nächste Runde fort
            return new_pause

        if remaining <= 0:
            # Countdown beendet – Idle ohne Klammern für 'fertig'
            _gui_send("STATUS", "Idle")
            return pause_s

        # Kleinen Happen schlafen
        time.sleep(min(check_step, max(0.0, end - now)))

# ───────────────────────────────────────────────────────────────────────────────F
# Module laden
# ───────────────────────────────────────────────────────────────────────────────

def load_modules() -> dict:
    dlog(MODULE_NAME, f"load_modules from {MODULES_PATH}")
    try:
        raw = MODULES_PATH.read_text(encoding="utf-8")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        patterns = {m: re.compile(rf"{re.escape(m)}\s+([^\s]+)", re.I) for m in lines}
        logging.info(f"{len(patterns)} Modul(e) geladen aus modules.txt")
        dlog(MODULE_NAME, f"modules={lines}")
        return patterns
    except FileNotFoundError:
        logging.error("modules.txt nicht gefunden.")
        return {}
    except Exception as e:
        logging.error(f"Fehler beim Lesen modules.txt: {e}")
        return {}

# ───────────────────────────────────────────────────────────────────────────────
# Login
# ───────────────────────────────────────────────────────────────────────────────

def login(sess: requests.Session, username: str, password: str, retries: int = 3, limit_s: int = 20) -> None:
    _gui_send("STATUS", "Logging in…")
    for attempt in range(1, retries + 1):
        try:
            logging.info(f"Logon … (Versuch {attempt})")
            t0 = time.time()
            dlog(MODULE_NAME, f"POST {LOGIN_URL} data.user={_short_repr(username)} data.pass=*** timeout={limit_s}")

            sess.post(LOGIN_URL, data={
                "user": username, "pass": password,
                "logintype": "login", "pid": PID, "referer": OVERVIEW_URL
            }, headers=HEAD, verify=False, timeout=limit_s)

            dlog(MODULE_NAME, f"GET {OVERVIEW_URL} verify=False timeout={limit_s}")
            resp = sess.get(OVERVIEW_URL, headers=HEAD, verify=False, timeout=limit_s)
            dt = time.time() - t0
            dlog(MODULE_NAME, f"login roundtrip {dt:.3f}s status={getattr(resp, 'status_code', '?')}")

            if dt > limit_s:
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
        except RuntimeError as err:
            logging.error(f"Login fehlgeschlagen: {err}")
            raise

    _gui_send("LOGIN", "FAIL")
    raise RuntimeError("Login failed after retries")

# ───────────────────────────────────────────────────────────────────────────────
# Counter
# ───────────────────────────────────────────────────────────────────────────────

def load_counter() -> int:
    try:
        val = int(COUNTER_FILE.read_text().strip())
        dlog(MODULE_NAME, f"load_counter -> {val}")
        return val
    except (FileNotFoundError, ValueError):
        dlog(MODULE_NAME, "load_counter -> 0 (new)")
        return 0

def save_counter(value: int) -> None:
    dlog(MODULE_NAME, f"save_counter {value}")
    COUNTER_FILE.write_text(f"{value}\n")

# ───────────────────────────────────────────────────────────────────────────────
# Download/Parsing
# ───────────────────────────────────────────────────────────────────────────────

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
            dlog(MODULE_NAME, f"GET {TRANSCRIPT_URL} stream=True")
            with sess.get(TRANSCRIPT_URL, headers=HEAD, stream=True, timeout=30, verify=False) as r:
                r.raise_for_status()

                global _last_printed_kb
                _last_printed_kb = 0

                buf = io.BytesIO()
                size = 0

                for chunk in r.iter_content(1024):
                    buf.write(chunk)
                    size += len(chunk)
                    _print_progress(size)
                    _gui_progress(size // 1024)

                buf.seek(0)
                sys.stdout.write("\n")
                logging.info(f"PDF erfolgreich geladen ({size/1024:.1f} kB) ✓")
                _gui_progress(0)
                dlog(MODULE_NAME, f"PDF bytes={size}")
                return buf

        except (ConnectionError, HTTPError) as err:
            logging.warning(f"Download-Fehler: {err} – nächster Versuch …")
            _gui_send("STATUS", "Waiting for Server Response")
            time.sleep(2 ** attempt)

    raise RuntimeError("PDF download failed")

def pdf_text(buf: io.BytesIO) -> str:
    dlog(MODULE_NAME, "pdf_text: extracting")
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

# ───────────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────────

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

    # Lokale Pause-Variable
    # vor der while-Schleife
    pause_s = DEFAULT_PAUSE
    # gleich beim Start versuchen, den GUI-Wert zu holen
    pause_s = get_dynamic_pause_seconds(pause_s)
    logging.info("Start-Pause (Sekunden): %s", pause_s)

    while True:
        # hol ggf. neuen GUI-Wert; behalte alten, wenn kein Input
        new_pause_s = get_dynamic_pause_seconds(pause_s)
        if new_pause_s != pause_s:
            logging.info(f"Pausenzeit geändert: {pause_s}s -> {new_pause_s}s")
            pause_s = new_pause_s

        attempts += 1
        save_counter(attempts)

        if attempts % reload_interval == 1:
            patterns = load_modules()
            if not patterns:
                logging.warning("Keine Module geladen – überspringe Durchlauf.")
                _gui_send("STATUS", "Keine Module")
                # reaktiv schlafen (unterbricht sofort, wenn GUI ändert)
                pause_s = reactive_sleep(pause_s)
                continue

        if error_count > 0:
            logging.info("Versuche erneuten Login wegen vorherigem Fehler …")
            _gui_send("STATUS", "Reauthenticating…")
            try:
                login(session, username, password)
                error_count = 0
            except RuntimeError as err:
                logging.error(f"Login erneut fehlgeschlagen: {err}")
                pause_s = reactive_sleep(pause_s)
                continue

        logging.info(f"Check #{attempts}")

        try:
            check_modules(session, patterns)
            error_count = 0
        except Exception as err:
            logging.warning(f"Fehler bei der Analyse: {err}")
            _gui_send("STATUS", "Fehler bei Analyse")
            error_count += 1

        pause_s = get_dynamic_pause_seconds(pause_s)
        dlog(__name__, f"reactive_sleep({pause_s}s)")
        # ← hier die neue reaktive Pause
        pause_s = reactive_sleep(pause_s)

if __name__ == "__main__":
    main()
