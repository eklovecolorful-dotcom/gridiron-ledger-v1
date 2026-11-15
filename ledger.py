#!/usr/bin/env python3
"""球場帳本 Gridiron Ledger — run `python3 ledger.py --help`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
