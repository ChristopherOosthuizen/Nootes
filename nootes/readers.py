"""File content extraction for various formats."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

MARKDOWN_EXTS = {".md", ".markdown", ".txt", ".rst"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = MARKDOWN_EXTS | IMAGE_EXTS | DOCX_EXTS | PDF_EXTS

MAX_CHARS = 100_000


@dataclass
class ExtractedContent:
    """Result of extracting content from a file."""

    text: str = ""
    images: list[str] = field(default_factory=list)  # base64-encoded images
    needs_map_reduce: bool = False  # True if content exceeded MAX_CHARS
    is_visual: bool = False  # True if content is image-based (needs vision API)


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() in PDF_EXTS


def read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())


def read_pdf_as_images(path: Path) -> list[str]:
    """Render each PDF page as an image and return base64-encoded PNGs."""
    import fitz

    images: list[str] = []
    with fitz.open(str(path)) as pdf:
        for page in pdf:
            # Render at 150 DPI for good quality without being too large
            pix = page.get_pixmap(dpi=150)
            png_bytes = pix.tobytes("png")
            b64 = base64.b64encode(png_bytes).decode("ascii")
            images.append(b64)
    return images


def read_pdf_text(path: Path) -> str:
    """Extract text from PDF as fallback."""
    import fitz

    parts: list[str] = []
    with fitz.open(str(path)) as pdf:
        for page in pdf:
            parts.append(page.get_text())
    return "\n\n".join(parts)


def read_image(path: Path) -> str:
    """Load an image file and return base64-encoded data."""
    raw = path.read_bytes()
    return base64.b64encode(raw).decode("ascii")


def _image_media_type(path: Path) -> str:
    """Get the media type string for an image file."""
    ext = path.suffix.lower()
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }
    return mapping.get(ext, "image/png")


def extract_content(path: Path) -> ExtractedContent:
    """Extract content from a file for categorization.

    Returns an ExtractedContent with text and/or images.
    If text exceeds 100K chars, sets needs_map_reduce=True.
    """
    suffix = path.suffix.lower()

    if suffix in IMAGE_EXTS:
        b64 = read_image(path)
        return ExtractedContent(
            text=f"[Image file] Filename: {path.stem}",
            images=[b64],
            is_visual=True,
        )

    if suffix in PDF_EXTS:
        images = read_pdf_as_images(path)
        # Also extract text for potential map-reduce on large PDFs
        text = read_pdf_text(path)
        return ExtractedContent(
            text=text,
            images=images,
            is_visual=True,
            needs_map_reduce=len(text) > MAX_CHARS,
        )

    if suffix in MARKDOWN_EXTS:
        text = read_markdown(path)
    elif suffix in DOCX_EXTS:
        text = read_docx(path)
    else:
        text = f"[Unsupported file type: {suffix}] Filename: {path.stem}"

    return ExtractedContent(
        text=text,
        needs_map_reduce=len(text) > MAX_CHARS,
    )
