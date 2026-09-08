"""Render the status page to a static HTML file (Phase 3 evidence / preview).

Usage:
    python -m statuspack.render_status --out evidence/phase3/status.html
"""

from __future__ import annotations

import argparse
from pathlib import Path

from statuspack.app import render_status_page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="evidence/phase3/status.html")
    parser.add_argument("--db", default="statuspack.db")
    args = parser.parse_args(argv)
    html = render_status_page(args.db)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"Wrote {out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
