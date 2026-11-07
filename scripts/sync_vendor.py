"""Synchronize the HA integration's vendored Plus client (run from any directory)."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
for source in (root / "plus_balance").glob("*.py"):
    if source.name != "__main__.py":
        shutil.copyfile(source, root / "custom_components/iplus/plus_balance" / source.name)
