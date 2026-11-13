"""Put the add-on shell and the vendored coach package on sys.path."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "core" / "src", ROOT / "app"):
    text = str(entry)
    if text not in sys.path:
        sys.path.insert(0, text)
