"""PDF attachment extractor."""

from __future__ import annotations

import fitz

from attachment.images import pixmap_from_pdf_xref

from .base import BaseExtractor


class PDFExtractor(BaseExtractor):
    """Extract text and images from PDF attachments into docx blocks."""

    def extract(self, pdf_path: str, doc_token: str, root_block_id: str) -> None:
        items = self._extract_items(pdf_path)
        if not items:
            return

        text_buf = []
        for _y, item_type, data in items:
            if item_type == "text":
                clean = self.sanitize(data)
                if clean:
                    text_buf.append(
                        {
                            "block_type": 2,
                            "text": {"elements": [{"text_run": {"content": clean}}]},
                        }
                    )
            elif item_type == "image":
                if text_buf:
                    self.append_blocks(doc_token, text_buf)
                    text_buf = []
                self.insert_image(
                    doc_token,
                    root_block_id,
                    data["image_bytes"],
                    data["image_ext"],
                )
            elif item_type == "page_sep":
                if text_buf:
                    self.append_blocks(doc_token, text_buf)
                    text_buf = []
                self.append_blocks(
                    doc_token,
                    [
                        {
                            "block_type": 5,
                            "heading3": {
                                "elements": [
                                    {"text_run": {"content": f"—— 第 {data} 页 ——"}}
                                ]
                            },
                        }
                    ],
                )
        if text_buf:
            self.append_blocks(doc_token, text_buf)

    def _extract_items(self, pdf_path: str):
        items = []
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            pi = []

            for tb in page.get_text("blocks"):
                if len(tb) >= 7 and tb[6] == 0:
                    text = tb[4].strip()
                    if text:
                        pi.append((tb[1], "text", text))

            images = page.get_images(full=True)
            mask_xrefs = {img[1] for img in images if img[1]}
            for img in images:
                xref = img[0]
                if xref in mask_xrefs:
                    continue
                y0 = 0
                try:
                    rects = page.get_image_rects(xref)
                    if rects:
                        y0 = rects[0].y0 if hasattr(rects[0], "y0") else rects[0][1]
                except Exception:
                    try:
                        bbox = page.get_image_bbox(img)
                        y0 = bbox.y0 if hasattr(bbox, "y0") else bbox[1]
                    except Exception:
                        pass
                converted = pixmap_from_pdf_xref(doc, xref)
                if converted:
                    image_bytes, image_ext = converted
                else:
                    try:
                        base_image = doc.extract_image(xref)
                    except Exception:
                        continue
                    image_bytes = base_image.get("image") or b""
                    image_ext = base_image.get("ext") or "png"
                if not image_bytes:
                    continue
                pi.append(
                    (
                        y0,
                        "image",
                        {
                            "image_bytes": image_bytes,
                            "image_ext": image_ext,
                        },
                    )
                )

            if pi:
                pi.sort(key=lambda x: x[0])
                items.extend(pi)
                items.append((999999, "page_sep", page_num + 1))
        doc.close()
        return items
