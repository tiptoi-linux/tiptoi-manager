"""
Einstiegspunkt für tiptoi-gtk.

Wird über den pyproject.toml-Script-Eintrag aufgerufen:
    tiptoi-gtk = "tiptoi_gtk.main:main"

Kann auch direkt gestartet werden:
    python -m tiptoi_gtk.main
"""

import sys


def main() -> int:
    from tiptoi_gtk.application import TiptoiApplication

    app = TiptoiApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
