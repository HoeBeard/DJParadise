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
import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from engines import SPOTS, FORMATS, DownloadJob, validate_url  # noqa: E402

APP_NAME = "DJ Paradise"
APP_VERSION = "1.2.0"
COMPANY = "HB Software"
WEBSITE = "https://hbcs.info"
SOFTWARE_PAGE = "https://hbcs.info/software/"

ASSETS = os.path.join(ROOT, "assets")
LOGO_PNG = os.path.join(ASSETS, "hb_software_logo.png")
LOGO_ICO = os.path.join(ASSETS, "hb_software_logo.ico")
SETTINGS_FILE = os.path.join(ROOT, ".runtime", "settings.json")
IS_WIN = os.name == "nt"

# Palette
BG = "#05080f"
PANEL = "#0b111d"
CARD = "#0f1726"
CARD_HI = "#16213a"
FIELD = "#070c16"
BORDER = "#1a2a48"
TEXT = "#eaf2ff"
MUTED = "#8195b8"
FAINT = "#45567a"
ACCENT = "#1e90ff"
ACCENT_HOVER = "#1273d6"
GOOD = "#2ecc71"
BAD = "#ff5d6c"


def font(size, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def make_menu(parent):
    return tk.Menu(parent, tearoff=0, bg=CARD_HI, fg=TEXT, activebackground=ACCENT,
                   activeforeground="white", bd=0, relief="flat", font=("Segoe UI", 10))


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
        "spot_dirs": {},
        "recent_dirs": [],
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data.update(json.load(fh))
    except Exception:
        pass
    if data.get("format") not in FORMATS:
        data["format"] = "MP3"
    if not isinstance(data.get("spot_dirs"), dict):
        data["spot_dirs"] = {}
    if not isinstance(data.get("recent_dirs"), list):
        data["recent_dirs"] = []
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
        self.status.grid(row=5, column=0, sticky="ew", padx=18, pady=(8, 0))

        dest = ctk.CTkFrame(self, fg_color=FIELD, corner_radius=8)
        dest.grid(row=6, column=0, sticky="ew", padx=18, pady=(10, 16))
        dest.grid_columnconfigure(0, weight=1)
        self.dest_label = ctk.CTkLabel(dest, text="", text_color=MUTED, font=font(11),
                                       anchor="w", cursor="hand2")
        self.dest_label.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=4)
        self.dest_label.bind("<Button-1>", lambda e: self.app.open_folder(self.app.output_for(self.spot)))
        self.dest_btn = ctk.CTkButton(dest, text="Change", width=64, height=24, corner_radius=6,
                                      fg_color="transparent", hover_color=CARD_HI,
                                      text_color=ACCENT, font=font(11, "bold"),
                                      command=self.folder_menu)
        self.dest_btn.grid(row=0, column=1, padx=(0, 4), pady=4)
        self.refresh_destination()
        self.bind("<Configure>", self._rewrap)

    def _rewrap(self, event):
        self.status.configure(wraplength=max(event.width - 40, 120))
        self.refresh_destination(event.width)

    # -- save location for this spot
    def refresh_destination(self, width=None):
        path = self.app.output_for(self.spot)
        custom = self.spot["id"] in self.app.settings.get("spot_dirs", {})
        try:
            width = int(width or self.winfo_width())
        except Exception:
            width = 320
        if width < 100:
            width = 320
        room = max(int((width - 140) / 6.5), 16)
        shown = path if len(path) <= room else "…" + path[-(room - 1):]
        self.dest_label.configure(text=("★ " if custom else "") + shown,
                                  text_color=TEXT if custom else MUTED)

    def folder_menu(self):
        menu = make_menu(self)
        menu.add_command(label="Choose a folder for %s %s…" % (self.spot["service"], self.spot["kind"].lower()),
                         command=self.choose_folder)
        if self.spot["id"] in self.app.settings.get("spot_dirs", {}):
            menu.add_command(label="Use the main Save To folder", command=self.reset_folder)
        menu.add_separator()
        menu.add_command(label="Open this folder", command=lambda: self.app.open_folder(self.app.output_for(self.spot)))
        x = self.dest_btn.winfo_rootx()
        y = self.dest_btn.winfo_rooty() + self.dest_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def choose_folder(self):
        current = self.app.output_for(self.spot)
        start = current if os.path.isdir(current) else self.app.settings["output_dir"]
        path = filedialog.askdirectory(initialdir=start if os.path.isdir(start) else os.path.expanduser("~"),
                                       title="Where should %s %s downloads go?" % (self.spot["service"], self.spot["kind"].lower()))
        if path:
            self.app.settings.setdefault("spot_dirs", {})[self.spot["id"]] = os.path.normpath(path)
            self.app.remember_recent(path)
            save_settings(self.app.settings)
            self.refresh_destination()
            self.app.log("info", "%s %s now saves to %s" % (self.spot["service"], self.spot["kind"].lower(), os.path.normpath(path)))

    def reset_folder(self):
        self.app.settings.get("spot_dirs", {}).pop(self.spot["id"], None)
        save_settings(self.app.settings)
        self.refresh_destination()

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
        self.run_id = self.app.next_run_id()
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
        elif kind == "track":
            self.app.downloads.set_track(self.spot, (self.run_id, args[0]), args[1])
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
        self.app.downloads.finish_run(self.run_id, ok, text)
        self.app.log("ok" if ok else "error", "%s %s  ·  %s"
                     % (self.spot["service"], self.spot["kind"].lower(), text))
        if ok:
            self.entry.delete(0, "end")
        self.app.refresh_activity()


