"""Remaster version and update source, in one place (docs/release.md).

VERSION is what REMASTER.txt, state.json, install.json, the credits and the uninstall entry show;
the launcher compares it with the tag of the latest GitHub release (vX.Y.Z).
UPDATE_REPO can be overridden per install in <game>/.raf-remaster/update.json ({"repo": "owner/name"}).
"""

VERSION = "1.0.6"
UPDATE_REPO = "VlexWest/raf-remaster"
