"""
HTTP-Download-Logik für GME-Dateien.

Downloads laufen immer in einem Daemon-Thread, um den GTK-Hauptthread nicht zu
blockieren. Fortschritts- und Fertig-Callbacks werden über GLib.idle_add() sicher
in den GTK-Hauptthread zurückgerufen.

download_gme() gibt ein threading.Event zurück. Wenn der Aufrufer .set() darauf
aufruft, bricht der Download ab und done_cb wird mit (False, CANCEL_SENTINEL)
aufgerufen.

Verwendung:
    from tiptoi_gtk.backend.downloader import download_gme, CANCEL_SENTINEL

    cancel = download_gme(
        url="https://...",
        dest=Path("~/tiptoi-downloads/product.gme"),
        progress_cb=lambda fraction: progress_bar.set_fraction(fraction),
        done_cb=lambda ok, msg: handle_result(ok, msg),
        size_cb=lambda size: show_size(size),   # optional
    )
    # Abbrechen:
    cancel.set()
"""

import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable, Optional

from gi.repository import GLib

CHUNK_SIZE = 65_536  # 64 KiB

# Sentinel-Wert in done_cb result, wenn der Nutzer abgebrochen hat
CANCEL_SENTINEL = "__cancelled__"

_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
}


def download_gme(
    url: str,
    dest: Path,
    progress_cb: Callable[[float], None],
    done_cb: Callable[[bool, str], None],
    size_cb: Optional[Callable[[int], None]] = None,
) -> threading.Event:
    """
    Startet einen GME-Download in einem Hintergrundthread.

    Args:
        url: HTTPS-URL der .gme-Datei.
        dest: Zieldatei-Pfad.
        progress_cb: Wird mit einem Wert zwischen 0.0 und 1.0 aufgerufen.
                     Nur wenn Content-Length bekannt ist.
        done_cb: Wird mit (True, dest_str) bei Erfolg oder (False, error_msg)
                 bei Fehler/Abbruch aufgerufen. Bei Abbruch ist error_msg == CANCEL_SENTINEL.
        size_cb: Optional. Wird einmalig mit der Dateigröße in Bytes aufgerufen,
                 sobald der Content-Length-Header bekannt ist (0 = unbekannt).

    Returns:
        threading.Event – .set() darauf aufrufen, um den Download abzubrechen.
    """
    cancel_event = threading.Event()
    thread = threading.Thread(
        target=_download_worker,
        args=(url, dest, progress_cb, done_cb, size_cb, cancel_event),
        daemon=True,
    )
    thread.start()
    return cancel_event


def _download_worker(
    url: str,
    dest: Path,
    progress_cb: Callable[[float], None],
    done_cb: Callable[[bool, str], None],
    size_cb: Optional[Callable[[int], None]],
    cancel_event: threading.Event,
) -> None:
    """Läuft im Hintergrundthread."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")

    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=60) as response:
            total = int(response.headers.get("Content-Length", 0))
            if size_cb is not None:
                GLib.idle_add(size_cb, total)

            downloaded = 0
            with open(tmp, "wb") as out_file:
                while True:
                    if cancel_event.is_set():
                        break
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        GLib.idle_add(progress_cb, downloaded / total)

        if cancel_event.is_set():
            tmp.unlink(missing_ok=True)
            GLib.idle_add(done_cb, False, CANCEL_SENTINEL)
            return

        tmp.rename(dest)
        GLib.idle_add(done_cb, True, str(dest))

    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        GLib.idle_add(done_cb, False, f"HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        GLib.idle_add(done_cb, False, str(exc))
