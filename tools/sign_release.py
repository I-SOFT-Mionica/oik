"""Write the signed release manifest (CI, after building the installers).

    python tools/sign_release.py --tag v0.103.0 --out dist/release-manifest.json \
        dist/OIK_Setup.exe dist/Formalizator_Setup.exe

The Ed25519 seed comes from the RELEASE_SIGNING_KEY environment variable
(a GitHub Actions secret). Missing key = failed build: an unsigned
release would be refused by every updated client anyway.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from biracki_odbor import release_manifest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("files", nargs="+", type=Path)
    args = ap.parse_args()

    seed = os.environ.get("RELEASE_SIGNING_KEY", "").strip()
    if not seed:
        print("RELEASE_SIGNING_KEY is not set", file=sys.stderr)
        return 1
    manifest = release_manifest.build(args.tag, args.files, seed)
    # Prove it verifies with the public key the app ships, before publishing.
    release_manifest.parse(json.dumps(manifest).encode("utf-8"))
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name, entry in manifest["files"].items():
        print(f"{name}  {entry['sha256']}  {entry['size']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
