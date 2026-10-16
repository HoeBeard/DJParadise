# -*- coding: utf-8 -*-
"""
DJ Paradise - Spotify download worker
Copyright (c) 2026 HB Software. All rights reserved.

Runs one Spotify download and reports per-song progress as lines of
"DJS {json}" on stdout so the main window can draw a progress bar per track.
Exit code 3 means this engine version can't report progress; the caller then
falls back to the standard command-line download.
"""

import json
import logging
import sys
import threading

_LOCK = threading.Lock()


def out(**data):
    with _LOCK:
        sys.stdout.write("DJS " + json.dumps(data) + "\n")
        sys.stdout.flush()


def main():
    cfg = json.loads(sys.argv[1])

    try:
        from spotdl import Spotdl
        try:
            from spotdl.utils.config import SPOTIFY_OPTIONS as defaults
        except Exception:
            defaults = {}
    except Exception as exc:
        out(e="fallback", msg=str(exc))
        return 3

    client_id = cfg.get("client_id") or defaults.get("client_id")
    client_secret = cfg.get("client_secret") or defaults.get("client_secret")
    if not client_id or not client_secret:
        out(e="fallback", msg="no default app keys")
        return 3

    logging.basicConfig(level=logging.ERROR, format="%(message)s", stream=sys.stdout)

    settings = {
        "output": cfg["output"],
        "format": cfg["format"],
        "ffmpeg": cfg["ffmpeg"],
        "threads": 4,
        "overwrite": "skip",
        "simple_tui": True,
    }
    if cfg.get("bitrate"):
        settings["bitrate"] = cfg["bitrate"]

    try:
        client = Spotdl(client_id=client_id, client_secret=client_secret,
                        downloader_settings=settings)
        handler = client.downloader.progress_handler
    except (TypeError, AttributeError) as exc:
        out(e="fallback", msg=str(exc))
        return 3
    except Exception as exc:
        out(e="error", msg="%s: %s" % (exc.__class__.__name__, exc))
        return 1

    last = {}

    def on_update(tracker, message):
        song = tracker.song
        key = getattr(song, "url", None) or getattr(song, "song_id", None) or tracker.song_name
        pct = int(getattr(tracker, "progress", 0) or 0)
        if last.get(key) == (pct, message):
            return
        last[key] = (pct, message)
        out(e="track", id=key, title=getattr(song, "display_name", tracker.song_name), p=pct, msg=message)

    # Report fine-grained progress (the plain console mode only reports milestones).
    try:
        handler.web_ui = True
        handler.update_callback = on_update
    except Exception as exc:
        out(e="fallback", msg=str(exc))
        return 3

    out(e="status", msg="Reading link")
    try:
        songs = client.search([cfg["url"]])
    except Exception as exc:
        out(e="error", msg="%s: %s" % (exc.__class__.__name__, exc))
        return 1
    if not songs:
        out(e="error", msg="No songs found at that link.")
        return 1

    out(e="found", total=len(songs),
        songs=[{"id": s.url, "title": s.display_name} for s in songs])

    try:
        results = client.downloader.download_multiple_songs(songs)
    except Exception as exc:
        out(e="error", msg="%s: %s" % (exc.__class__.__name__, exc))
        return 1

    ok = sum(1 for _, path in results if path)
    out(e="done", ok=ok, fail=len(results) - ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
