"""Word (.doc / .docx) attachment extractor."""

from __future__ import annotations

import os
import shutil

from .base import BaseExtractor
from .office_convert import convert_doc_to_docx


class WordExtractor(BaseExtractor):
    """Extract text and images from Word attachments into docx blocks."""

    def extract(self, docx_path: str, doc_token: str, root_block_id: str) -> None:
        try:
            from docx import Document
        except ImportError as e:
            print(f"    缺少依赖: {e}")
            self.append_blocks(
                doc_token, [self._placeholder("请安装: pip install python-docx lxml")]
            )
            return

        convert_dir: str | None = None
        source_path = docx_path
        if docx_path.lower().endswith(".doc"):
            print("    转换 .doc → .docx ...")
            source_path = convert_doc_to_docx(docx_path)
            convert_dir = os.path.dirname(source_path)

        try:
            self._extract_docx(source_path, doc_token, root_block_id, Document)
        finally:
            if convert_dir and os.path.isdir(convert_dir):
                shutil.rmtree(convert_dir, ignore_errors=True)

    def _extract_docx(
        self, docx_path: str, doc_token: str, root_block_id: str, document_cls
    ) -> None:
        doc = document_cls(docx_path)
        ns_w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

        image_cache = {}
        for rel_id, rel in doc.part.rels.items():
            if "image" not in rel.reltype:
                continue
            if getattr(rel, "is_external", False):
                continue
            try:
                blob = rel.target_part.blob
                ext = rel.target_part.partname.split(".")[-1]
            except AttributeError:
                continue
            image_cache[rel_id] = (blob, ext)

        blocks: list = []
        body = doc.element.body

        for child in body:
            if child.tag == f"{{{ns_w}}}p":
                drawings = child.findall(f".//{{{ns_w}}}drawing")
                imgs_found = False
                for drawing in drawings:
                    for blip in drawing.findall(f".//{{{ns_a}}}blip"):
                        embed = blip.get(f"{{{ns_r}}}embed")
                        if embed and embed in image_cache:
                            blob, ext = image_cache[embed]
                            if blocks:
                                self.append_blocks(doc_token, blocks)
                                blocks = []
                            self.insert_image(doc_token, root_block_id, blob, ext)
                            imgs_found = True

                if not imgs_found:
                    text = ""
                    for para in doc.paragraphs:
                        if para._element is child:
                            text = para.text.strip()
                            break
                    if text:
                        blocks.append(
                            {
                                "block_type": 2,
                                "text": {
                                    "elements": [
                                        {"text_run": {"content": self.sanitize(text)}}
                                    ]
                                },
                            }
                        )

            elif child.tag == f"{{{ns_w}}}tbl":
                if blocks:
                    self.append_blocks(doc_token, blocks)
                    blocks = []
                for row in child.findall(f".//{{{ns_w}}}tr"):
                    cells = row.findall(f".//{{{ns_w}}}tc")
                    row_texts = []
                    for cell in cells:
                        paras = cell.findall(f".//{{{ns_w}}}p")
                        ct = " ".join("".join(p.itertext()).strip() for p in paras)
                        if ct:
                            row_texts.append(ct)
                    if row_texts:
                        blocks.append(
                            {
                                "block_type": 2,
                                "text": {
                                    "elements": [
                                        {
                                            "text_run": {
                                                "content": self.sanitize(
                                                    " | ".join(row_texts)
                                                )
                                            }
                                        }
                                    ]
                                },
                            }
                        )

        if blocks:
            self.append_blocks(doc_token, blocks)

    @staticmethod
    def _placeholder(msg: str):
        return {
            "block_type": 2,
            "text": {
                "elements": [
                    {
                        "text_run": {
                            "content": f"📎 {msg}",
                            "text_element_style": {"text_color": 4},
                        }
                    }
                ]
            },
        }
