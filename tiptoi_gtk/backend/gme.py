"""
Dateioperationen für GME-Dateien auf dem TipToi-Stift.

Alle Funktionen sind synchron und sollten aus dem GTK-Hauptthread aufgerufen werden,
da die Operationen schnell sind (lokales Kopieren auf FAT-Volume). Bei sehr großen
Dateien (>100 MB) wäre eine asynchrone Variante via threading sinnvoll – dies ist
für Phase 2 vorgesehen.
"""

import shutil
from pathlib import Path
from typing import Optional


def list_gme_files(pen_path: str) -> list[Path]:
    """
    Listet alle .gme-Dateien im Root-Verzeichnis des Stifts auf.

    Die Suche ist case-insensitiv (.GME und .gme werden beide gefunden).

    Returns:
        Alphabetisch sortierte Liste von Path-Objekten.
    """
    root = Path(pen_path)
    files = [p for p in root.iterdir() if p.suffix.lower() == ".gme"]
    return sorted(files, key=lambda p: p.name.lower())


def copy_to_pen(source: Path, pen_path: str) -> Optional[str]:
    """
    Kopiert eine lokale .gme-Datei auf den Stift.

    Verwendet shutil.copy2, um auch Datei-Metadaten zu erhalten.
    Wenn die Datei auf dem Stift bereits vorhanden ist, wird sie überschrieben.

    Args:
        source: Quelldatei (lokal).
        pen_path: Mount-Punkt des Stifts.

    Returns:
        Fehlermeldung als String oder None bei Erfolg.
    """
    dest = Path(pen_path) / source.name
    try:
        shutil.copy2(source, dest)
        return None
    except PermissionError:
        return "Keine Schreibrechte auf dem Stift. Ist der Stift schreibgeschützt?"
    except OSError as exc:
        return str(exc)


def delete_from_pen(gme_path: Path) -> Optional[str]:
    """
    Löscht eine .gme-Datei vom Stift.

    Args:
        gme_path: Absoluter Pfad zur Datei auf dem Stift.

    Returns:
        Fehlermeldung als String oder None bei Erfolg.
    """
    try:
        gme_path.unlink()
        return None
    except PermissionError:
        return "Keine Schreibrechte. Ist der Stift schreibgeschützt?"
    except OSError as exc:
        return str(exc)


def pen_disk_info(pen_path: str) -> tuple[int, int]:
    """
    Gibt Speicherplatz-Informationen des Stifts zurück.

    Returns:
        Tupel (free_bytes, total_bytes). Bei Fehler (0, 0).
    """
    try:
        usage = shutil.disk_usage(pen_path)
        return usage.free, usage.total
    except OSError:
        return 0, 0


def format_size(size_bytes: int) -> str:
    """Formatiert eine Byte-Anzahl in eine lesbare Größenangabe (MB oder GB)."""
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    return f"{size_bytes / 1_048_576:.0f} MB"
