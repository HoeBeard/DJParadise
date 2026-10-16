# -*- coding: utf-8 -*-
"""
DJ Paradise
Copyright (c) 2026 HB Software. All rights reserved.
https://hbcs.info
"""

import json
import os
import queue
import subprocess
import sys
import time
import webbrowser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("DJP_ROOT") or os.path.dirname(APP_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import customtkinter as ctk  # noqa: E402
from tkinter import filedialog, messagebox  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from engines import SPOTS, FORMATS, DownloadJob, validate_url  # noqa: E402

APP_NAME = "DJ Paradise"
APP_VERSION = "1.0.0"
COMPANY = "HB Software"
WEBSITE = "https://hbcs.info"
SOFTWARE_PAGE = "https://hbcs.info/software/"

ASSETS = os.path.join(ROOT, "assets")
LOGO_PNG = os.path.join(ASSETS, "hb_software_logo.png")
LOGO_ICO = os.path.join(ASSETS, "hb_software_logo.ico")
SETTINGS_FILE = os.path.join(ROOT, ".runtime", "settings.json")
IS_WIN = os.name == "nt"

# Palette
BG = "#0a0c13"
PANEL = "#10141f"
CARD = "#151a28"
CARD_HI = "#1a2032"
FIELD = "#0d111b"
BORDER = "#232a3f"
TEXT = "#eef1f8"
MUTED = "#8a93a8"
FAINT = "#4a5269"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#3a74e0"
GOOD = "#2ecc71"
BAD = "#ff5d6c"


def font(size, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def default_music_dir():
    home = os.path.expanduser("~")
    music = os.path.join(home, "Music")
    base = music if os.path.isdir(music) else home
    return os.path.join(base, "DJ Paradise")


def load_settings():
    data = {
        "output_dir": default_music_dir(),
        "format": "MP3",
        "organize": True,
        "spotify_client_id": "",
        "spotify_client_secret": "",
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data.update(json.load(fh))
    except Exception:
        pass
    if data.get("format") not in FORMATS:
        data["format"] = "MP3"
    return data


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


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


def fallback_logo(size=128):
    """HB badge used only if the logo file can't be loaded."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=ACCENT)
    try:
        f = ImageFont.truetype("arialbd.ttf" if IS_WIN else "DejaVuSans-Bold.ttf", size // 2)
    except Exception:
        f = ImageFont.load_default()
    d.text((size / 2, size / 2), "HB", font=f, fill="white", anchor="mm")
    return img


def load_logo():
    try:
        img = Image.open(LOGO_PNG).convert("RGBA")
        box = img.getbbox()
        return img.crop(box) if box else img
    except Exception:
        return fallback_logo()


def ensure_ico(logo):
    """Always have an HB Software window icon on Windows."""
    if os.path.exists(LOGO_ICO):
        return LOGO_ICO
    path = os.path.join(ROOT, ".runtime", "app_icon.ico")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        side = max(logo.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2))
        sq.save(path, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
        return path
    except Exception:
        return None


def apply_icon(window, logo):
    if IS_WIN:
        ico = ensure_ico(logo)
        if ico:
            try:
                window.iconbitmap(ico)
            except Exception:
                pass


# --------------------------------------------------------------------------
# One download spot
# --------------------------------------------------------------------------

class SpotCard(ctk.CTkFrame):
    def __init__(self, master, app, spot):
        ctk.CTkFrame.__init__(self, master, fg_color=CARD, corner_radius=16,
                              border_width=1, border_color=BORDER)
        self.app = app
        self.spot = spot
        self.job = None
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(self, height=3, fg_color=spot["color"], corner_radius=2).grid(
            row=0, column=0, sticky="ew", padx=18, pady=(16, 0))

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=1, column=0, sticky="ew", padx=18, pady=(12, 0))
        ctk.CTkLabel(head, text=spot["service"].upper(), text_color=spot["color"],
                     font=font(11, "bold")).pack(anchor="w")
        ctk.CTkLabel(head, text=spot["kind"], text_color=TEXT,
                     font=font(22, "bold")).pack(anchor="w")

        self.entry = ctk.CTkEntry(self, placeholder_text=spot["hint"], height=40,
                                  fg_color=FIELD, border_color=BORDER, border_width=1,
                                  corner_radius=10, text_color=TEXT,
                                  placeholder_text_color=FAINT, font=font(13))
        self.entry.grid(row=2, column=0, sticky="ew", padx=18, pady=(14, 0))
        self.entry.bind("<Return>", lambda e: self.toggle())

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=18, pady=(10, 0))
        row.grid_columnconfigure(1, weight=1)
        self.paste_btn = ctk.CTkButton(row, text="Paste", width=74, height=36, corner_radius=10,
                                       fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT,
                                       font=font(12, "bold"), command=self.paste)
        self.paste_btn.grid(row=0, column=0, padx=(0, 8))
        self.go_btn = ctk.CTkButton(row, text="Download", height=36, corner_radius=10,
                                    fg_color=spot["color"], hover_color=spot["color"],
                                    text_color=spot["on_color"], font=font(13, "bold"),
                                    command=self.toggle)
        self.go_btn.grid(row=0, column=1, sticky="ew")

        self.bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, fg_color=FIELD,
                                      progress_color=spot["color"])
        self.bar.grid(row=4, column=0, sticky="ew", padx=18, pady=(14, 0))
        self.bar.set(0)
        self._indeterminate = False

        self.status = ctk.CTkLabel(self, text="Ready", text_color=MUTED, font=font(12),
                                   anchor="w", justify="left", wraplength=280)
        self.status.grid(row=5, column=0, sticky="ew", padx=18, pady=(8, 16))
        self.bind("<Configure>", self._rewrap)

    def _rewrap(self, event):
        self.status.configure(wraplength=max(event.width - 40, 120))

    # -- actions
    def paste(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            text = ""
        if text:
            self.entry.delete(0, "end")
            self.entry.insert(0, text)

    @property
    def busy(self):
        return self.job is not None

    def has_link(self):
        return bool(self.entry.get().strip())

    def toggle(self):
        if self.busy:
            self.job.cancel()
            self.set_status("Stopping", MUTED)
            return
        self.start()

    def start(self):
        url = self.entry.get().strip()
        ok, msg = validate_url(self.spot["id"], url)
        if not ok:
            self.set_status(msg, BAD)
            return False
        out_dir = self.app.output_for(self.spot)
        fmt = self.app.settings["format"]
        sid = self.spot["id"]
        self.job = DownloadJob(self.spot, url, out_dir, fmt, dict(self.app.settings),
                               lambda *evt: self.app.events.put((sid,) + evt))
        self.go_btn.configure(text="Stop", fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT)
        self.entry.configure(state="disabled")
        self.paste_btn.configure(state="disabled")
        self.set_status("Starting", MUTED)
        self.app.log("info", "%s %s  ·  %s" % (self.spot["service"], self.spot["kind"].lower(), url))
        self.job.start()
        return True

    # -- events from the job
    def handle(self, kind, *args):
        if kind == "status":
            self.set_status(args[0], TEXT)
        elif kind == "progress":
            self.set_progress(args[0])
        elif kind == "log":
            self.app.log(args[0], args[1], self.spot)
        elif kind == "done":
            self.finish(args[0], args[1])

    def set_status(self, text, color):
        self.status.configure(text=text, text_color=color)

    def set_progress(self, value):
        if value is None:
            if not self._indeterminate:
                self.bar.configure(mode="indeterminate")
                self.bar.start()
                self._indeterminate = True
            return
        if self._indeterminate:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self._indeterminate = False
        self.bar.set(max(0.0, min(1.0, value)))

    def finish(self, ok, text):
        self.job = None
        if self._indeterminate:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self._indeterminate = False
        self.bar.set(1.0 if ok else 0.0)
        self.go_btn.configure(text="Download", fg_color=self.spot["color"],
                              hover_color=self.spot["color"], text_color=self.spot["on_color"])
        self.entry.configure(state="normal")
        self.paste_btn.configure(state="normal")
        self.set_status(text, GOOD if ok else (MUTED if text == "Stopped" else BAD))
        self.app.log("ok" if ok else "error", "%s %s  ·  %s"
                     % (self.spot["service"], self.spot["kind"].lower(), text))
        if ok:
            self.entry.delete(0, "end")
        self.app.refresh_activity()


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        ctk.CTkToplevel.__init__(self, app)
        self.app = app
        self.title("Settings  |  %s" % APP_NAME)
        self.configure(fg_color=BG)
        self.geometry("520x470")
        self.resizable(False, False)
        self.transient(app)
        apply_icon(self, app.logo_img)

        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=26, pady=22)

        ctk.CTkLabel(wrap, text="Settings", font=font(22, "bold"), text_color=TEXT).pack(anchor="w")

        ctk.CTkLabel(wrap, text="LIBRARY", font=font(11, "bold"), text_color=MUTED).pack(anchor="w", pady=(18, 4))
        self.organize = ctk.CTkSwitch(wrap, text="Sort downloads into Spotify, SoundCloud and YouTube folders",
                                      font=font(12), text_color=TEXT, progress_color=ACCENT)
        if app.settings.get("organize", True):
            self.organize.select()
        self.organize.pack(anchor="w")

        ctk.CTkLabel(wrap, text="SPOTIFY APP KEYS  (OPTIONAL)", font=font(11, "bold"),
                     text_color=MUTED).pack(anchor="w", pady=(22, 2))
        ctk.CTkLabel(wrap, text="If Spotify downloads stop with a request limit message, create a free app at "
                                "developer.spotify.com and paste its keys here.",
                     font=font(12), text_color=MUTED, wraplength=460, justify="left").pack(anchor="w")
        self.cid = ctk.CTkEntry(wrap, placeholder_text="Client ID", height=38, fg_color=FIELD,
                                border_color=BORDER, corner_radius=10)
        self.cid.pack(fill="x", pady=(10, 0))
        self.secret = ctk.CTkEntry(wrap, placeholder_text="Client secret", show="•", height=38,
                                   fg_color=FIELD, border_color=BORDER, corner_radius=10)
        self.secret.pack(fill="x", pady=(8, 0))
        if app.settings.get("spotify_client_id"):
            self.cid.insert(0, app.settings["spotify_client_id"])
        if app.settings.get("spotify_client_secret"):
            self.secret.insert(0, app.settings["spotify_client_secret"])
        ctk.CTkButton(wrap, text="Open Spotify developer site", width=10, height=26,
                      fg_color="transparent", hover_color=CARD_HI, text_color=ACCENT,
                      font=font(12), command=lambda: webbrowser.open("https://developer.spotify.com/dashboard")
                      ).pack(anchor="w", pady=(6, 0))

        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(side="bottom", fill="x")
        ctk.CTkButton(btns, text="Save", width=110, height=38, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, font=font(13, "bold"), command=self.save).pack(side="right")
        ctk.CTkButton(btns, text="Cancel", width=90, height=38, corner_radius=10, fg_color=CARD_HI,
                      hover_color=BORDER, text_color=TEXT, font=font(13), command=self.destroy
                      ).pack(side="right", padx=(0, 8))
        self.after(50, self.grab_set)

    def save(self):
        s = self.app.settings
        s["organize"] = bool(self.organize.get())
        s["spotify_client_id"] = self.cid.get().strip()
        s["spotify_client_secret"] = self.secret.get().strip()
        save_settings(s)
        self.destroy()


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class DJParadise(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.CTk.__init__(self, fg_color=BG)
        self.settings = load_settings()
        self.events = queue.Queue()
        self.cards = {}

        self.title("%s  |  %s" % (APP_NAME, COMPANY))
        self.geometry("1220x840")
        self.minsize(1000, 720)
        self._set_icon()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_spots()
        self._build_activity()
        self._build_footer()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.poll)
        self.log("info", "%s %s ready  ·  saving to %s" % (APP_NAME, APP_VERSION, self.settings["output_dir"]))

    # -- layout
    def _set_icon(self):
        self.logo_img = load_logo()
        try:
            from PIL import ImageTk
            icon = self.logo_img.copy()
            icon.thumbnail((64, 64))
            self._icon_photo = ImageTk.PhotoImage(icon)
            self.iconphoto(True, self._icon_photo)
        except Exception:
            pass
        apply_icon(self, self.logo_img)

    def _build_header(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 0))
        head.grid_columnconfigure(1, weight=1)

        h = 58
        w = max(1, int(h * self.logo_img.width / float(self.logo_img.height or 1)))
        if w > 220:
            w, h = 220, max(1, int(220 * self.logo_img.height / float(self.logo_img.width)))
        logo = ctk.CTkImage(light_image=self.logo_img, dark_image=self.logo_img, size=(w, h))
        logo_btn = ctk.CTkLabel(head, image=logo, text="", cursor="hand2")
        logo_btn.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 16))
        logo_btn.bind("<Button-1>", lambda e: webbrowser.open(SOFTWARE_PAGE))

        ctk.CTkLabel(head, text="DJ PARADISE", font=font(30, "bold"), text_color=TEXT
                     ).grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(head, text="Build your crate from Spotify, SoundCloud and YouTube",
                     font=font(13), text_color=MUTED).grid(row=1, column=1, sticky="nw")

        right = ctk.CTkFrame(head, fg_color="transparent")
        right.grid(row=0, column=2, rowspan=2, sticky="e")
        ctk.CTkButton(right, text="Settings", width=96, height=38, corner_radius=10,
                      fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT, font=font(13),
                      command=lambda: SettingsWindow(self)).pack(side="right")
        self.all_btn = ctk.CTkButton(right, text="Download all", width=140, height=38, corner_radius=10,
                                     fg_color=ACCENT, hover_color=ACCENT_HOVER, font=font(13, "bold"),
                                     command=self.download_all)
        self.all_btn.pack(side="right", padx=(0, 10))

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
        bar.grid(row=1, column=0, sticky="ew", padx=28, pady=(18, 0))
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bar, text="SAVE TO", font=font(11, "bold"), text_color=MUTED
                     ).grid(row=0, column=0, padx=(18, 10), pady=12)
        self.path_btn = ctk.CTkButton(bar, text="", anchor="w", height=34, corner_radius=8,
                                      fg_color=FIELD, hover_color=CARD_HI, text_color=TEXT,
                                      font=font(12), command=self.choose_folder)
        self.path_btn.grid(row=0, column=1, sticky="ew", pady=12)
        self._show_path()
        ctk.CTkButton(bar, text="Open folder", width=110, height=34, corner_radius=8,
                      fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT, font=font(12),
                      command=self.open_output).grid(row=0, column=2, padx=(10, 18))

        ctk.CTkLabel(bar, text="FORMAT", font=font(11, "bold"), text_color=MUTED
                     ).grid(row=0, column=3, padx=(4, 10))
        self.fmt = ctk.CTkSegmentedButton(bar, values=FORMATS, height=34, corner_radius=8,
                                          fg_color=FIELD, selected_color=ACCENT,
                                          selected_hover_color=ACCENT_HOVER,
                                          unselected_color=FIELD, unselected_hover_color=CARD_HI,
                                          text_color=TEXT, font=font(12, "bold"),
                                          command=self.set_format)
        self.fmt.set(self.settings["format"])
        self.fmt.grid(row=0, column=4, padx=(0, 18))

    def _build_spots(self):
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.grid(row=2, column=0, sticky="nsew", padx=22, pady=(12, 0))
        for c in range(3):
            grid.grid_columnconfigure(c, weight=1, uniform="spot")
        for r in range(2):
            grid.grid_rowconfigure(r, weight=1)
        for i, spot in enumerate(SPOTS):
            card = SpotCard(grid, self, spot)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
            self.cards[spot["id"]] = card

    def _build_activity(self):
        box = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
        box.grid(row=3, column=0, sticky="ew", padx=28, pady=(10, 0))
        box.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 0))
        ctk.CTkLabel(top, text="ACTIVITY", font=font(11, "bold"), text_color=MUTED).pack(side="left")
        self.activity_count = ctk.CTkLabel(top, text="", font=font(11), text_color=FAINT)
        self.activity_count.pack(side="left", padx=(10, 0))
        ctk.CTkButton(top, text="Clear", width=60, height=24, corner_radius=6, fg_color="transparent",
                      hover_color=CARD_HI, text_color=MUTED, font=font(11),
                      command=self.clear_log).pack(side="right")
        self.logbox = ctk.CTkTextbox(box, height=130, fg_color=FIELD, corner_radius=10,
                                     border_width=0, text_color=TEXT, font=font(12),
                                     wrap="none", activate_scrollbars=True)
        self.logbox.grid(row=1, column=0, sticky="ew", padx=14, pady=(8, 14))
        tb = self.logbox._textbox
        tb.tag_configure("time", foreground=FAINT)
        tb.tag_configure("ok", foreground=GOOD)
        tb.tag_configure("error", foreground=BAD)
        tb.tag_configure("info", foreground=MUTED)
        for spot in SPOTS:
            tb.tag_configure("svc_" + spot["service"], foreground=spot["color"])
        self.logbox.configure(state="disabled")

    def _build_footer(self):
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=4, column=0, sticky="ew", padx=30, pady=(8, 12))
        ctk.CTkLabel(foot, text="© 2026 %s  ·  Huntsville, Alabama  ·  v%s" % (COMPANY, APP_VERSION),
                     font=font(11), text_color=FAINT).pack(side="left")
        link = ctk.CTkLabel(foot, text="hbcs.info", font=font(11, "bold"), text_color=MUTED, cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: webbrowser.open(WEBSITE))

    # -- settings helpers
    def _show_path(self):
        path = self.settings["output_dir"]
        shown = path if len(path) < 70 else "…" + path[-68:]
        self.path_btn.configure(text="  " + shown)

    def choose_folder(self):
        start = self.settings["output_dir"] if os.path.isdir(self.settings["output_dir"]) else os.path.expanduser("~")
        path = filedialog.askdirectory(initialdir=start, title="Choose where DJ Paradise saves music")
        if path:
            self.settings["output_dir"] = os.path.normpath(path)
            save_settings(self.settings)
            self._show_path()

    def open_output(self):
        os.makedirs(self.settings["output_dir"], exist_ok=True)
        open_path(self.settings["output_dir"])

    def set_format(self, value):
        self.settings["format"] = value
        save_settings(self.settings)

    def output_for(self, spot):
        base = self.settings["output_dir"]
        if self.settings.get("organize", True):
            return os.path.join(base, spot["service"])
        return base

    # -- actions
    def download_all(self):
        ready = [c for c in self.cards.values() if not c.busy and c.has_link()]
        if not ready:
            self.log("info", "Paste a link into any spot, then press Download all.")
            return
        started = sum(1 for c in ready if c.start())
        if started:
            self.log("info", "Started %d download%s" % (started, "" if started == 1 else "s"))
        self.refresh_activity()

    def refresh_activity(self):
        running = sum(1 for c in self.cards.values() if c.busy)
        self.activity_count.configure(text=("%d running" % running) if running else "")

    # -- log
    def log(self, level, text, spot=None):
        self.logbox.configure(state="normal")
        tb = self.logbox._textbox
        tb.insert("end", time.strftime("%H:%M  "), "time")
        if spot is not None:
            tb.insert("end", spot["service"] + "  ", "svc_" + spot["service"])
        tb.insert("end", text + "\n", level if level in ("ok", "error", "info") else "info")
        lines = int(tb.index("end-1c").split(".")[0])
        if lines > 600:
            tb.delete("1.0", "%d.0" % (lines - 600))
        tb.see("end")
        self.logbox.configure(state="disabled")

    def clear_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

    # -- event loop
    def poll(self):
        try:
            for _ in range(200):
                evt = self.events.get_nowait()
                card = self.cards.get(evt[0])
                if card is not None:
                    card.handle(*evt[1:])
        except queue.Empty:
            pass
        self.refresh_activity()
        self.after(100, self.poll)

    def on_close(self):
        busy = [c for c in self.cards.values() if c.busy]
        if busy:
            if not messagebox.askyesno(APP_NAME, "%d download%s still running. Stop and close?"
                                       % (len(busy), "" if len(busy) == 1 else "s")):
                return
            for c in busy:
                c.job.cancel()
        self.destroy()


def main():
    app = DJParadise()
    app.mainloop()


if __name__ == "__main__":
    main()
