"""
Einfache Einstellungsverwaltung via JSON-Datei.

Einstellungen werden unter ~/.config/tiptoi-gtk/settings.json gespeichert.
"""

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".config" / "tiptoi-gtk" / "settings.json"

_DEFAULTS: dict[str, Any] = {
    "download_dir": str(Path.home() / "tiptoi-downloads"),
    "csv_max_age_days": 7,
    "csv_url": "https://cdn.ravensburger.de/db/tiptoi.csv",
}

_cache: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    global _cache
    if _cache:
        return _cache
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _cache = {**_DEFAULTS, **stored}
            return _cache
        except Exception:
            pass
    _cache = dict(_DEFAULTS)
    return _cache


def _save() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(_cache, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get(key: str) -> Any:
    return _load().get(key, _DEFAULTS.get(key))


def set_value(key: str, value: Any) -> None:
    _load()
    _cache[key] = value
    _save()


def download_dir() -> Path:
    return Path(get("download_dir"))


def set_download_dir(path: Path) -> None:
    set_value("download_dir", str(path))
