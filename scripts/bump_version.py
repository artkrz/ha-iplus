"""Bump the manifest version and its packaging mirrors without resolving dependencies."""
import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', help='Release version in X.Y.Z format')
    args = parser.parse_args()
    if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', args.version):
        parser.error('version must be X.Y.Z (non-negative integers without leading zeros)')
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / 'custom_components/iplus/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['version'] = args.version
    updates = {manifest_path: json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'}
    project = root / 'pyproject.toml'
    text, count = re.subn(r'(?ms)(^\[project\]\n.*?^version = ")[^"]+("$)',
                          lambda m: m[1] + args.version + m[2], project.read_text(), count=1)
    if count != 1:
        parser.error('could not find project version in pyproject.toml')
    updates[project] = text
    lock = root / 'uv.lock'
    if lock.exists():
        text, count = re.subn(r'(?m)(^name = "plus-balance"\nversion = ")[^"]+("$)',
                              lambda m: m[1] + args.version + m[2], lock.read_text())
        if count:
            updates[lock] = text
    for path, text in updates.items():
        path.write_text(text)


if __name__ == '__main__':
    main()
