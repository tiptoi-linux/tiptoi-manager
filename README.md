# TipToi Manager

> Nativer GNOME-Manager für TipToi®-Stifte unter Linux

**Stack:** Python 3.11 · GTK 4 · libadwaita  
**Plattform:** Linux (primär Fedora / GNOME)

---

## Motivation

Der offizielle Ravensburger TipToi® Manager ist nur für Windows und macOS verfügbar.
**TipToi Manager** schließt diese Lücke mit einer nativen GNOME-Anwendung, die sich
nahtlos in den Desktop integriert und ohne Terminal-Kenntnisse bedienbar ist.

---

## Funktionsumfang

| Funktion | Status |
|---|:---:|
| Produktliste von Ravensburger laden & cachen | ✅ |
| Suche nach Name oder Artikelnummer | ✅ |
| Filter nach Erscheinungsjahr | ✅ |
| GME-Datei herunterladen (mit Fortschrittsbalken) | ✅ |
| Direkt auf Stift herunterladen (1-Klick) | ✅ |
| TipToi-Stift automatisch erkennen (GIO VolumeMonitor) | ✅ |
| Installierte Produkte auf dem Stift anzeigen | ✅ |
| Produkt vom Stift löschen (mit Bestätigungsdialog) | ✅ |
| Datei aus Download-Ordner auf Stift kopieren | ✅ |
| Einstellungen (Download-Ordner, Cache-Dauer, CSV-URL) | ✅ |
| About-Dialog | ✅ |

---

## Screenshots

> *(folgen)*

---

## Installation

### Systemabhängigkeiten

```bash
# Fedora
sudo dnf install python3-gobject gtk4 libadwaita

# Ubuntu / Debian
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

### App starten (Entwicklungsmodus)

```bash
git clone https://github.com/example/tiptoi-manager
cd tiptoi-manager
python -m tiptoi_gtk.main
```

### Installation per pip

```bash
pip install -e . --user
tiptoi-gtk
```

---

## Projektstruktur

```
tiptoi-manager/
├── tiptoi_gtk/
│   ├── main.py                  # Einstiegspunkt
│   ├── application.py           # Adw.Application-Subklasse
│   ├── window.py                # Hauptfenster (alle 3 Views)
│   ├── backend/
│   │   ├── catalog.py           # CSV laden, cachen, suchen, Jahresfilter
│   │   ├── downloader.py        # HTTP-Download (threaded, Fortschritt)
│   │   ├── gme.py               # GME-Dateioperationen (kopieren, löschen)
│   │   ├── pen.py               # Stifterkennung via GIO VolumeMonitor
│   │   └── settings_manager.py  # JSON-Einstellungen (~/.config/tiptoi-gtk/)
│   └── model/
│       └── product.py           # Produkt-Datenklasse
├── tests/
│   ├── test_catalog.py
│   └── test_pen.py
├── pyproject.toml
└── README.md
```

---

## UI-Übersicht

```
┌──────────────────────────────────────────────────────────┐
│  [Suchen]        [Stift]        [Downloads]    [≡ Menü]  │  ← AdwHeaderBar
├──────────────────────────────────────────────────────────┤
│  ▶  Stift verbunden: /run/media/user/TIPTOI  [Anzeigen]  │  ← AdwBanner
├──────────────────────────────────────────────────────────┤
│                                                          │
│  View „Suchen":                                          │
│  ┌─ Suchfeld ──────────────────────────────────────────┐ │
│  │  🔍  Produktname oder Artikelnummer…                │ │
│  └─────────────────────────────────────────────────────┘ │
│  Jahr: [Alle Jahre ▾]                                    │
│  ████████████░░░░  63 %  ← Fortschrittsbalken            │
│  274 Produkte                                            │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Weltatlas · 2022               Nr. 32911  [🖊] [↓] │ │
│  │  Erste Zahlen · 2021            Nr. 41801  [🖊] [↓] │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  View „Stift":  Pfad · Speicher · installierte GME-Files │
│  View „Downloads":  lokale Dateien · auf Stift kopieren  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Navigation ausschließlich über die **Header-Leiste** (kein unteres Tab-Bar).

---

## Architektur

### Asynchrones Modell

Alle Netzwerk- und I/O-Operationen laufen in Daemon-Threads. UI-Updates werden
ausschließlich über `GLib.idle_add()` im GTK-Hauptthread durchgeführt:

```
[GTK-Hauptthread]              [Hintergrundthread]
        │                               │
        │── download_gme() ───────────▶ │  urllib.urlopen(...)
        │                               │  chunk loop
        │◀── GLib.idle_add() ──────────│  progress_cb(0.42)
        │   progress_bar.set(0.42)      │
        │                               │
        │◀── GLib.idle_add() ──────────│  done_cb(True, path)
        │   show_toast("Fertig")        │
```

### Datenspeicherung

| Pfad | Inhalt |
|---|---|
| `~/.cache/tiptoi-gtk/produkte.csv` | Ravensburger Produktliste (7-Tage-Cache) |
| `~/.config/tiptoi-gtk/settings.json` | Einstellungen (Download-Ordner, CSV-URL, …) |
| `~/tiptoi-downloads/` | Heruntergeladene GME-Dateien (Standard) |

### Stifterkennung

1. **GIO VolumeMonitor** – reagiert auf `mount-added` / `mount-removed`
2. **Scan beim Start** – prüft bereits gemountete Volumes via `scan_existing_mounts()`

Ein Mount gilt als TipToi-Stift, wenn im Root-Verzeichnis `.gme`-, `.key`-Dateien
oder ein `system/`-Ordner vorhanden sind.

---

## Roadmap

### Abgeschlossen ✅
- Produktliste laden, cachen, durchsuchen (Name & Artikelnummer)
- Jahresfilter (basiert auf `_version`-Spalte der CSV)
- GME-Download mit Fortschrittsbalken
- 1-Klick „Herunterladen + auf Stift kopieren"
- Stifterkennung via GIO VolumeMonitor
- Produkte auf dem Stift anzeigen & löschen (mit Bestätigungsdialog)
- Einstellungsfenster (Download-Ordner, Cache-Gültigkeit, CSV-URL)
- About-Dialog

### Geplant
- `.desktop`-Datei & App-Icon (SVG)
- udev-Regel für automatischen Start beim Einstecken
- Flatpak-Manifest & Flathub-Einreichung
- Lokalisierung (gettext / i18n)

---

## Referenzen

- [GNOME Human Interface Guidelines](https://developer.gnome.org/hig/)
- [libadwaita Dokumentation](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/)
- [PyGObject Dokumentation](https://pygobject.gnome.org/)
- [tip-toi-reveng (tttool)](https://github.com/entropia/tip-toi-reveng)
