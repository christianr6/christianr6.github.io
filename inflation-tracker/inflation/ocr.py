"""Read a receipt photo into a draft list of items and prices.

OCR on receipts is unreliable: thermal paper fades, and stores abbreviate
names ("LG EGGS 12CT"). So this returns a DRAFT for a person to correct and
to add quantities to. It needs the Tesseract program installed
(https://tesseract-ocr.github.io/); the rest of the project does not.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_PRICE = re.compile(r"^(?P<name>.*?[A-Za-z].*?)\s+\$?(?P<price>\d{1,4}[.,]\d{2})\s*[A-Z]{0,2}$")
_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_NOT_ITEMS = ("total", "subtotal", "tax", "change", "cash", "visa", "mastercard", "debit", "credit",
              "balance", "tender", "savings", "discount", "coupon", "amount", "payment", "card")


class OcrUnavailable(RuntimeError):
    pass


def image_to_text(path: str | Path) -> str:
    if shutil.which("tesseract") is None:
        raise OcrUnavailable("Tesseract is not installed. Install it, or enter the receipt by hand.")
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "6"], capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise OcrUnavailable(f"Tesseract could not read the image: {result.stderr.strip()[:200]}")
    return result.stdout


def parse(text: str) -> dict:
    """Receipt text -> {"date": "YYYY-MM-DD" or None, "lines": [{"item", "price"}]}.

    Keeps lines that end in a price and are not totals, tax or payment lines.
    """
    date = None
    found = _DATE.search(text)
    if found:
        month, day, year = (int(part) for part in found.groups())
        year += 2000 if year < 100 else 0
        if 1 <= month <= 12 and 1 <= day <= 31:
            date = f"{year:04d}-{month:02d}-{day:02d}"
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"[^A-Za-z0-9]+$", "", raw.strip())    # OCR often leaves stray marks at the line end
        hit = _PRICE.match(line)
        if not hit:
            continue
        name = re.sub(r"\s{2,}", " ", hit["name"]).strip(" .:-")
        if any(word in name.lower() for word in _NOT_ITEMS) or len(name) < 2:
            continue
        lines.append({"item": name, "price": float(hit["price"].replace(",", "."))})
    return {"date": date, "lines": lines}


def read_receipt(path: str | Path) -> dict:
    return parse(image_to_text(path))
