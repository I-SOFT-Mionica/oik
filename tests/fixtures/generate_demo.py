"""Thin CLI wrapper around biracki_odbor.core.demo_data.generate_all.

Run from the repo root:
    python tests/fixtures/generate_demo.py

Outputs five demo files to tests/fixtures/demo/.
See demo_data.py for the full scenario description and data.
"""

from pathlib import Path

from biracki_odbor.core.demo_data import generate_all

OUT_DIR = Path(__file__).resolve().parent / "demo"

if __name__ == "__main__":
    print(f"Generating demo fixtures -> {OUT_DIR}")
    for p in generate_all(OUT_DIR):
        print(f"  OK {p.name}")
    print("Done.")
