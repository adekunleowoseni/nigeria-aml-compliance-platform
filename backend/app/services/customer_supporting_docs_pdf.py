"""Merge customer KYC / AOP uploads into a single PDF bundle."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import List, Tuple

from pypdf import PdfReader, PdfWriter


def _customer_name_slug(customer_name: str) -> str:
    base = (customer_name or "").strip() or "Customer"
    parts: List[str] = []
    for p in re.split(r"\s+", base):
        clean = re.sub(r"[^\w-]", "", p, flags=re.UNICODE)
        if clean:
            parts.append(clean)
    slug = "-".join(x.title() for x in parts)[:80] or "Customer"
    safe = "".join(c if c.isascii() and c not in '\\/:*?"<>|' else "-" for c in slug)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "Customer"


def supporting_bundle_download_filename(customer_name: str, *, variant: str = "full") -> str:
    """
    Download filename from display name.

    ``variant``:
    - ``full`` — all uploads merged (legacy / admin archive).
    - ``otc_estr_supporting`` — profile-change + cash-threshold evidence only (OTC ESTR).
    - ``aop_package`` — account opening package file uploads only.
    """
    safe = _customer_name_slug(customer_name)
    if variant == "otc_estr_supporting":
        return f"{safe}-otc-estr-supporting.pdf"
    if variant == "aop_package":
        return f"{safe}-aop-package.pdf"
    return f"{safe}-supporting-doc.pdf"


def _placeholder_pdf_page(title: str, body_lines: List[str]) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        buf = BytesIO()
        writer.write(buf)
        return buf.getvalue()

    w, h = 595, 842
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
        font_small = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
        font_small = font
    y = 48
    draw.text((48, y), title[:200], fill=(20, 20, 20), font=font)
    y += 36
    for line in body_lines:
        draw.text((48, y), line[:120], fill=(40, 40, 40), font=font_small)
        y += 22
        if y > h - 48:
            break
    buf = BytesIO()
    img.save(buf, format="PDF", resolution=72.0)
    return buf.getvalue()


def _image_bytes_to_pdf(data: bytes) -> bytes:
    from PIL import Image

    im = Image.open(BytesIO(data))
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")
    max_dim = 2200
    w, h = im.size
    if max(w, h) > max_dim:
        ratio = max_dim / float(max(w, h))
        im = im.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="PDF", resolution=100.0)
    return buf.getvalue()


def _append_pdf_bytes(writer: PdfWriter, pdf_bytes: bytes) -> None:
    reader = PdfReader(BytesIO(pdf_bytes))
    for page in reader.pages:
        writer.add_page(page)


def merge_customer_files_to_pdf(
    items: List[Tuple[Path, str]],
    *,
    customer_display_name: str,
) -> bytes:
    """
    ``items`` is ordered ``(path, logical_filename)`` for each on-disk upload.
    Embeds PDFs and raster images; inserts a placeholder page for Word docs.
    """
    writer = PdfWriter()
    if not items:
        b = _placeholder_pdf_page(
            "No supporting documents",
            [
                f"No files are on file for {customer_display_name or 'this customer'}.",
                "Upload documents on the Customers page, then download this bundle again.",
            ],
        )
        _append_pdf_bytes(writer, b)
    else:
        for path, logical_name in items:
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if suffix == ".pdf":
                try:
                    _append_pdf_bytes(writer, raw)
                except Exception:
                    b = _placeholder_pdf_page(
                        "Could not read PDF",
                        [logical_name[:180], "This file is skipped; download it separately."],
                    )
                    _append_pdf_bytes(writer, b)
            elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
                try:
                    img_pdf = _image_bytes_to_pdf(raw)
                    _append_pdf_bytes(writer, img_pdf)
                except Exception:
                    b = _placeholder_pdf_page(
                        "Could not embed image",
                        [logical_name[:180], "This file is skipped; download it separately."],
                    )
                    _append_pdf_bytes(writer, b)
            elif suffix in (".doc", ".docx"):
                b = _placeholder_pdf_page(
                    "Word document (not embedded)",
                    [
                        logical_name[:180],
                        "Download the original .doc / .docx from the Customers page.",
                    ],
                )
                _append_pdf_bytes(writer, b)
            else:
                b = _placeholder_pdf_page(
                    "Unsupported format",
                    [logical_name[:180], "Download the original file from the Customers page."],
                )
                _append_pdf_bytes(writer, b)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
