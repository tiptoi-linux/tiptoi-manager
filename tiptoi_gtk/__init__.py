import gettext
import os

_LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")
gettext.bindtextdomain("tiptoi-gtk", _LOCALE_DIR)
gettext.textdomain("tiptoi-gtk")

# Exportiert als _ für alle Submodule
_ = gettext.gettext
ngettext = gettext.ngettext