# --------------------------------------------------------------------------
# Downloads list - one live progress bar per track
# --------------------------------------------------------------------------

STATE_TEXT = {"queued": "Queued", "downloading": "Downloading", "converting": "Converting",
              "done": "Saved", "skipped": "In library", "failed": "Failed"}
FINISHED = ("done", "skipped", "failed")


def _short(text, n):
    text = text or ""
    return text if len(text) <= n else text[:n - 1].rstrip() + "\u2026"


class TrackRow(ctk.CTkFrame):
    def __init__(self, master, spot):
        ctk.CTkFrame.__init__(self, master, fg_color=CARD, corner_radius=10, height=46)
        self.spot = spot
        self.state = None
        self.raw_title = ""
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(self, width=4, height=30, fg_color=spot["color"], corner_radius=2
                     ).grid(row=0, column=0, rowspan=2, padx=(10, 10), pady=8, sticky="ns")
        self.title = ctk.CTkLabel(self, text="", anchor="w", font=font(12, "bold"), text_color=TEXT, height=18)
        self.title.grid(row=0, column=1, sticky="ew", pady=(7, 0))
        self.detail = ctk.CTkLabel(self, text="", anchor="w", font=font(11), text_color=MUTED, height=16)
        self.detail.grid(row=1, column=1, sticky="ew", pady=(0, 7))
        self.bar = ctk.CTkProgressBar(self, width=190, height=6, corner_radius=3,
                                      fg_color=FIELD, progress_color=spot["color"])
        self.bar.grid(row=0, column=2, rowspan=2, padx=(12, 12))
        self.bar.set(0)
        self.pct = ctk.CTkLabel(self, text="", width=44, anchor="e", font=font(12, "bold"), text_color=TEXT)
        self.pct.grid(row=0, column=3, rowspan=2)
        self.badge = ctk.CTkLabel(self, text="", width=92, anchor="e", font=font(11, "bold"), text_color=MUTED)
        self.badge.grid(row=0, column=4, rowspan=2, padx=(6, 14))

    def apply(self, info):
        state = info.get("state", "downloading")
        prog = max(0.0, min(1.0, float(info.get("progress") or 0.0)))
        if state == "done":
            prog = 1.0
        self.raw_title = info.get("title") or self.raw_title or "Track"
        self.title.configure(text=_short("%s  \u00B7  %s" % (self.spot["service"], self.raw_title), 90))
        self.detail.configure(text=_short(info.get("detail") or "", 110),
                              text_color=BAD if state == "failed" else MUTED)
        self.bar.set(prog)
        if state == "failed":
            self.bar.configure(progress_color=BAD)
        self.pct.configure(text="" if state in ("failed", "skipped") else "%d%%" % int(prog * 100))
        color = {"done": GOOD, "skipped": MUTED, "failed": BAD}.get(state, self.spot["color"])
        self.badge.configure(text=STATE_TEXT.get(state, state.title()), text_color=color)
        self.state = state


