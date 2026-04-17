"""
HTTP-Download-Logik für GME-Dateien.

Downloads laufen immer in einem Daemon-Thread, um den GTK-Hauptthread nicht zu
blockieren. Fortschritts- und Fertig-Callbacks werden über GLib.idle_add() sicher
in den GTK-Hauptthread zurückgerufen.

Verwendung:
    from tiptoi_gtk.backend.downloader import download_gme

    download_gme(
        url="https://...",
        dest=Path("~/tiptoi-downloads/product.gme"),
        progress_cb=lambda fraction: progress_bar.set_fraction(fraction),
        done_cb=lambda ok, msg: handle_result(ok, msg),
    )
"""

import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable

from gi.repository import GLib

CHUNK_SIZE = 65_536  # 64 KiB


def download_gme(
    url: str,
    dest: Path,
    progress_cb: Callable[[float], None],
    done_cb: Callable[[bool, str], None],
) -> None:
    """
    Startet einen GME-Download in einem Hintergrundthread.

    Der Download wird zunächst in eine temporäre Datei (<dest>.tmp) geschrieben und
    erst nach erfolgreichem Abschluss umbenannt, damit keine unvollständigen Dateien
    im Zielverzeichnis landen.

    Args:
        url: HTTPS-URL der .gme-Datei.
        dest: Zieldatei-Pfad (wird nach dem Download angelegt).
        progress_cb: Wird mit einem Wert zwischen 0.0 und 1.0 aufgerufen.
                     Läuft im GTK-Hauptthread (via GLib.idle_add).
        done_cb: Wird mit (True, dest_str) bei Erfolg oder (False, error_msg)
                 bei Fehler aufgerufen. Läuft im GTK-Hauptthread.
    """
    thread = threading.Thread(
        target=_download_worker,
        args=(url, dest, progress_cb, done_cb),
        daemon=True,
    )
    thread.start()


def _download_worker(
    url: str,
    dest: Path,
    progress_cb: Callable[[float], None],
    done_cb: Callable[[bool, str], None],
) -> None:
    """Läuft im Hintergrundthread."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "tiptoi-gtk/0.1 (Linux; GTK4)"},
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0

            with open(tmp, "wb") as out_file:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        GLib.idle_add(progress_cb, downloaded / total)

        tmp.rename(dest)
        GLib.idle_add(done_cb, True, str(dest))

    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        GLib.idle_add(done_cb, False, f"HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        GLib.idle_add(done_cb, False, str(exc))
