# -*- coding: utf-8 -*-
"""
DJ Paradise - Download Engines
Copyright (c) 2026 HB Software. All rights reserved.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import threading

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0

# The six spots on the main screen. Row 1 = collections, row 2 = single tracks.
SPOTS = [
    {"id": "spotify_playlist", "service": "Spotify", "kind": "Playlist", "engine": "spotdl",
     "collection": True, "color": "#1ED760", "on_color": "#06130b",
     "hint": "Paste a Spotify playlist or album link"},
    {"id": "soundcloud_playlist", "service": "SoundCloud", "kind": "Playlist", "engine": "ytdlp",
     "collection": True, "color": "#FF6A1A", "on_color": "#1a0a00",
     "hint": "Paste a SoundCloud playlist or set link"},
    {"id": "youtube_playlist", "service": "YouTube", "kind": "Playlist", "engine": "ytdlp",
     "collection": True, "color": "#FF3355", "on_color": "#ffffff",
     "hint": "Paste a YouTube playlist link"},
    {"id": "spotify_song", "service": "Spotify", "kind": "Song", "engine": "spotdl",
     "collection": False, "color": "#1ED760", "on_color": "#06130b",
     "hint": "Paste a Spotify song link"},
    {"id": "soundcloud_song", "service": "SoundCloud", "kind": "Song", "engine": "ytdlp",
     "collection": False, "color": "#FF6A1A", "on_color": "#1a0a00",
     "hint": "Paste a SoundCloud track link"},
    {"id": "youtube_song", "service": "YouTube", "kind": "Song", "engine": "ytdlp",
     "collection": False, "color": "#FF3355", "on_color": "#ffffff",
     "hint": "Paste a YouTube video link"},
]

SPOT_BY_ID = {s["id"]: s for s in SPOTS}

FORMATS = ["MP3", "M4A", "FLAC", "WAV"]

_PATTERNS = {
    "spotify_playlist": r"(open\.spotify\.com/(intl-[a-z-]+/)?(playlist|album)/|^spotify:(playlist|album):)",
    "spotify_song": r"(open\.spotify\.com/(intl-[a-z-]+/)?track/|^spotify:track:)",
    "soundcloud_playlist": r"(soundcloud\.com/[^/]+/sets/|on\.soundcloud\.com/|soundcloud\.app\.goo\.gl/)",
    "soundcloud_song": r"(soundcloud\.com/(?!discover|search|you/)[^/?#]+/(?!sets/)[^/?#]+|on\.soundcloud\.com/|soundcloud\.app\.goo\.gl/)",
    "youtube_playlist": r"((youtube\.com|youtu\.be)/.*[?&]list=)",
    "youtube_song": r"(youtube\.com/(watch\?|shorts/|live/)|youtu\.be/[\w-]{6,}|music\.youtube\.com/watch)",
}

_SPOT_HELP = {
    "spotify_playlist": "That isn't a Spotify playlist link. Use Share > Copy link to playlist.",
    "spotify_song": "That isn't a Spotify song link. Use Share > Copy song link.",
    "soundcloud_playlist": "That isn't a SoundCloud playlist link.",
    "soundcloud_song": "That isn't a SoundCloud track link.",
    "youtube_playlist": "That link has no playlist in it. Open the playlist and copy its link.",
    "youtube_song": "That isn't a YouTube video link.",
}


def validate_url(spot_id, url):
    """Return (ok, message)."""
    url = (url or "").strip()
    if not url:
        return False, "Paste a link first."
    if not re.search(_PATTERNS[spot_id], url, re.I):
        return False, _SPOT_HELP[spot_id]
    return True, ""


def resolve_ffmpeg():
    """Return (ffmpeg, ffprobe) paths, or (None, None)."""
    ff = os.environ.get("DJP_FFMPEG")
    fp = os.environ.get("DJP_FFPROBE")
    if ff and os.path.exists(ff):
        return ff, fp if fp and os.path.exists(fp) else None
    try:
        from static_ffmpeg import run
        ff, fp = run.get_or_fetch_platform_executables_else_raise()
        if ff and os.path.exists(ff):
            return ff, fp
    except Exception:
        pass
    ff = shutil.which("ffmpeg")
    return (ff, shutil.which("ffprobe")) if ff else (None, None)


def _p(path):
    """Paths for output templates (forward slashes work on every platform)."""
    return path.replace("\\", "/")


# --------------------------------------------------------------------------
# Output parsers - turn engine output into progress + friendly status text
# --------------------------------------------------------------------------

class _Parser(object):
    def __init__(self, emit, collection):
        self.emit = emit
        self.collection = collection
        self.total = 0 if collection else 1
        self.completed = 0
        self.failed = 0
        self.last_error = ""

    def error(self, text):
        self.failed += 1
        self.last_error = text
        self.emit("log", "error", text)


class YtDlpParser(_Parser):
    _ITEM = re.compile(r"^DJITEM (\d+)/(\d+) (.*)$")
    _PROG = re.compile(r"^DJPROG\s*([\d.]+)%")
    _DONE = re.compile(r"^DJDONE (.*)$")

    def __init__(self, emit, collection):
        _Parser.__init__(self, emit, collection)
        self.index = 0
        self.title = ""

    def overall(self, item_fraction):
        if self.total <= 1:
            return item_fraction
        done_items = max(self.index - 1, 0)
        return min((done_items + item_fraction) / float(self.total), 1.0)

    def feed(self, line):
        m = self._ITEM.match(line)
        if m:
            self.index = int(m.group(1) or 0)
            total = int(m.group(2) or 0)
            if total:
                self.total = total
            self.title = m.group(3).strip()
            if self.total > 1:
                self.emit("status", "Downloading %d of %d  ·  %s" % (max(self.index, 1), self.total, self.title))
            else:
                self.emit("status", "Downloading  ·  %s" % self.title)
            self.emit("progress", self.overall(0.0))
            return
        m = self._PROG.match(line)
        if m:
            pct = float(m.group(1)) / 100.0
            self.emit("progress", self.overall(pct * 0.92))
            if pct >= 0.999:
                self.emit("status", "Converting  ·  %s" % self.title)
            return
        m = self._DONE.match(line)
        if m:
            self.completed += 1
            self.emit("log", "ok", "Saved  %s" % os.path.basename(m.group(1).strip()))
            self.emit("progress", self.overall(1.0))
            return
        if line.startswith("ERROR:"):
            self.error(line[6:].strip())
        elif line.startswith("WARNING:"):
            pass  # engine chatter, not useful to a DJ


class SpotdlParser(_Parser):
    _FOUND = re.compile(r"Found (\d+) songs? in", re.I)
    _DOWNLOADED = re.compile(r'Downloaded "(.+?)"', re.I)
    _SKIPPED = re.compile(r"Skipping (.+?) \(", re.I)
    _ERRORS = ("LookupError", "AudioProviderError", "DownloaderError", "FFmpegError",
               "SpotifyError", "rate/request limit", "Traceback", "Error:")

    def frac(self):
        if not self.total:
            return None
        return min((self.completed + self.failed) / float(self.total), 1.0)

    def feed(self, line):
        m = self._FOUND.search(line)
        if m:
            self.total = int(m.group(1))
            self.emit("status", "Found %d songs  ·  downloading" % self.total)
            self.emit("progress", 0.0)
            return
        m = self._DOWNLOADED.search(line)
        if m:
            self.completed += 1
            self.emit("log", "ok", "Saved  %s" % m.group(1))
            self._progress(m.group(1))
            return
        m = self._SKIPPED.search(line)
        if m:
            self.completed += 1
            self.emit("log", "info", "Already in your library  %s" % m.group(1))
            self._progress(m.group(1))
            return
        if line.startswith("Processing query"):
            self.emit("status", "Reading link")
            return
        if any(tag in line for tag in self._ERRORS):
            clean = line.strip()
            if "rate/request limit" in clean:
                clean = "Spotify is limiting requests right now. Add your own Spotify app keys in Settings, or try again later."
            self.error(clean)
            self.emit("progress", self.frac())

    def _progress(self, title):
        if self.total > 1:
            self.emit("status", "Downloaded %d of %d  ·  %s" % (self.completed, self.total, title))
        else:
            self.emit("status", "Downloaded  ·  %s" % title)
        self.emit("progress", self.frac())


# --------------------------------------------------------------------------
# Download job
# --------------------------------------------------------------------------

class DownloadJob(threading.Thread):
    """Runs one download in the background. emit(kind, *args) receives:
    ("status", text) ("progress", 0..1 or None) ("log", level, text) ("done", ok, text)
    """

    def __init__(self, spot, url, out_dir, fmt, settings, emit):
        threading.Thread.__init__(self)
        self.daemon = True
        self.spot = spot
        self.url = url.strip()
        self.out_dir = out_dir
        self.fmt = fmt.lower()
        self.settings = settings
        self.emit = emit
        self._proc = None
        self._cancelled = threading.Event()

    # -- command builders
    def build_ytdlp(self, ffmpeg):
        collection = self.spot["collection"]
        # SoundCloud titles rarely include the artist; YouTube titles usually do.
        if self.spot["service"] == "SoundCloud":
            name = "%(uploader|)s%(uploader& - |)s%(title)s.%(ext)s"
        else:
            name = "%(title)s.%(ext)s"
        if collection:
            template = "%(playlist_title,playlist,playlist_id|Playlist)s/" + name
        else:
            template = name
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--newline", "--no-colors", "--progress",
            "--ignore-errors", "--no-overwrites", "--trim-filenames", "180",
            "-f", "bestaudio/best",
            "-x", "--audio-format", self.fmt, "--audio-quality", "0",
            "--embed-metadata",
            "--ffmpeg-location", os.path.dirname(ffmpeg),
            "--progress-template", "download:DJPROG %(progress._percent_str)s",
            "--print", "before_dl:DJITEM %(playlist_index|0)s/%(n_entries|0)s %(title)s",
            "--print", "after_move:DJDONE %(filepath)s",
            "--no-simulate",
            "-P", self.out_dir,
            "-o", template,
        ]
        if self.fmt in ("mp3", "m4a", "flac"):
            cmd += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
        cmd.append("--yes-playlist" if collection else "--no-playlist")
        cmd.append(self.url)
        return cmd, YtDlpParser(self.emit, collection)

    def build_spotdl(self, ffmpeg):
        collection = self.spot["collection"]
        if collection:
            template = _p(os.path.join(self.out_dir, "{list-name}", "{artists} - {title}.{output-ext}"))
        else:
            template = _p(os.path.join(self.out_dir, "{artists} - {title}.{output-ext}"))
        cmd = [
            sys.executable, "-m", "spotdl", "download", self.url,
            "--output", template,
            "--format", self.fmt,
            "--ffmpeg", ffmpeg,
            "--threads", "4",
            "--simple-tui",
            "--overwrite", "skip",
        ]
        if self.fmt in ("mp3", "m4a"):
            cmd += ["--bitrate", "320k"]
        cid = (self.settings.get("spotify_client_id") or "").strip()
        secret = (self.settings.get("spotify_client_secret") or "").strip()
        if cid and secret:
            cmd += ["--client-id", cid, "--client-secret", secret]
        return cmd, SpotdlParser(self.emit, collection)

    def engine_available(self):
        mod = "spotdl" if self.spot["engine"] == "spotdl" else "yt_dlp"
        try:
            __import__(mod)
            return True
        except Exception:
            return False

    # -- lifecycle
    def run(self):
        try:
            if not self.engine_available():
                self.emit("done", False, "The %s engine isn't installed. Restart DJ Paradise to repair it."
                          % self.spot["service"])
                return
            ffmpeg, _ = resolve_ffmpeg()
            if not ffmpeg:
                self.emit("done", False, "The audio converter is missing. Restart DJ Paradise to repair it.")
                return
            os.makedirs(self.out_dir, exist_ok=True)
            if self.spot["engine"] == "spotdl":
                cmd, parser = self.build_spotdl(ffmpeg)
            else:
                cmd, parser = self.build_ytdlp(ffmpeg)

            self.emit("status", "Reading link")
            self.emit("progress", None)
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            env["PATH"] = os.pathsep.join([os.path.dirname(sys.executable),
                                           os.path.dirname(ffmpeg), env.get("PATH", "")])
            kwargs = {}
            if IS_WIN:
                kwargs["creationflags"] = NO_WINDOW
            else:
                kwargs["start_new_session"] = True
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                universal_newlines=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=self.out_dir, env=env, **kwargs)
            for raw in self._proc.stdout:
                if self._cancelled.is_set():
                    break
                line = raw.strip()
                if line:
                    parser.feed(line)
            code = self._proc.wait()

            if self._cancelled.is_set():
                self.emit("done", False, "Stopped")
            elif parser.completed and parser.failed:
                self.emit("done", True, "Saved %d  ·  %d couldn't be downloaded" % (parser.completed, parser.failed))
            elif parser.completed:
                self.emit("done", True, "Saved %d track%s" % (parser.completed, "" if parser.completed == 1 else "s"))
            elif code == 0 and not parser.failed:
                self.emit("done", True, "Done")
            else:
                self.emit("done", False, self.friendly(parser.last_error))
        except Exception as exc:
            self.emit("done", False, "Download failed (%s)" % exc)

    @staticmethod
    def friendly(err):
        e = (err or "").lower()
        if not e:
            return "Download failed. Check the link and your connection."
        if "private" in e:
            return "That item is private."
        if "sign in" in e or ("age" in e and "confirm" in e):
            return "That item needs a signed-in account and can't be downloaded."
        if "unavailable" in e or "removed" in e or "404" in e:
            return "That item isn't available."
        if "unable to download webpage" in e or "network" in e or "timed out" in e:
            return "Couldn't reach the site. Check your connection."
        return err[:160]

    def cancel(self):
        self._cancelled.set()
        proc = self._proc
        if not proc or proc.poll() is not None:
            return
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=NO_WINDOW)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
