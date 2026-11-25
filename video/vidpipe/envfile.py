"""Minimal .env loader (no dependency). Values are put into os.environ and never printed or logged."""
import os
from pathlib import Path

from .util import PKG_DIR, ROOT_DIR


def candidates():
    return [Path.cwd() / ".env", ROOT_DIR / ".env", PKG_DIR / ".env"]


def load_dotenv(paths=None, override=False):
    """Load KEY=VALUE lines. Existing environment variables win unless override=True.
    Returns the list of variable NAMES that were set (never the values)."""
    names = []
    for p in paths or candidates():
        p = Path(p)
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            elif " #" in v:
                v = v.split(" #", 1)[0].rstrip()
            if k and (override or k not in os.environ):
                os.environ[k] = v
                names.append(k)
    return names
