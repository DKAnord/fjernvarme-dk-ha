"""Test path setup for the kmd_easy_energy custom component."""

from __future__ import annotations

import sys
from pathlib import Path

# Import Home Assistant first so it can alias voluptuous before the
# integration modules import it (mirrors the real HA start-up order).
import homeassistant  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "custom_components"
if str(CC) not in sys.path:
    sys.path.insert(0, str(CC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
