"""Normalize extracted images into formats Feishu Docx can render."""

from __future__ import annotations

from typing import Optional, Tuple

import fitz

# Feishu Docx image blocks reliably render JPEG/PNG. GIF/WEBP/BMP/CMYK/JPX/EMF often 裂图.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MIN_SIDE_PX = 2
MAX_SIDE_PX = 4096
MAX_DISPLAY_WIDTH = 800

_MIME = {
    "jpeg": "image/jpeg",
    "png": "image/png",
}


def image_mime(ext: str) -> str:
    key = (ext or "").lower().lstrip(".")
    if key == "jpg":
        key = "jpeg"
    return _MIME.get(key, "image/png")


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
    attempts.extend(["jpeg", "png", "gif", "bmp", "tiff", "webp", "jpx", "jp2", "emf", "wmf"])
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


def _render_page_to_feishu(page: fitz.Page) -> Tuple[bytes, str]:
    pix = page.get_pixmap(alpha=True)
    try:
        if max(pix.width, pix.height) > MAX_SIDE_PX:
            scale = MAX_SIDE_PX / float(max(pix.width, pix.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
        return _pixmap_to_feishu(pix)
    finally:
        pix = None


def display_size(width: int, height: int) -> Tuple[int, int]:
    w = int(width or 0)
    h = int(height or 0)
    if w < MIN_SIDE_PX or h < MIN_SIDE_PX:
        return MAX_DISPLAY_WIDTH, int(MAX_DISPLAY_WIDTH * 0.75)
    if w > MAX_DISPLAY_WIDTH:
        h = max(1, int(h * MAX_DISPLAY_WIDTH / w))
        w = MAX_DISPLAY_WIDTH
    return w, h


def probe_image_size(image_bytes: bytes, image_ext: str = "") -> Tuple[int, int]:
    try:
        img = _open_with_fitz(image_bytes, image_ext)
        try:
            rect = img[0].rect
            return max(1, int(rect.width)), max(1, int(rect.height))
        finally:
            img.close()
    except Exception:
        return MAX_DISPLAY_WIDTH, int(MAX_DISPLAY_WIDTH * 0.75)


def pixmap_from_pdf_xref(doc: fitz.Document, xref: int) -> Optional[Tuple[bytes, str]]:
    """Render a PDF image XObject to JPEG/PNG. None if it should be skipped."""
    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception:
        return None
    try:
        if max(pix.width, pix.height) > MAX_SIDE_PX:
            scale = MAX_SIDE_PX / float(max(pix.width, pix.height))
            pix = fitz.Pixmap(pix, fitz.Matrix(scale, scale))
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

    Keep RGB JPEG/PNG under size cap; convert CMYK / GIF / WEBP / BMP / JPX / EMF.
    """
    if not image_bytes:
        raise ValueError("empty image")
    ext = canonical_ext(image_ext)

    if _is_jpeg(image_bytes) or _is_png(image_bytes):
        kind = "jpeg" if _is_jpeg(image_bytes) else "png"
        try:
            img = fitz.open(stream=image_bytes, filetype=kind)
            try:
                pix = img[0].get_pixmap(alpha=True)
                cmyk = pix.n - pix.alpha > 3
                too_big = max(pix.width, pix.height) > MAX_SIDE_PX
                if cmyk or too_big:
                    return _render_page_to_feishu(img[0])
            finally:
                img.close()
        except Exception:
            pass
        return image_bytes, kind

    img = _open_with_fitz(image_bytes, ext)
    try:
        return _render_page_to_feishu(img[0])
    finally:
        img.close()
