import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk, messagebox
import subprocess
import threading
import time
import pathlib
import datetime
import os
import socket
import tempfile

SOURCE = pathlib.Path(__file__).resolve().parent
MAIN = SOURCE / "nakbot" / "__main__.py"
MODULES = SOURCE / "modules.txt"
BUILD = SOURCE / "nakbot.pyz"
REQS = SOURCE / "requirements.txt"
GUI = SOURCE / "gui_runner.py"

class BotRunnerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NAK Notenbot")
        self.root.resizable(False, False)

        self.pause_seconds = tk.IntVar(value=2)
        self.last_pause_update = time.time()

        self.text = ScrolledText(
            root, state="disabled", width=100, height=30,
            font=("Courier", 9), spacing1=0, spacing2=0, spacing3=0
        )
        self.text.pack(padx=10, pady=(10, 0))

        self.progress = ttk.Progressbar(root, orient="horizontal", length=600, mode="determinate", maximum=69)
        self.progress.pack(pady=(4, 4))

        self.status_frame = tk.Frame(root)
        self.status_frame.pack(pady=(0, 4))

        self.login_status_label = tk.Label(self.status_frame, text="Login: unbekannt", fg="gray")
        self.activity_label = tk.Label(self.status_frame, text="Status: bereit", fg="gray")

        self.login_status_label.grid(row=0, column=0, padx=20)
        self.activity_label.grid(row=0, column=1, padx=20)

        self.pause_control_frame = tk.Frame(root)
        self.pause_control_frame.pack(pady=(0, 10))
        tk.Label(self.pause_control_frame, text="Pausezeit (Sekunden):").pack(side="left", padx=(0, 5))
        self.pause_spinbox = tk.Spinbox(
            self.pause_control_frame, from_=1, to=600,
            textvariable=self.pause_seconds, width=5,
            command=self.update_pause_live
        )
        self.pause_spinbox.pack(side="left")

        self.button_frame = tk.Frame(root)
        self.button_frame.pack(pady=2)

        self.start_btn = tk.Button(self.button_frame, text="▶ Start", command=self.start_bot)
        self.stop_btn = tk.Button(self.button_frame, text="■ Stop", command=self.stop_bot, state="disabled")
        self.restart_btn = tk.Button(self.button_frame, text="⟳ Neustart", command=self.restart_bot, state="disabled")

        self.start_btn.grid(row=0, column=0, padx=5)
        self.stop_btn.grid(row=0, column=1, padx=5)
        self.restart_btn.grid(row=0, column=2, padx=5)

        self.process = None
        self.last_mtime_main = self.get_mtime(MAIN)
        self.last_mtime_modules = self.get_mtime(MODULES)
        self.last_mtime_gui = self.get_mtime(GUI)

        self.progress_path = tempfile.mktemp(prefix="nakbot_gui_", suffix=".sock")
        self.status_path = tempfile.mktemp(prefix="nakbot_status_", suffix=".sock")
        self.pause_path = tempfile.mktemp(prefix="nakbot_pause_", suffix=".sock")

        self.listen_progress_socket()
        self.listen_status_socket()
        self.send_pause_loop()

        if not BUILD.exists():
            self.build()

        self.setup_tags()
        self.setup_module_editor()
        self.auto_check_loop()

    def update_pause_live(self):
        now = time.time()
        if now - self.last_pause_update < 2:
            return
        self.last_pause_update = now
        try:
            pause_val = int(self.pause_spinbox.get())
            if hasattr(self, 'pause_socket'):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(self.pause_path)
                    s.sendall(f"{pause_val}\n".encode())
        except Exception:
            pass

    def send_pause_loop(self):
        def listen():
            try:
                if os.path.exists(self.pause_path):
                    os.remove(self.pause_path)
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(self.pause_path)
                s.listen(1)
                self.pause_socket = s
            except Exception as e:
                self.log(f"[PauseSocket-Fehler] {e}", "error")

        threading.Thread(target=listen, daemon=True).start()

    def log(self, msg, tag="info"):
        timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        entry = f"{timestamp} {msg}\n"
        self.text.config(state="normal")
        self.text.insert(tk.END, entry, tag)
        self.text.yview(tk.END)
        self.text.config(state="disabled")

    def setup_tags(self):
        self.text.tag_config("stdout", foreground="white")
        self.text.tag_config("error", foreground="red")
        self.text.tag_config("success", foreground="green")
        self.text.tag_config("info", foreground="cyan")

    def listen_progress_socket(self):
        def listen():
            try:
                if os.path.exists(self.progress_path):
                    os.remove(self.progress_path)
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(self.progress_path)
                s.listen(1)
                while True:
                    conn, _ = s.accept()
                    data = conn.recv(32)
                    try:
                        val = int(data.decode().strip())
                        self.root.after(0, self.progress.configure, {"value": val})
                    except:
                        self.root.after(0, self.progress.configure, {"value": 0})
                    conn.close()
            except Exception as e:
                self.log(f"[Fortschrittsfehler] {e}", "error")

        threading.Thread(target=listen, daemon=True).start()

    def listen_status_socket(self):
        def listen():
            try:
                if os.path.exists(self.status_path):
                    os.remove(self.status_path)
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.bind(self.status_path)
                s.listen(1)
                while True:
                    conn, _ = s.accept()
                    data = conn.recv(128).decode(errors="ignore").strip()
                    if data.startswith("LOGIN:"):
                        value = data.split("LOGIN:", 1)[1].strip()
                        color = "green" if value == "OK" else "red"
                        self.root.after(0, self.login_status_label.config, {"text": f"Login: {value}", "fg": color})
                    elif data.startswith("STATUS:"):
                        value = data.split("STATUS:", 1)[1].strip()
                        self.root.after(0, self.activity_label.config, {"text": f"Status: {value}", "fg": "blue"})
                    conn.close()
            except Exception as e:
                self.log(f"[StatusSocket-Fehler] {e}", "error")

        threading.Thread(target=listen, daemon=True).start()

    def build(self):
        self.log("🔨 Baue neue .pyz …", "info")
        try:
            subprocess.run(
                ["shiv", "-c", "nakbot", "-o", str(BUILD), ".", "-r", str(REQS)],
                cwd=str(SOURCE), check=True
            )
            self.log("✅ Build erfolgreich.", "success")
        except subprocess.CalledProcessError as e:
            self.log(f"❌ Build fehlgeschlagen: {e}", "error")

    def start_bot(self):
        if self.process:
            self.log("⚠️ Bot läuft bereits.", "info")
            return

        self.log("▶️ Starte Bot …", "info")

        env = os.environ.copy()
        env["GUI_PROGRESS"] = self.progress_path
        env["GUI_STATUS"] = self.status_path
        env["PAUSE_SOCKET"] = self.pause_path

        self.process = subprocess.Popen(
            ["python3", str(BUILD)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            env=env
        )

        threading.Thread(target=self.print_output, args=(self.process.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=self.print_output, args=(self.process.stderr, "error"), daemon=True).start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.restart_btn.config(state="normal")

    def stop_bot(self):
        if self.process:
            self.log("🛑 Stoppe Bot …", "info")
            self.process.terminate()
            self.process.wait()
            self.process = None
            self.progress["value"] = 0

        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.restart_btn.config(state="disabled")

    def restart_bot(self):
        self.stop_bot()
        self.build()
        self.start_bot()

    def get_mtime(self, path):
        try:
            return path.stat().st_mtime
        except FileNotFoundError:
            return 0

    def print_output(self, stream, tag):
        for line in iter(stream.readline, b''):
            text = line.decode(errors="replace")
            self.root.after(0, self.log_raw, text, tag)
        stream.close()

    def log_raw(self, text, tag="stdout"):
        self.text.config(state="normal")
        self.text.insert(tk.END, text, tag)
        self.text.yview(tk.END)
        self.text.config(state="disabled")

    def setup_module_editor(self):
        self.module_frame = tk.Frame(self.root)
        self.module_frame.pack(pady=(0, 10))

        tk.Label(self.module_frame, text="Module (eines pro Zeile):").pack(anchor="w")
        self.module_text = ScrolledText(self.module_frame, width=100, height=6, font=("Courier", 9))
        self.module_text.pack()

        if MODULES.exists():
            self.module_text.insert("1.0", MODULES.read_text(encoding="utf-8"))

        tk.Button(self.module_frame, text="💾 Speichern und starten", command=self.save_and_start).pack(pady=4)

    def save_and_start(self):
        text = self.module_text.get("1.0", tk.END).strip()
        MODULES.write_text(text, encoding="utf-8")
        self.start_bot()

    def auto_check_loop(self):
        def loop():
            while True:
                time.sleep(3)

                if self.process and self.process.poll() is not None:
                    self.log(f"💥 Bot abgestürzt (Code {self.process.returncode}) – Neustart …", "error")
                    self.process = None
                    self.start_bot()

                if any([
                    self.get_mtime(MAIN) != self.last_mtime_main,
                    self.get_mtime(MODULES) != self.last_mtime_modules,
                    self.get_mtime(GUI) != self.last_mtime_gui
                ]):
                    self.log("✏️ Änderung erkannt – baue & starte neu …", "info")
                    self.last_mtime_main = self.get_mtime(MAIN)
                    self.last_mtime_modules = self.get_mtime(MODULES)
                    self.last_mtime_gui = self.get_mtime(GUI)
                    self.restart_bot()

        threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = BotRunnerApp(root)
    root.mainloop()
