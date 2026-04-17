"""
Lädt und cached die Ravensburger Produktliste (CSV) und bietet eine Suchfunktion.

Caching-Strategie:
    Die CSV wird unter ~/.cache/tiptoi-gtk/produkte.csv gespeichert und nach
    MAX_AGE_DAYS Tagen automatisch neu heruntergeladen. Bei Netzwerkfehlern wird
    die gecachte Version weiter verwendet, solange sie vorhanden ist.

CSV-Format (aktuell, kommagetrennt):
    Zeile 1: Firmware-Metadaten-Header  (wird übersprungen)
    Zeile 2: Firmware-Versions-Daten    (wird übersprungen)
    Zeile 3: Produkt-Header: Items._id, Items._version, Items._url, Items._fileName
    Zeile 4+: Produkt-Daten
        [0] Items._id       – numerische Produkt-ID (entspricht der Artikelnummer)
        [1] Items._version  – Version (wird ignoriert)
        [2] Items._url      – Download-URL der .gme-Datei
        [3] Items._fileName – Dateiname ohne Extension (Unterstriche statt Leerzeichen)

    Hinweis: Die CSV enthält keinen lesbaren Produktnamen mehr. Als Anzeigename
    wird der _fileName-Wert verwendet, wobei Unterstriche durch Leerzeichen ersetzt
    werden.
"""

import csv
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from tiptoi_gtk.model.product import Product
from tiptoi_gtk.backend import settings_manager as settings

CACHE_PATH = Path.home() / ".cache" / "tiptoi-gtk" / "produkte.csv"
CSV_URL = "https://cdn.ravensburger.de/db/tiptoi.csv"  # Fallback / Anzeige-Default
MAX_AGE_DAYS = 7

_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
}

# Header-Wert, der die Produktdaten-Sektion einleitet
_PRODUCTS_HEADER_START = "Items._id"


def _is_cache_fresh() -> bool:
    """Gibt True zurück, wenn der Cache existiert und nicht älter als MAX_AGE_DAYS ist."""
    if not CACHE_PATH.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
    return age < timedelta(days=MAX_AGE_DAYS)


def _filename_to_name(filename: str) -> str:
    """Wandelt einen CSV-Dateinamen in einen lesbaren Produktnamen um."""
    return filename.replace("_", " ").strip()


def fetch_catalog(
    force: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    Lädt die CSV von Ravensburger herunter, falls der Cache veraltet oder nicht
    vorhanden ist.

    Args:
        force: Erzwingt den Download, auch wenn der Cache noch frisch ist.
        progress_cb: Optionaler Callback für Statusmeldungen (läuft im Hintergrundthread).

    Returns:
        Fehlermeldung als String oder None bei Erfolg.
    """
    if not force and _is_cache_fresh():
        return None

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CACHE_PATH.with_suffix(".tmp")

    if progress_cb:
        progress_cb("Produktliste wird heruntergeladen…")

    try:
        url = settings.get("csv_url") or CSV_URL
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as response:
            tmp_path.write_bytes(response.read())
        tmp_path.rename(CACHE_PATH)
        return None
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        if CACHE_PATH.exists():
            # Gecachte Version weiter verwenden
            return None
        return str(exc)


def load_products() -> tuple[list[Product], Optional[str]]:
    """
    Liest alle Produkte aus dem lokalen CSV-Cache.

    Das neue CSV-Format hat einen Zwei-Abschnitt-Aufbau: Zuerst Firmware-Metadaten,
    dann ab der Zeile mit 'Items._id' die eigentlichen Produktdaten.

    Returns:
        Tupel aus (Produktliste, Fehlermeldung). Bei Erfolg ist der Fehler None.
    """
    if not CACHE_PATH.exists():
        return [], "Produktliste nicht vorhanden. Bitte Internetverbindung prüfen."

    products: list[Product] = []

    try:
        with open(CACHE_PATH, encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            in_products_section = False

            for row in reader:
                if not row:
                    continue

                # Auf den Produkt-Header warten
                if not in_products_section:
                    if row[0].strip() == _PRODUCTS_HEADER_START:
                        in_products_section = True
                    continue

                # Produkt-Zeile: id, version, url, filename
                if len(row) < 4:
                    continue

                product_id = row[0].strip().strip('"')
                version = row[1].strip().strip('"')
                url = row[2].strip().strip('"')
                filename = row[3].strip().strip('"')

                # Nur echte Produkt-IDs (numerisch, nicht leer)
                if not product_id or not product_id.isdigit():
                    continue

                # Dateiname als Anzeigename aufbereiten
                name = _filename_to_name(filename) if filename else f"Produkt {product_id}"

                # Nur GME-Dateien
                if url and not url.lower().endswith(".gme"):
                    continue

                products.append(Product(product_id, name, url, version_date=version))

    except Exception as exc:
        return [], str(exc)

    return products, None


def fetch_and_load(
    force: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[list[Product], Optional[str]]:
    """
    Kombinierter Aufruf: erst fetch_catalog(), dann load_products().
    Für den Einsatz in Hintergrundthreads gedacht.
    """
    error = fetch_catalog(force=force, progress_cb=progress_cb)
    if error:
        return [], error
    return load_products()


def search_products(query: str, products: list[Product]) -> list[Product]:
    """
    Durchsucht die Produktliste nach Name oder ID (case-insensitiv).
    Leerer Query gibt alle Produkte zurück.

    Returns:
        Gefilterte Liste.
    """
    q = query.lower().strip()
    if not q:
        return list(products)
    return [
        p for p in products
        if q in p.name.lower() or q in p.artikelnummer
    ]


def available_years(products: list[Product]) -> list[int]:
    """Gibt die sortierte Liste aller Jahre zurück, für die Produkte existieren."""
    return sorted({p.year for p in products if p.year is not None})


def catalog_age_days() -> Optional[float]:
    """Gibt das Alter des CSV-Caches in Tagen zurück, oder None wenn nicht vorhanden."""
    if not CACHE_PATH.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
    return age.total_seconds() / 86400
