"""Pytest config: add bench/v2/scripts to sys.path so the test files can
import the harness modules whether pytest is run from the repo root or
from inside `bench/v2/`."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent / "scripts"
for p in (_SCRIPTS, _SCRIPTS.parent.parent.parent):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
