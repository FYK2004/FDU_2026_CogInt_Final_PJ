"""Convert saved HTML evidence files into readable .txt next to them."""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_articles import strip_html  # noqa: E402


def main() -> None:
    paths = sys.argv[1:] or glob.glob("data/raw/articles/*.htm*")
    for path in paths:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = strip_html(fh.read())
        out = os.path.splitext(path)[0] + ".txt"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"{os.path.basename(path):32s} -> {len(text):7d} chars")


if __name__ == "__main__":
    main()
