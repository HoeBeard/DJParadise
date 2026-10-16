#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DJ Paradise - Startup & Dependency Manager
Copyright (c) 2026 HB Software. All rights reserved.
https://hbcs.info

Runs every time DJ Paradise starts. It checks that everything the program
needs is installed, installs or repairs anything that is missing, keeps the
download engines current, and then opens DJ Paradise.
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

APP_NAME = "DJ Paradise"
APP_VERSION = "1.2.0"
COMPANY = "HB Software"
WEBSITE = "https://hbcs.info"

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, ".runtime")
VENV_DIR = os.path.join(RUNTIME, "venv")
STATE_FILE = os.path.join(RUNTIME, "state.json")
LOG_FILE = os.path.join(RUNTIME, "setup.log")
ASSETS = os.path.join(ROOT, "assets")
LOGO_PNG = os.path.join(ASSETS, "hb_software_logo.png")
LOGO_ICO = os.path.join(ASSETS, "hb_software_logo.ico")
LOGO_URL = "https://hbcs.info/assets/software-mark.webp"
APP_ENTRY = os.path.join(ROOT, "app", "main.py")

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0
UPDATE_EVERY_SECONDS = 24 * 60 * 60
MIN_PY = (3, 10)
MAX_PY = (3, 14)

# Everything DJ Paradise needs. "required" items must install for the program
# to open; optional items only disable the feature that uses them.
DEPENDENCIES = [
    {"key": "ui", "label": "Interface", "spec": "customtkinter>=5.2.2",
     "dist": "customtkinter", "required": True},
    {"key": "img", "label": "Graphics engine", "spec": "pillow>=10.0",
     "dist": "pillow", "required": True},
    {"key": "ytdlp", "label": "YouTube & SoundCloud engine", "spec": "yt-dlp[default]",
     "dist": "yt-dlp", "required": True, "auto_update": True},
    {"key": "spotdl", "label": "Spotify engine", "spec": "spotdl>=4.2",
     "dist": "spotdl", "required": False, "auto_update": True, "slow": True},
    {"key": "deno", "label": "YouTube script runtime", "spec": "deno",
     "dist": "deno", "required": False},
    {"key": "ffmpeg", "label": "Audio converter", "spec": "static-ffmpeg",
     "dist": "static-ffmpeg", "required": True},
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def python_ok():
    return MIN_PY <= sys.version_info[:2] <= MAX_PY


def venv_python(windowed=False):
    if IS_WIN:
        exe = "pythonw.exe" if windowed else "python.exe"
        return os.path.join(VENV_DIR, "Scripts", exe)
    return os.path.join(VENV_DIR, "bin", "python")


def venv_bin():
    return os.path.join(VENV_DIR, "Scripts" if IS_WIN else "bin")


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(RUNTIME, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def normalize(name):
    return name.lower().replace("_", "-").replace(".", "-")


class SetupError(Exception):
    pass


# --------------------------------------------------------------------------
# Setup work (runs on a background thread)
# --------------------------------------------------------------------------

class Setup(object):
    def __init__(self, events):
        self.events = events  # queue of (kind, *args)
        os.makedirs(RUNTIME, exist_ok=True)
        self._log_fh = open(LOG_FILE, "a", encoding="utf-8")
        self.log("=" * 60)
        self.log("%s %s startup  %s" % (APP_NAME, APP_VERSION, time.strftime("%Y-%m-%d %H:%M:%S")))
        self.log("Python %s at %s" % (sys.version.split()[0], sys.executable))

    # -- event plumbing
    def log(self, text):
        try:
            self._log_fh.write(text.rstrip() + "\n")
            self._log_fh.flush()
        except Exception:
            pass

    def status(self, text, fraction=None):
        self.log("> " + text)
        self.events.put(("status", text, fraction))

    def dep(self, key, state, detail=""):
        self.events.put(("dep", key, state, detail))

    # -- process runner
    def run(self, cmd, timeout=None, env=None):
        self.log("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW, timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            self.log("(timed out)")
            return 1, ""
        except OSError as exc:
            self.log("(could not start: %s)" % exc)
            return 1, ""
        self.log(proc.stdout or "")
        return proc.returncode, proc.stdout or ""

    def pip(self, *args, **kw):
        """Run pip, streaming its progress to the log and the startup window.
        Stops pip if it goes quiet for too long instead of hanging forever."""
        cmd = [venv_python(), "-m", "pip", "--disable-pip-version-check", "--no-input",
               "--progress-bar", "off", "--default-timeout", "60"] + list(args)
        key = kw.get("key")
        idle_limit = kw.get("idle", 300)
        total_limit = kw.get("timeout", 1800)
        self.log("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                universal_newlines=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=NO_WINDOW)
        except OSError as exc:
            self.log("(could not start: %s)" % exc)
            return 1, ""

        started = time.time()
        last = [time.time()]
        stopped = [False]

        def watchdog():
            while proc.poll() is None:
                now = time.time()
                if now - last[0] > idle_limit or now - started > total_limit:
                    stopped[0] = True
                    self.log("(no progress, stopping installer)")
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return
                time.sleep(2)

        threading.Thread(target=watchdog, daemon=True).start()
        out = []
        for raw in proc.stdout:
            last[0] = time.time()
            line = raw.rstrip()
            if not line:
                continue
            out.append(line)
            self.log(line)
            detail = self._pip_detail(line)
            if detail and key:
                self.dep(key, "working", detail)
        proc.wait()
        code = 1 if stopped[0] else proc.returncode
        return code, "\n".join(out)

    @staticmethod
    def _pip_detail(line):
        s = line.strip()
        for prefix, label in (("Collecting ", "Getting "), ("Downloading ", "Downloading "),
                              ("Building wheel for ", "Building "),
                              ("Installing collected packages", "Installing"),
                              ("Successfully installed", "Finishing")):
            if s.startswith(prefix):
                rest = s[len(prefix):].split()[0] if s[len(prefix):].split() else ""
                name = rest.split("/")[-1].split("-")[0].split("==")[0].split(">")[0].split("<")[0].split("[")[0]
                text = (label + name).strip() if label.endswith(" ") else label
                return text[:34]
        return None

    # -- steps
    def ensure_runtime(self, state):
        py_tag = "%d.%d" % sys.version_info[:2]
        healthy = False
        if os.path.exists(venv_python()):
            code, _ = self.run([venv_python(), "-c", "import sys; print(sys.version)"], timeout=60)
            healthy = code == 0 and state.get("python") == py_tag
        if healthy:
            return False
        if os.path.isdir(VENV_DIR):
            self.log("Rebuilding private runtime")
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        import venv
        try:
            venv.EnvBuilder(with_pip=True, clear=True).create(VENV_DIR)
        except Exception as exc:
            self.log(traceback.format_exc())
            hint = ""
            if sys.platform.startswith("linux"):
                hint = " Install your system's python3-venv package and start again."
            raise SetupError("Could not create the private runtime (%s).%s" % (exc, hint))
        state["python"] = py_tag
        state.pop("last_update", None)
        return True

    def installed_packages(self):
        code, out = self.run([
            venv_python(), "-c",
            "import json, importlib.metadata as m; "
            "print('DJP' + json.dumps({d.metadata['Name']: d.version for d in m.distributions() if d.metadata['Name']}))"
        ], timeout=120)
        for line in out.splitlines():
            if line.startswith("DJP"):
                try:
                    return {normalize(k): v for k, v in json.loads(line[3:]).items()}
                except Exception:
                    pass
        return {}

    def resolve_ffmpeg(self):
        code, out = self.run([
            venv_python(), "-c",
            "from static_ffmpeg import run; f, p = run.get_or_fetch_platform_executables_else_raise(); "
            "print('DJPFF' + f); print('DJPFP' + p)"
        ], timeout=900)
        ffmpeg = ffprobe = None
        for line in out.splitlines():
            if line.startswith("DJPFF"):
                ffmpeg = line[5:].strip()
            elif line.startswith("DJPFP"):
                ffprobe = line[5:].strip()
        if ffmpeg and os.path.exists(ffmpeg):
            return ffmpeg, ffprobe
        system = shutil.which("ffmpeg")
        if system:
            return system, shutil.which("ffprobe")
        return None, None

    def fetch_logo(self):
        if os.path.exists(LOGO_PNG):
            return True
        os.makedirs(ASSETS, exist_ok=True)
        raw = os.path.join(RUNTIME, "logo_download.webp")
        try:
            req = urllib.request.Request(LOGO_URL, headers={"User-Agent": "%s/%s" % (APP_NAME.replace(" ", ""), APP_VERSION)})
            with urllib.request.urlopen(req, timeout=20) as resp, open(raw, "wb") as fh:
                fh.write(resp.read())
        except Exception as exc:
            self.log("Logo download failed: %s" % exc)
            return False
        script = (
            "import sys\n"
            "from PIL import Image\n"
            "im = Image.open(sys.argv[1]).convert('RGBA')\n"
            "box = im.getbbox()\n"
            "im = im.crop(box) if box else im\n"
            "im.save(sys.argv[2])\n"
            "side = max(im.size)\n"
            "sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))\n"
            "sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))\n"
            "sq.save(sys.argv[3], sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])\n"
        )
        code, _ = self.run([venv_python(), "-c", script, raw, LOGO_PNG, LOGO_ICO], timeout=120)
        try:
            os.remove(raw)
        except OSError:
            pass
        return code == 0 and os.path.exists(LOGO_PNG)

    def go(self):
        state = load_state()
        self.status("Checking system", 0.02)
        if not python_ok():
            raise SetupError("DJ Paradise needs Python %d.%d to %d.%d. This computer is running %s."
                             % (MIN_PY + MAX_PY + (sys.version.split()[0],)))
        if not os.path.exists(APP_ENTRY):
            raise SetupError("Program files are missing. Download DJ Paradise again.")

        self.status("Preparing runtime", 0.06)
        fresh = self.ensure_runtime(state)
        if fresh:
            self.status("Setting up installer", 0.1)
            self.pip("install", "--upgrade", "pip", "setuptools", "wheel", timeout=600, idle=180)

        installed = self.installed_packages()
        n = len(DEPENDENCIES)
        warnings = []
        for i, dep in enumerate(DEPENDENCIES):
            frac = 0.12 + 0.62 * (i / float(n))
            self.dep(dep["key"], "working")
            if normalize(dep["dist"]) in installed:
                self.dep(dep["key"], "ok", installed[normalize(dep["dist"])])
                continue
            note = "  (this one takes a few minutes)" if dep.get("slow") else ""
            self.status("Installing %s%s" % (dep["label"].lower(), note), frac)
            code, _ = self.pip("install", "--upgrade", dep["spec"], key=dep["key"])
            if code != 0:
                # One retry - networks blink.
                self.status("Retrying %s" % dep["label"].lower(), frac)
                code, _ = self.pip("install", "--upgrade", dep["spec"], key=dep["key"])
            if code == 0:
                self.dep(dep["key"], "ok", "installed")
            elif dep["required"]:
                self.dep(dep["key"], "fail", "failed")
                raise SetupError("Could not install the %s. Check your internet connection and try again."
                                 % dep["label"].lower())
            else:
                self.dep(dep["key"], "warn", "unavailable")
                warnings.append(dep["label"])

        # Download engines break when the sites change, so keep them current.
        now = time.time()
        if now - state.get("last_update", 0) > UPDATE_EVERY_SECONDS:
            specs = [d["spec"] for d in DEPENDENCIES if d.get("auto_update")]
            self.status("Checking for engine updates", 0.76)
            code, _ = self.pip("install", "--upgrade", *specs, timeout=900, idle=180)
            if code == 0:
                state["last_update"] = now

        self.status("Checking audio converter", 0.84)
        self.dep("ffmpeg", "working")
        ffmpeg, ffprobe = self.resolve_ffmpeg()
        if not ffmpeg:
            self.dep("ffmpeg", "fail", "failed")
            raise SetupError("Could not set up the audio converter. Check your internet connection and try again.")
        self.dep("ffmpeg", "ok", "ready")
        state["ffmpeg"] = ffmpeg
        state["ffprobe"] = ffprobe or ""

        self.status("Loading branding", 0.92)
        self.fetch_logo()

        state["last_check"] = now
        state["version"] = APP_VERSION
        save_state(state)

        self.status("Starting %s" % APP_NAME, 1.0)
        self.launch(ffmpeg, ffprobe)
        return warnings

    def launch(self, ffmpeg, ffprobe):
        env = os.environ.copy()
        paths = [venv_bin(), os.path.dirname(ffmpeg)]
        env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
        env["DJP_ROOT"] = ROOT
        env["DJP_FFMPEG"] = ffmpeg
        env["DJP_FFPROBE"] = ffprobe or ""
        env["PYTHONIOENCODING"] = "utf-8"
        exe = venv_python(windowed=True)
        if not os.path.exists(exe):
            exe = venv_python()
        kwargs = {"cwd": ROOT, "env": env, "close_fds": True}
        if IS_WIN:
            kwargs["creationflags"] = NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([exe, APP_ENTRY], **kwargs)

    def run_threaded(self):
        try:
            warnings = self.go()
            self.events.put(("done", True, warnings))
        except SetupError as exc:
            self.log("SETUP ERROR: %s" % exc)
            self.events.put(("done", False, str(exc)))
        except Exception as exc:
            self.log(traceback.format_exc())
            self.events.put(("done", False, "Something went wrong during startup (%s)." % exc))


# --------------------------------------------------------------------------
# Startup window
# --------------------------------------------------------------------------

class StartupWindow(object):
    BG = "#05080f"
    PANEL = "#0b111d"
    TEXT = "#eef1f8"
    MUTED = "#8a93a8"
    ACCENT = "#1e90ff"
    COLORS = {"pending": "#3a4157", "working": "#f5a623", "ok": "#2ecc71",
              "warn": "#f5a623", "fail": "#ff4d5e"}

    def __init__(self, tk, ttk):
        self.tk = tk
        self.events = queue.Queue()
        root = self.root = tk.Tk()
        root.title("%s  |  %s" % (APP_NAME, COMPANY))
        root.configure(bg=self.BG)
        root.resizable(False, False)
        w, h = 560, 470
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry("%dx%d+%d+%d" % (w, h, x, y))

        self.logo = None
        if os.path.exists(LOGO_PNG):
            try:
                img = tk.PhotoImage(file=LOGO_PNG)
                root.iconphoto(True, img)
                factor = max(1, img.height() // 64)
                self.logo = img.subsample(factor, factor)
            except Exception:
                self.logo = None
        if IS_WIN and os.path.exists(LOGO_ICO):
            try:
                root.iconbitmap(LOGO_ICO)
            except Exception:
                pass

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("DJP.Horizontal.TProgressbar", troughcolor=self.PANEL,
                        background=self.ACCENT, bordercolor=self.BG,
                        lightcolor=self.ACCENT, darkcolor=self.ACCENT, thickness=6)

        head = tk.Frame(root, bg=self.BG)
        head.pack(fill="x", padx=28, pady=(26, 8))
        if self.logo is not None:
            tk.Label(head, image=self.logo, bg=self.BG).pack(side="left", padx=(0, 14))
        else:
            badge = tk.Label(head, text="HB", bg=self.ACCENT, fg="white",
                             font=("Segoe UI", 18, "bold"), width=3, height=1)
            badge.pack(side="left", padx=(0, 14), ipady=8)
        titles = tk.Frame(head, bg=self.BG)
        titles.pack(side="left", anchor="w")
        tk.Label(titles, text="DJ PARADISE", bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(titles, text="by %s" % COMPANY, bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI", 10)).pack(anchor="w")

        self.status_var = tk.StringVar(value="Starting up")
        tk.Label(root, textvariable=self.status_var, bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 11), anchor="w").pack(fill="x", padx=28, pady=(14, 6))
        self.bar = ttk.Progressbar(root, style="DJP.Horizontal.TProgressbar",
                                   mode="determinate", maximum=1000)
        self.bar.pack(fill="x", padx=28)

        box = tk.Frame(root, bg=self.PANEL)
        box.pack(fill="x", padx=28, pady=(18, 0))
        self.rows = {}
        for dep in DEPENDENCIES:
            row = tk.Frame(box, bg=self.PANEL)
            row.pack(fill="x", padx=14, pady=4)
            dot = tk.Label(row, text="●", bg=self.PANEL, fg=self.COLORS["pending"],
                           font=("Segoe UI", 11))
            dot.pack(side="left")
            tk.Label(row, text=dep["label"], bg=self.PANEL, fg=self.TEXT,
                     font=("Segoe UI", 10)).pack(side="left", padx=(8, 0))
            info = tk.Label(row, text="", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9))
            info.pack(side="right")
            self.rows[dep["key"]] = (dot, info)
        tk.Frame(box, bg=self.PANEL, height=6).pack()

        self.buttons = tk.Frame(root, bg=self.BG)
        self.message = tk.Label(root, text="", bg=self.BG, fg="#ff8a95", wraplength=500,
                                justify="left", font=("Segoe UI", 10))

        tk.Label(root, text="© 2026 %s  ·  hbcs.info  ·  v%s" % (COMPANY, APP_VERSION),
                 bg=self.BG, fg="#4a5269", font=("Segoe UI", 8)).pack(side="bottom", pady=10)

        self.status_text = "Starting up"
        self.status_since = time.time()
        self.running = False
        self.start()
        root.after(80, self.poll)
        root.after(1000, self.tick)

    def tick(self):
        # Show a running clock on long steps so it's clear the program is working.
        if self.running:
            secs = int(time.time() - self.status_since)
            if secs >= 5:
                self.status_var.set("%s   %d:%02d" % (self.status_text, secs // 60, secs % 60))
        self.root.after(1000, self.tick)

    def button(self, parent, text, cmd, primary=False):
        b = self.tk.Button(parent, text=text, command=cmd, relief="flat", bd=0, cursor="hand2",
                           bg=self.ACCENT if primary else self.PANEL, fg="white",
                           activebackground="#1273d6" if primary else "#16213a",
                           activeforeground="white", font=("Segoe UI", 10, "bold"),
                           padx=16, pady=6)
        b.pack(side="left", padx=(0, 8))
        return b

    def start(self):
        self.message.pack_forget()
        self.buttons.pack_forget()
        for child in self.buttons.winfo_children():
            child.destroy()
        for dot, info in self.rows.values():
            dot.configure(fg=self.COLORS["pending"])
            info.configure(text="")
        setup = Setup(self.events)
        self.running = True
        threading.Thread(target=setup.run_threaded, daemon=True).start()

    def poll(self):
        try:
            while True:
                evt = self.events.get_nowait()
                kind = evt[0]
                if kind == "status":
                    self.status_text = evt[1]
                    self.status_since = time.time()
                    self.status_var.set(evt[1])
                    if evt[2] is not None:
                        self.bar["value"] = int(evt[2] * 1000)
                elif kind == "dep":
                    dot, info = self.rows[evt[1]]
                    dot.configure(fg=self.COLORS.get(evt[2], self.MUTED))
                    info.configure(text=evt[3] or ("checking" if evt[2] == "working" else ""))
                elif kind == "done":
                    self.running = False
                    self.finish(evt[1], evt[2])
                    return
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def finish(self, ok, payload):
        self.root.after(80, self.poll)
        if ok:
            self.status_var.set("Starting DJ Paradise")
            self.root.after(1400, self.root.destroy)
            return
        self.status_var.set("Startup stopped")
        self.message.configure(text=payload)
        self.message.pack(fill="x", padx=28, pady=(14, 0))
        self.buttons.pack(fill="x", padx=28, pady=(12, 0))
        self.button(self.buttons, "Try again", self.start, primary=True)
        self.button(self.buttons, "View log", self.open_log)
        self.button(self.buttons, "Close", self.root.destroy)

    def open_log(self):
        open_path(LOG_FILE)

    def mainloop(self):
        self.root.mainloop()


def open_path(path):
    try:
        if IS_WIN:
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


# --------------------------------------------------------------------------
# Console mode (used only if this Python has no window toolkit)
# --------------------------------------------------------------------------

def console_mode():
    print("%s %s  -  %s" % (APP_NAME, APP_VERSION, COMPANY))
    events = queue.Queue()
    setup = Setup(events)
    t = threading.Thread(target=setup.run_threaded, daemon=True)
    t.start()
    while True:
        evt = events.get()
        if evt[0] == "status":
            print("  " + evt[1])
        elif evt[0] == "done":
            if evt[1]:
                print("  Ready.")
                return 0
            print("  " + evt[2])
            print("  Details: " + LOG_FILE)
            return 1


def main():
    args = sys.argv[1:]
    if "--check" in args:
        # Used by the start scripts to pick a suitable Python.
        try:
            import tkinter  # noqa: F401
            import venv  # noqa: F401
            import ensurepip  # noqa: F401
        except Exception:
            sys.exit(2)
        sys.exit(0 if python_ok() else 1)
    if "--where" in args:
        print(sys.executable)
        sys.exit(0)
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        sys.exit(console_mode())
    StartupWindow(tk, ttk).mainloop()


if __name__ == "__main__":
    main()