class DownloadsList(ctk.CTkScrollableFrame):
    MAX_ROWS = 150

    def __init__(self, master, app):
        ctk.CTkScrollableFrame.__init__(self, master, fg_color=FIELD, corner_radius=10,
                                        scrollbar_button_color=BORDER,
                                        scrollbar_button_hover_color=FAINT)
        self.app = app
        self.rows = {}
        self.order = []
        self.empty = ctk.CTkLabel(self, text="Downloads show up here with a live progress bar for every track.",
                                  font=font(12), text_color=FAINT)
        self.empty.pack(pady=40)
        self.empty_shown = True

    def set_track(self, spot, key, info):
        row = self.rows.get(key)
        if row is None:
            if self.empty_shown:
                self.empty.pack_forget()
                self.empty_shown = False
            row = TrackRow(self, spot)
            first = next((self.rows[k] for k in reversed(self.order) if k in self.rows), None)
            if first is not None:
                row.pack(fill="x", padx=6, pady=(6, 0), before=first)
            else:
                row.pack(fill="x", padx=6, pady=(6, 0))
            self.rows[key] = row
            self.order.append(key)
            self._trim()
        row.apply(info)

    def finish_run(self, run_id, ok, text):
        # Anything still marked active when a spot stops was cut short.
        for key, row in self.rows.items():
            if key[0] == run_id and row.state not in FINISHED:
                row.apply({"title": row.raw_title, "state": "failed", "progress": 0.0,
                           "detail": "Didn't finish" if ok else text})

    def active_count(self):
        return sum(1 for r in self.rows.values() if r.state not in FINISHED)

    def clear_finished(self):
        for key in list(self.order):
            row = self.rows.get(key)
            if row is not None and row.state in FINISHED:
                row.destroy()
                del self.rows[key]
                self.order.remove(key)
        if not self.rows and not self.empty_shown:
            self.empty.pack(pady=40)
            self.empty_shown = True

    def _trim(self):
        while len(self.rows) > self.MAX_ROWS:
            victim = next((k for k in self.order if self.rows[k].state in FINISHED), None)
            if victim is None:
                return
            self.rows.pop(victim).destroy()
            self.order.remove(victim)


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

        ctk.CTkLabel(wrap, text="SAVE LOCATIONS", font=font(11, "bold"), text_color=MUTED).pack(anchor="w", pady=(18, 4))
        custom = len(app.settings.get("spot_dirs", {}))
        ctk.CTkLabel(wrap, text=("%d spot%s use%s its own folder." % (custom, "" if custom == 1 else "s", "s" if custom == 1 else ""))
                     if custom else "Every spot saves to the main Save To folder.",
                     font=font(12), text_color=TEXT).pack(anchor="w")
        ctk.CTkButton(wrap, text="Send every spot to the main folder", width=10, height=30, corner_radius=8,
                      fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT, font=font(12),
                      state="normal" if custom else "disabled",
                      command=self.reset_spots).pack(anchor="w", pady=(8, 0))

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

    def reset_spots(self):
        self.app.settings["spot_dirs"] = {}
        save_settings(self.app.settings)
        self.app.refresh_destinations()
        self.app.log("info", "Every spot now saves to the main folder")
        self.destroy()

    def save(self):
        s = self.app.settings
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
        self._run_seq = 0

        self.title("%s  |  %s" % (APP_NAME, COMPANY))
        self.geometry("1240x900")
        self.minsize(1000, 700)
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

        h = 72
        w = max(1, int(h * self.logo_img.width / float(self.logo_img.height or 1)))
        if w > 240:
            w, h = 240, max(1, int(240 * self.logo_img.height / float(self.logo_img.width)))
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
                     ).grid(row=0, column=0, padx=(18, 10), pady=(12, 0))
        self.path_entry = ctk.CTkEntry(bar, height=34, corner_radius=8, fg_color=FIELD,
                                       border_color=BORDER, border_width=1, text_color=TEXT,
                                       font=font(12))
        self.path_entry.grid(row=0, column=1, sticky="ew", pady=(12, 0))
        self.path_entry.bind("<Return>", lambda e: self.apply_typed_path())
        self.path_entry.bind("<FocusOut>", lambda e: self.apply_typed_path(quiet=True))
        self._show_path()

        btns = ctk.CTkFrame(bar, fg_color="transparent")
        btns.grid(row=0, column=2, padx=(8, 18), pady=(12, 0))
        ctk.CTkButton(btns, text="Change…", width=86, height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
                      font=font(12, "bold"), command=self.choose_folder).pack(side="left")
        self.recent_btn = ctk.CTkButton(btns, text="Recent ▾", width=84, height=34, corner_radius=8,
                                        fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT,
                                        font=font(12), command=self.recent_menu)
        self.recent_btn.pack(side="left", padx=(6, 0))
        ctk.CTkButton(btns, text="Open", width=64, height=34, corner_radius=8,
                      fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT, font=font(12),
                      command=self.open_output).pack(side="left", padx=(6, 0))

        self.organize = ctk.CTkSwitch(bar, text="Sort into Spotify, SoundCloud and YouTube folders",
                                      font=font(12), text_color=MUTED, progress_color=ACCENT,
                                      switch_width=34, switch_height=17, command=self.set_organize)
        if self.settings.get("organize", True):
            self.organize.select()
        self.organize.grid(row=1, column=1, sticky="w", pady=(8, 12))
        ctk.CTkLabel(bar, text="Type or paste a folder and press Enter, or use Change. Each spot can also have its own folder.",
                     font=font(11), text_color=FAINT, anchor="e"
                     ).grid(row=1, column=2, columnspan=3, sticky="e", padx=(8, 18), pady=(8, 12))

        ctk.CTkLabel(bar, text="FORMAT", font=font(11, "bold"), text_color=MUTED
                     ).grid(row=0, column=3, padx=(4, 10), pady=(12, 0))
        self.fmt = ctk.CTkSegmentedButton(bar, values=FORMATS, height=34, corner_radius=8,
                                          fg_color=FIELD, selected_color=ACCENT,
                                          selected_hover_color=ACCENT_HOVER,
                                          unselected_color=FIELD, unselected_hover_color=CARD_HI,
                                          text_color=TEXT, font=font(12, "bold"),
                                          command=self.set_format)
        self.fmt.set(self.settings["format"])
        self.fmt.grid(row=0, column=4, padx=(0, 18), pady=(12, 0))

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
        """Bottom panel: live per-track Downloads list + Activity log. Can be hidden."""
        box = self.panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14,
                                        border_width=1, border_color=BORDER)
        box.grid(row=3, column=0, sticky="ew", padx=28, pady=(10, 0))
        box.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        top.grid_columnconfigure(2, weight=1)
        self.tabs = ctk.CTkSegmentedButton(top, values=["Downloads", "Activity"], height=30,
                                           corner_radius=8, fg_color=FIELD, selected_color=CARD_HI,
                                           selected_hover_color=BORDER, unselected_color=FIELD,
                                           unselected_hover_color=CARD_HI, text_color=TEXT,
                                           font=font(12, "bold"), command=self.show_tab)
        self.tabs.grid(row=0, column=0, sticky="w")
        self.activity_count = ctk.CTkLabel(top, text="", font=font(12), text_color=MUTED)
        self.activity_count.grid(row=0, column=1, sticky="w", padx=(14, 0))

        right = ctk.CTkFrame(top, fg_color="transparent")
        right.grid(row=0, column=3, sticky="e")
        self.overall_bar = ctk.CTkProgressBar(right, width=160, height=6, corner_radius=3,
                                              fg_color=FIELD, progress_color=ACCENT)
        self.overall_bar.set(0)
        self.overall_pct = ctk.CTkLabel(right, text="", width=40, font=font(11, "bold"), text_color=MUTED)
        self.clear_btn = ctk.CTkButton(right, text="Clear finished", width=104, height=28, corner_radius=8,
                                       fg_color="transparent", hover_color=CARD_HI, text_color=MUTED,
                                       font=font(12), command=self.clear_current)
        self.clear_btn.pack(side="left", padx=(10, 0))
        self.toggle_btn = ctk.CTkButton(right, text="", width=86, height=28, corner_radius=8,
                                        fg_color=CARD_HI, hover_color=BORDER, text_color=TEXT,
                                        font=font(12, "bold"), command=self.toggle_panel)
        self.toggle_btn.pack(side="left", padx=(8, 0))

        self.panel_body = ctk.CTkFrame(box, fg_color="transparent", height=200)
        self.panel_body.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.panel_body.grid_columnconfigure(0, weight=1)
        self.panel_body.grid_propagate(False)
        self.panel_body.grid_rowconfigure(0, weight=1)

        self.downloads = DownloadsList(self.panel_body, self)
        self.downloads.grid(row=0, column=0, sticky="nsew")

        self.logbox = ctk.CTkTextbox(self.panel_body, fg_color=FIELD, corner_radius=10,
                                     border_width=0, text_color=TEXT, font=font(12),
                                     wrap="none", activate_scrollbars=True)
        self.logbox.grid(row=0, column=0, sticky="nsew")
        tb = self.logbox._textbox
        tb.tag_configure("time", foreground=FAINT)
        tb.tag_configure("ok", foreground=GOOD)
        tb.tag_configure("error", foreground=BAD)
        tb.tag_configure("info", foreground=MUTED)
        for spot in SPOTS:
            tb.tag_configure("svc_" + spot["service"], foreground=spot["color"])
        self.logbox.configure(state="disabled")

        tab = self.settings.get("panel_tab", "Downloads")
        self.tabs.set(tab if tab in ("Downloads", "Activity") else "Downloads")
        self.show_tab(self.tabs.get(), save=False)
        self.set_panel_open(self.settings.get("panel_open", True), save=False)

    def show_tab(self, name, save=True):
        if name == "Activity":
            self.downloads.grid_remove()
            self.logbox.grid()
            self.clear_btn.configure(text="Clear log")
        else:
            self.logbox.grid_remove()
            self.downloads.grid()
            self.clear_btn.configure(text="Clear finished")
        if save:
            self.settings["panel_tab"] = name
            save_settings(self.settings)

    def set_panel_open(self, is_open, save=True):
        self.panel_open = bool(is_open)
        if self.panel_open:
            self.panel_body.grid()
            self.tabs.configure(state="normal")
            self.clear_btn.pack(side="left", padx=(10, 0), before=self.toggle_btn)
            self.toggle_btn.configure(text="Hide \u25BE")
        else:
            self.panel_body.grid_remove()
            self.clear_btn.pack_forget()
            self.toggle_btn.configure(text="Show \u25B4")
        if save:
            self.settings["panel_open"] = self.panel_open
            save_settings(self.settings)

    def toggle_panel(self):
        self.set_panel_open(not self.panel_open)

    def clear_current(self):
        if self.tabs.get() == "Activity":
            self.clear_log()
        else:
            self.downloads.clear_finished()

    def next_run_id(self):
        self._run_seq += 1
        return self._run_seq

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
        self.path_entry.configure(border_color=BORDER)
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, self.settings["output_dir"])

    def set_output_dir(self, path, announce=True):
        path = os.path.normpath(os.path.expandvars(os.path.expanduser(path.strip().strip('"'))))
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            self.path_entry.configure(border_color=BAD)
            self.log("error", "Can't save to %s. Pick a different folder." % path)
            return False
        changed = path != self.settings["output_dir"]
        self.settings["output_dir"] = path
        self.remember_recent(path)
        save_settings(self.settings)
        self._show_path()
        self.refresh_destinations()
        if changed and announce:
            self.log("info", "Saving to %s" % path)
        return True

    def apply_typed_path(self, quiet=False):
        typed = self.path_entry.get().strip()
        if not typed:
            self._show_path()
            return
        if os.path.normpath(typed) == self.settings["output_dir"]:
            return
        if not self.set_output_dir(typed) and quiet:
            self._show_path()

    def choose_folder(self):
        start = self.settings["output_dir"] if os.path.isdir(self.settings["output_dir"]) else os.path.expanduser("~")
        path = filedialog.askdirectory(initialdir=start, title="Choose where DJ Paradise saves music")
        if path:
            self.set_output_dir(path)

    def remember_recent(self, path):
        path = os.path.normpath(path)
        recent = [p for p in self.settings.get("recent_dirs", []) if os.path.normpath(p) != path]
        self.settings["recent_dirs"] = [path] + recent[:7]

    def recent_menu(self):
        menu = make_menu(self)
        recent = [p for p in self.settings.get("recent_dirs", []) if p != self.settings["output_dir"]]
        for p in recent:
            menu.add_command(label=p, command=lambda p=p: self.set_output_dir(p))
        if recent:
            menu.add_separator()
        default = default_music_dir()
        if default != self.settings["output_dir"]:
            menu.add_command(label="Default  (%s)" % default, command=lambda: self.set_output_dir(default))
        desktop = os.path.join(os.path.expanduser("~"), "Desktop", "DJ Paradise")
        if desktop != self.settings["output_dir"]:
            menu.add_command(label="Desktop  (%s)" % desktop, command=lambda: self.set_output_dir(desktop))
        menu.add_separator()
        menu.add_command(label="Browse…", command=self.choose_folder)
        x = self.recent_btn.winfo_rootx()
        y = self.recent_btn.winfo_rooty() + self.recent_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def set_organize(self):
        self.settings["organize"] = bool(self.organize.get())
        save_settings(self.settings)
        self.refresh_destinations()

    def refresh_destinations(self):
        for card in self.cards.values():
            card.refresh_destination()

    def open_folder(self, path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        open_path(path)

    def open_output(self):
        self.open_folder(self.settings["output_dir"])

    def set_format(self, value):
        self.settings["format"] = value
        save_settings(self.settings)

    def output_for(self, spot):
        custom = self.settings.get("spot_dirs", {}).get(spot["id"])
        if custom:
            return custom
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
        busy = [c for c in self.cards.values() if c.busy]
        active = self.downloads.active_count()
        parts = []
        if busy:
            parts.append("%d spot%s running" % (len(busy), "" if len(busy) == 1 else "s"))
        if active:
            parts.append("%d track%s downloading" % (active, "" if active == 1 else "s"))
        text = "  \u00B7  ".join(parts)
        if text != getattr(self, "_summary", None):
            self._summary = text
            self.activity_count.configure(text=text)
        if busy:
            values = []
            for c in busy:
                try:
                    values.append(0.0 if c._indeterminate else float(c.bar.get()))
                except Exception:
                    values.append(0.0)
            avg = sum(values) / len(values)
            if not getattr(self, "_overall_shown", False):
                self._overall_shown = True
                anchor = self.clear_btn if self.panel_open else self.toggle_btn
                self.overall_pct.pack(side="left", before=anchor)
                self.overall_bar.pack(side="left", padx=(0, 8), before=self.overall_pct)
            self.overall_bar.set(avg)
            self.overall_pct.configure(text="%d%%" % int(avg * 100))
        elif getattr(self, "_overall_shown", False):
            self._overall_shown = False
            self.overall_bar.pack_forget()
            self.overall_pct.pack_forget()

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
        # Progress arrives many times a second; only draw the latest state per track.
        latest = {}
        ordered = []
        try:
            for _ in range(2000):
                evt = self.events.get_nowait()
                if evt[1] == "track":
                    k = (evt[0], evt[2])
                    if k not in latest:
                        ordered.append(k)
                    latest[k] = evt
                else:
                    for k in ordered:
                        self._dispatch(latest[k])
                    latest.clear()
                    del ordered[:]
                    self._dispatch(evt)
        except queue.Empty:
            pass
        for k in ordered:
            self._dispatch(latest[k])
        self.refresh_activity()
        self.after(100, self.poll)

    def _dispatch(self, evt):
        card = self.cards.get(evt[0])
        if card is not None:
            card.handle(*evt[1:])

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
