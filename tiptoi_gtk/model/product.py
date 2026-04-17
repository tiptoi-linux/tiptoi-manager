"""
Datenmodell für ein TipToi-Produkt.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Product:
    """Repräsentiert ein einzelnes TipToi-Produkt aus der Ravensburger-Produktliste."""

    artikelnummer: str
    name: str
    download_url: str
    version_date: str = field(default="")  # Format: YYYYMMDD

    @property
    def year(self) -> Optional[int]:
        """Gibt das Jahr der letzten GME-Aktualisierung zurück, oder None."""
        if self.version_date and len(self.version_date) >= 4:
            try:
                return int(self.version_date[:4])
            except ValueError:
                pass
        return None

    def __str__(self) -> str:
        return f"{self.name} ({self.artikelnummer})"
