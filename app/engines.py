# -*- coding: utf-8 -*-
"""
DJ Paradise - Download Engines
Copyright (c) 2026 HB Software. All rights reserved.
"""

import json
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
# Output parsers - turn engine output into progress + friendly status text.
#
# Every parser emits, through emit(kind, *args):
#   ("status", text)                 one-line status for the spot card
#   ("progress", 0..1 | None)        overall progress for the spot card
#   ("log", level, text)             a line for the Activity log
#   ("track", key, info)             live state of one track, where info is
#        {"title", "state", "progress", "detail"} and state is one of
#        queued / downloading / converting / done / skipped / failed
# --------------------------------------------------------------------------

def _fmt_speed(text):
    text = (text or "").strip()
    return "" if not text or text.lower().startswith(("unknown", "n/a", "na")) else text


def _fmt_eta(text):
    text = (text or "").strip()
    if not text or text.lower().startswith(("unknown", "n/a", "na")):
        return ""
    if text.startswith("00:") and text.count(":") == 2:
        text = text[3:]
    if text.startswith("0") and len(text) == 5 and text[2] == ":":
        text = text[1:]
    return text


class _Parser(object):
    def __init__(self, emit, collection):
        self.emit = emit
        self.collection = collection
        self.total = 0 if collection else 1
        self.completed = 0
        self.failed = 0
        self.last_error = ""

    def error(self, text, count=True):
        if count:
            self.failed += 1
        self.last_error = text
        self.emit("log", "error", text)

    def track(self, key, title, state, progress, detail=""):
        self.emit("track", key, {"title": title, "state": state,
                                 "progress": progress, "detail": detail})


class YtDlpParser(_Parser):
    _ITEM = re.compile(r"^DJITEM (\d+)/(\d+) (.*)$")
    _PROG = re.compile(r"^DJPROG\s*([\d.]+)%\|([^|]*)\|([^|]*)\|?(.*)$")
    _DONE = re.compile(r"^DJDONE (.*)$")

    def __init__(self, emit, collection):
        _Parser.__init__(self, emit, collection)
        self.index = 0
        self.seq = 0
        self.title = ""
        self.key = None
        self.active = False

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
            self.seq += 1
            self.key = "y%d" % self.seq
            self.active = True
            if self.total > 1:
                self.emit("status", "Downloading %d of %d  ·  %s" % (max(self.index, 1), self.total, self.title))
            else:
                self.emit("status", "Downloading  ·  %s" % self.title)
            self.emit("progress", self.overall(0.0))
            self.track(self.key, self.title, "downloading", 0.0, "Starting")
            return
        m = self._PROG.match(line)
        if m:
            pct = float(m.group(1)) / 100.0
            self.emit("progress", self.overall(pct * 0.92))
            if not self.active:
                return
            if pct >= 0.999:
                self.emit("status", "Converting  ·  %s" % self.title)
                self.track(self.key, self.title, "converting", 0.95, "Converting")
            else:
                bits = []
                size = (m.group(4) or "").strip()
                if size and not size.lower().startswith(("unknown", "n/a", "na")):
                    bits.append(size)
                speed = _fmt_speed(m.group(2))
                if speed:
                    bits.append(speed)
                eta = _fmt_eta(m.group(3))
                if eta:
                    bits.append(eta + " left")
                self.track(self.key, self.title, "downloading", pct * 0.92,
                           "  ·  ".join(bits) or "%d%%" % int(pct * 100))
            return
        m = self._DONE.match(line)
        if m:
            self.completed += 1
            self.emit("log", "ok", "Saved  %s" % os.path.basename(m.group(1).strip()))
            self.emit("progress", self.overall(1.0))
            if self.key:
                self.track(self.key, self.title, "done", 1.0, "Saved")
            self.active = False
            return
        if line.startswith("ERROR:"):
            text = line[6:].strip()
            self.error(text)
            if self.active and self.key:
                self.track(self.key, self.title, "failed", 0.0, DownloadJob.friendly(text))
                self.active = False
            elif self.collection:
                # A playlist item that failed before it started downloading.
                self.seq += 1
                name = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", text)
                self.track("y%d" % self.seq, "Playlist item", "failed", 0.0, DownloadJob.friendly(name))


