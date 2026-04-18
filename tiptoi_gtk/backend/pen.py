"""
TipToi-Stifterkennung via GIO VolumeMonitor.

Erkennungsstrategie (Reihenfolge):
    1. GIO VolumeMonitor (Ereignisse mount-added / mount-removed)
    2. Scan aller bereits gemounteten Volumes beim Start (scan_existing_mounts)
    3. Manuell: Der Nutzer gibt den Mount-Punkt direkt an (set_manual_path)

Ein gemountetes Laufwerk gilt als TipToi-Stift, wenn im Root-Verzeichnis
mindestens eines dieser Kriterien erfüllt ist:
    • Eine Datei mit der Endung .gme oder .GME existiert
    • Eine Datei mit der Endung .key existiert (z. B. .tiptoi.key)
    • Ein Unterordner namens "system" oder "gmefile" vorhanden ist

Callbacks erhalten (label, path) – label ist der Anzeigename des Laufwerks
(z. B. "TIPTOI"), path der Mount-Pfad (z. B. "/run/media/user/TIPTOI").
Beide Callbacks laufen im GTK-Hauptthread (via GLib.idle_add).
"""

from typing import Callable, Optional

from gi.repository import Gio, GLib


def _is_tiptoi_root(root: Gio.File) -> bool:
    """Prüft, ob das Root-Verzeichnis eines Mounts wie ein TipToi-Stift aussieht."""
    try:
        enumerator = root.enumerate_children(
            "standard::name,standard::type",
            Gio.FileQueryInfoFlags.NONE,
            None,
        )
        for info in enumerator:
            name = info.get_name().lower()
            if name.endswith(".gme") or name.endswith(".key"):
                enumerator.close(None)
                return True
            if name in ("system", "gmefile"):
                enumerator.close(None)
                return True
        enumerator.close(None)
    except GLib.Error:
        pass
    return False


class PenMonitor:
    """
    Überwacht USB-Mounts und erkennt TipToi-Stifte über den GIO VolumeMonitor.

    Die Callbacks erhalten (label: str, path: str), wobei label der Anzeigename
    des Laufwerks ist (z. B. "TIPTOI") und path der Mount-Pfad.

    Beispiel:
        monitor = PenMonitor(
            on_connected=lambda label, path: print(f"Stift: {label} @ {path}"),
            on_disconnected=lambda label, path: print("Stift getrennt"),
        )
        existing = monitor.scan_existing_mounts()
        if existing:
            label, path = existing
    """

    def __init__(
        self,
        on_connected: Callable[[str, str], None],
        on_disconnected: Callable[[str, str], None],
    ) -> None:
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._current_path: Optional[str] = None

        self._volume_monitor = Gio.VolumeMonitor.get()
        self._volume_monitor.connect("mount-added", self._on_mount_added)
        self._volume_monitor.connect("mount-removed", self._on_mount_removed)

    # ── Öffentliche API ────────────────────────────────────────────────────────

    def scan_existing_mounts(self) -> Optional[tuple[str, str]]:
        """
        Durchsucht beim Start alle bereits gemounteten Volumes nach einem Stift.

        Returns:
            (label, path) des gefundenen Stifts oder None.
        """
        for mount in self._volume_monitor.get_mounts():
            root = mount.get_root()
            if root and _is_tiptoi_root(root):
                path = root.get_path()
                if path:
                    label = mount.get_name() or path
                    self._current_path = path
                    return label, path
        return None

    def set_manual_path(self, path: str) -> None:
        """
        Setzt den Stift-Pfad manuell (Fallback, wenn automatische Erkennung fehlschlägt).
        Löst den on_connected-Callback aus.
        """
        self._current_path = path
        GLib.idle_add(self._on_connected, path, path)

    @property
    def current_path(self) -> Optional[str]:
        """Aktuell verbundener Stift-Pfad oder None."""
        return self._current_path

    @property
    def is_connected(self) -> bool:
        """True wenn ein Stift verbunden ist."""
        return self._current_path is not None

    # ── Interne Callbacks ──────────────────────────────────────────────────────

    def _on_mount_added(self, _monitor: Gio.VolumeMonitor, mount: Gio.Mount) -> None:
        root = mount.get_root()
        if not root:
            return
        if _is_tiptoi_root(root):
            path = root.get_path()
            if path:
                label = mount.get_name() or path
                self._current_path = path
                GLib.idle_add(self._on_connected, label, path)

    def _on_mount_removed(self, _monitor: Gio.VolumeMonitor, mount: Gio.Mount) -> None:
        root = mount.get_root()
        if not root:
            return
        path = root.get_path()
        if path and path == self._current_path:
            label = mount.get_name() or path
            self._current_path = None
            GLib.idle_add(self._on_disconnected, label, path)
