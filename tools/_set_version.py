"""Update `__version__` in `biracki_odbor/__init__.py` for semantic-release.

Called via the `@semantic-release/exec` plugin from `.releaserc.json` as:

    python tools/_set_version.py ${nextRelease.version}

semantic-release computes the next version from commit messages; this
script writes that version into the Python package so the running app's
About page and the in-app updater report it correctly.

Kept deliberately tiny — no dependencies beyond stdlib so it runs in
the same env semantic-release uses on CI.
"""

from __future__ import annotations

import pathlib
import re
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: _set_version.py <new-version>", file=sys.stderr)
        return 2
    new_version = sys.argv[1].strip()
    if not new_version:
        print("empty version", file=sys.stderr)
        return 2

    target = pathlib.Path(__file__).resolve().parent.parent / "biracki_odbor" / "__init__.py"
    content = target.read_text(encoding="utf-8")
    new_content, count = re.subn(
        r'__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
        content,
    )
    if count != 1:
        print(
            f"expected exactly one __version__ assignment, found {count}",
            file=sys.stderr,
        )
        return 1
    target.write_text(new_content, encoding="utf-8")
    print(f'updated {target.relative_to(target.parent.parent)}: __version__ = "{new_version}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
