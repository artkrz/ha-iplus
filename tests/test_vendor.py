from pathlib import Path


def test_vendored_library_matches():
    root = Path(__file__).resolve().parents[1]
    sources = {p.name: p.read_bytes() for p in (root / "plus_balance").glob("*.py")
               if p.name != "__main__.py"}
    vendored = {p.name: p.read_bytes() for p in
                (root / "custom_components/iplus/plus_balance").glob("*.py")}
    assert sources == vendored
