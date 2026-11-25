#!/usr/bin/env python3
"""Extract chapter pages from a PDF into a --pages directory (one pNNN.txt per PDF page).

    python scripts/extract_pages.py --pdf book.pdf --pages 64-69 --out examples/x/pages
    python scripts/extract_pages.py --pdf book.pdf --find "ГАММА-ИЗЛУЧЕНИЯ"     # locate a section

Uses `pdftotext` (poppler) when available, otherwise pypdf. Page numbers are PDF page indices (1-based);
cite these numbers in node.json claims so the truth gate can find the quote on pNNN.txt.
"""
import argparse
import os
import shutil
import subprocess
import sys


def page_text(pdf, n):
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), "-enc", "UTF-8", pdf, "-"],
                           capture_output=True, text=True, check=True)
        return r.stdout
    from pypdf import PdfReader  # fallback
    return PdfReader(pdf).pages[n - 1].extract_text() or ""


def n_pages(pdf):
    if shutil.which("pdfinfo"):
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    from pypdf import PdfReader
    return len(PdfReader(pdf).pages)


def parse_range(s):
    pages = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return pages


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages", help="e.g. 64-69 or 12,14-16")
    ap.add_argument("--out", help="output directory for pNNN.txt")
    ap.add_argument("--find", help="print PDF pages whose text contains this string (case-insensitive)")
    a = ap.parse_args(argv)

    if a.find:
        needle = a.find.lower()
        for n in range(1, n_pages(a.pdf) + 1):
            t = page_text(a.pdf, n)
            if needle in t.lower():
                line = next(l for l in t.splitlines() if needle in l.lower())
                print(f"p{n:03d}: {line.strip()[:100]}")
        return 0
    if not (a.pages and a.out):
        ap.error("--pages and --out are required unless --find is used")
    os.makedirs(a.out, exist_ok=True)
    for n in parse_range(a.pages):
        path = os.path.join(a.out, f"p{n:03d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page_text(a.pdf, n))
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
