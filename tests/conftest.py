"""Shared pytest setup.

Adds the repo root to `sys.path` so `import backend.*` works regardless of how
pytest is invoked, and forces PROTOTYPE_MODE for tests so nothing tries to hit
real Circle/Phala/Polymarket APIs.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("PROTOTYPE_MODE", "true")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("CIRCLE_API_KEY", "")
os.environ.setdefault("PHALA_CLOUD_API_KEY", "")
