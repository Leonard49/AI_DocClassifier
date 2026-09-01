"""Normalize extracted images into formats Feishu Docx can render."""

from __future__ import annotations

from typing import Optional, Tuple

import fitz

# Feishu Docx image blocks reliably render these; PDF/Word often emit jpx/emf/wmf.
FEISHU_IMAGE_EXTS = {"jpeg", "png", "gif", "webp", "bmp"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MIN_SIDE_PX = 2

_MIME = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


def image_mime(ext: str) -> str:
    key = (ext or "").lower().lstrip(".")
    if key == "jpg":
        key = "jpeg"
    return _MIME.get(key, f"image/{key or 'png'}")


def canonical_ext(image_ext: str) -> str:
    ext = (image_ext or "").lower().lstrip(".")
    if "/" in ext:
        ext = ext.rsplit("/", 1)[-1]
    if ext in ("jpg", "jpe"):
        return "jpeg"
    return ext


def _is_jpeg(data: bytes) -> bool:
    return len(data) >= 3 and data[:2] == b"\xff\xd8"


def _is_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def _open_with_fitz(image_bytes: bytes, image_ext: str) -> fitz.Document:
    ext = canonical_ext(image_ext)
    attempts = []
    if ext:
        attempts.append(ext)
    attempts.extend(["jpeg", "png", "gif", "bmp", "tiff", "webp"])
    seen = set()
    last_exc: Optional[BaseException] = None
    for kind in attempts:
        if kind in seen:
            continue
        seen.add(kind)
        try:
            return fitz.open(stream=image_bytes, filetype=kind)
        except Exception as exc:
            last_exc = exc
    try:
        return fitz.open(stream=image_bytes)
    except Exception:
        if last_exc:
            raise last_exc
        raise


def _pixmap_to_feishu(pix: fitz.Pixmap) -> Tuple[bytes, str]:
    if pix.n - pix.alpha > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if pix.width < MIN_SIDE_PX or pix.height < MIN_SIDE_PX:
        raise ValueError(f"image too small: {pix.width}x{pix.height}")
    if pix.alpha:
        return pix.tobytes("png"), "png"
    return pix.tobytes("jpeg"), "jpeg"


def pixmap_from_pdf_xref(doc: fitz.Document, xref: int) -> Optional[Tuple[bytes, str]]:
    """Render a PDF image XObject to JPEG/PNG. None if it should be skipped."""
    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception:
        return None
    try:
        return _pixmap_to_feishu(pix)
    except Exception:
        return None
    finally:
        pix = None


def normalize_image_bytes(
    image_bytes: bytes,
    image_ext: str = "",
) -> Tuple[bytes, str]:
    """
    Return (bytes, ext) that Feishu image blocks can display.

    Keep already-valid JPEG/PNG; convert PDF JPEG2000 / Office WMF / etc.
    """
    if not image_bytes:
        raise ValueError("empty image")
    ext = canonical_ext(image_ext)
    if _is_jpeg(image_bytes):
        return image_bytes, "jpeg"
    if _is_png(image_bytes):
        return image_bytes, "png"
    if ext in FEISHU_IMAGE_EXTS and ext not in ("jpeg", "png"):
        return image_bytes, ext

    img = _open_with_fitz(image_bytes, ext)
    try:
        page = img[0]
        pix = page.get_pixmap(alpha=True)
        return _pixmap_to_feishu(pix)
    finally:
        img.close()