class SpotifyRunnerParser(_Parser):
    """Reads per-song progress from spotify_runner.py."""

    def __init__(self, emit, collection):
        _Parser.__init__(self, emit, collection)
        self.fallback = False
        self.songs = {}
        self.finished = set()

    def frac(self):
        if not self.total:
            return None
        parts = sum(self.songs.get(k, 0) for k in self.songs)
        return min(parts / float(self.total * 100), 1.0)

    def feed(self, line):
        if not line.startswith("DJS "):
            if "rate/request limit" in line or "429" in line:
                self.last_error = ("Spotify is limiting requests right now. Add your own Spotify app keys "
                                   "in Settings, or try again later.")
            return
        try:
            data = json.loads(line[4:])
        except Exception:
            return
        e = data.get("e")
        if e == "fallback":
            self.fallback = True
        elif e == "status":
            self.emit("status", data.get("msg", ""))
        elif e == "found":
            self.total = int(data.get("total") or 0)
            self.emit("status", "Found %d song%s  ·  downloading" % (self.total, "" if self.total == 1 else "s"))
            self.emit("progress", 0.0)
            for song in data.get("songs") or []:
                self.songs[song["id"]] = 0
        elif e == "track":
            self._track(data)
        elif e == "error":
            msg = data.get("msg", "")
            if "rate/request limit" in msg or "429" in msg:
                msg = ("Spotify is limiting requests right now. Add your own Spotify app keys "
                       "in Settings, or try again later.")
            self.error(msg, count=False)
        elif e == "done":
            self.completed = int(data.get("ok") or 0)
            self.failed = int(data.get("fail") or 0)

    def _track(self, data):
        key = data.get("id")
        title = data.get("title") or "Track"
        pct = int(data.get("p") or 0)
        msg = (data.get("msg") or "").strip()
        low = msg.lower()
        self.songs[key] = pct
        if low == "error":
            state, detail, prog = "failed", "Couldn't find a match", 0.0
            if key not in self.finished:
                self.finished.add(key)
                self.emit("log", "error", "Couldn't download  %s" % title)
        elif low.startswith("skip"):
            state, detail, prog = "skipped", "Already in your library", 1.0
            if key not in self.finished:
                self.finished.add(key)
                self.emit("log", "info", "Already in your library  %s" % title)
        elif low == "done" or pct >= 100:
            state, detail, prog = "done", "Saved", 1.0
            if key not in self.finished:
                self.finished.add(key)
                self.emit("log", "ok", "Saved  %s" % title)
        elif low.startswith("convert") or low.startswith("embed"):
            state, detail, prog = "converting", msg or "Converting", pct / 100.0
        elif low.startswith("download"):
            state, detail, prog = "downloading", "Downloading  ·  %d%%" % pct, pct / 100.0
        else:
            state, detail, prog = "downloading", msg or "Searching", pct / 100.0
        self.track("s:" + str(key), title, state, prog, detail)
        done = len(self.finished)
        if self.total > 1:
            self.emit("status", "%d of %d done  ·  %s" % (done, self.total, title))
        else:
            self.emit("status", "%s  ·  %s" % (detail, title))
        self.emit("progress", self.frac())


class SpotdlParser(_Parser):
    """Fallback: reads the standard spotDL command-line output."""
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
            self.track("c:" + m.group(1), m.group(1), "done", 1.0, "Saved")
            self._progress(m.group(1))
            return
        m = self._SKIPPED.search(line)
        if m:
            self.completed += 1
            self.emit("log", "info", "Already in your library  %s" % m.group(1))
            self.track("c:" + m.group(1), m.group(1), "skipped", 1.0, "Already in your library")
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
    """Runs one download in the background and reports through emit(kind, *args).
    See the parser notes above for the event kinds; a final ("done", ok, text)
    is always sent."""

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
            "--progress-template",
            "download:DJPROG %(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress._total_bytes_str,progress._total_bytes_estimate_str)s",
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

    def _spotify_template(self):
        if self.spot["collection"]:
            return _p(os.path.join(self.out_dir, "{list-name}", "{artists} - {title}.{output-ext}"))
        return _p(os.path.join(self.out_dir, "{artists} - {title}.{output-ext}"))

    def build_spotify_runner(self, ffmpeg):
        cfg = {
            "url": self.url,
            "output": self._spotify_template(),
            "format": self.fmt,
            "ffmpeg": ffmpeg,
            "bitrate": "320k" if self.fmt in ("mp3", "m4a") else None,
            "client_id": (self.settings.get("spotify_client_id") or "").strip(),
            "client_secret": (self.settings.get("spotify_client_secret") or "").strip(),
        }
        runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spotify_runner.py")
        return [sys.executable, runner, json.dumps(cfg)], SpotifyRunnerParser(self.emit, self.spot["collection"])

    def build_spotdl(self, ffmpeg):
        cmd = [
            sys.executable, "-m", "spotdl", "download", self.url,
            "--output", self._spotify_template(),
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
        return cmd, SpotdlParser(self.emit, self.spot["collection"])

    def engine_available(self):
        mod = "spotdl" if self.spot["engine"] == "spotdl" else "yt_dlp"
        try:
            __import__(mod)
            return True
        except Exception:
            return False

    # -- process
    def _execute(self, cmd, parser, ffmpeg):
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
        return self._proc.wait()

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
            self.emit("status", "Reading link")
            self.emit("progress", None)

            if self.spot["engine"] == "spotdl":
                cmd, parser = self.build_spotify_runner(ffmpeg)
                code = self._execute(cmd, parser, ffmpeg)
                if parser.fallback and not self._cancelled.is_set():
                    cmd, parser = self.build_spotdl(ffmpeg)
                    code = self._execute(cmd, parser, ffmpeg)
            else:
                cmd, parser = self.build_ytdlp(ffmpeg)
                code = self._execute(cmd, parser, ffmpeg)

            if self._cancelled.is_set():
                self.emit("done", False, "Stopped")
            elif parser.completed and parser.failed:
                self.emit("done", True, "Saved %d  ·  %d couldn't be downloaded" % (parser.completed, parser.failed))
            elif parser.completed:
                self.emit("done", True, "Saved %d track%s" % (parser.completed, "" if parser.completed == 1 else "s"))
            elif code == 0 and not parser.failed and not parser.last_error:
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
        if "limiting requests" in e:
            return err
        if "private" in e:
            return "That item is private."
        if "sign in" in e or ("age" in e and "confirm" in e):
            return "Needs a signed-in account"
        if "unavailable" in e or "removed" in e or "404" in e:
            return "Not available"
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
