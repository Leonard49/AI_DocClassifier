"""
Extract PDF/Word/PPT attachments from Feishu wiki docx pages and paste text back.

Runs before document read/classify when ENABLE_ATTACHMENT_EXTRACT=true.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from attachment_extractors import PDFExtractor, PPTExtractor, WordExtractor
from feishu_http import feishu_request

logger = logging.getLogger(__name__)

SUPPORTED_ATTACHMENT_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}
EXT_TO_KIND = {
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".ppt": "ppt",
    ".pptx": "ppt",
}
ATTACHMENT_HEADING_PREFIX = "附件："
HEADING_BLOCK_TYPES = {3, 4, 5}
EXTRACTED_CONTENT_BLOCK_TYPES = {2, 27, 31, 32}


def load_failed_docs_from_report(report_path: str) -> List[Dict[str, Any]]:
    """Load documents with failed attachment files from a previous run report."""
    with open(report_path, encoding="utf-8") as f:
        data = json.load(f)

    docs: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for doc in data.get("documents", []):
        failed_files = [
            item for item in doc.get("files", []) if item.get("status") == "failed"
        ]
        if not failed_files:
            continue
        node_token = doc.get("node_token") or ""
        if not node_token or node_token in seen:
            continue
        seen.add(node_token)
        docs.append(
            {
                "node_token": node_token,
                "title": doc.get("title") or node_token,
                "source_path": doc.get("source_path") or "",
                "failed_files": [item["name"] for item in failed_files],
            }
        )
    return docs


def _block_heading_text(block: Dict[str, Any]) -> str:
    for key in ("heading1", "heading2", "heading3"):
        heading = block.get(key, {})
        parts = [
            el.get("text_run", {}).get("content", "")
            for el in heading.get("elements", [])
        ]
        text = "".join(parts).strip()
        if text:
            return text
    return ""


@dataclass
class AttachmentFileResult:
    name: str
    ext: str
    status: str  # extracted | skipped | failed
    error: Optional[str] = None


@dataclass
class AttachmentDocResult:
    title: str
    node_token: str
    obj_token: Optional[str] = None
    source_path: str = ""
    status: str = "none"  # none | extracted | skipped | partial | failed
    files: List[AttachmentFileResult] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AttachmentExtractStats:
    checked: int = 0
    with_attachments: int = 0
    no_attachments: int = 0
    documents_extracted: int = 0
    documents_skipped: int = 0
    documents_partial: int = 0
    documents_failed: int = 0
    files_total: int = 0
    files_extracted: int = 0
    files_skipped: int = 0
    files_failed: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "checked": self.checked,
            "with_attachments": self.with_attachments,
            "no_attachments": self.no_attachments,
            "documents_extracted": self.documents_extracted,
            "documents_skipped": self.documents_skipped,
            "documents_partial": self.documents_partial,
            "documents_failed": self.documents_failed,
            "files_total": self.files_total,
            "files_extracted": self.files_extracted,
            "files_skipped": self.files_skipped,
            "files_failed": self.files_failed,
        }


def _format_eta(elapsed: float, done: int, total: int) -> str:
    if done <= 0 or done >= total:
        return "—"
    remaining = elapsed / done * (total - done)
    if remaining >= 3600:
        return f"{remaining / 3600:.1f} 小时"
    return f"{remaining / 60:.1f} 分钟"


def _print_progress(
    done: int,
    total: int,
    stats: AttachmentExtractStats,
    start_time: datetime,
) -> None:
    elapsed = (datetime.now() - start_time).total_seconds()
    pct = (done / total * 100) if total else 0
    eta = _format_eta(elapsed, done, total)
    print(
        f"\r📎 附件提取: {done}/{total} ({pct:.1f}%) | "
        f"含附件文档 {stats.with_attachments} | "
        f"新提取文件 {stats.files_extracted} | "
        f"跳过 {stats.files_skipped} | "
        f"失败 {stats.files_failed} | "
        f"已用 {elapsed / 60:.1f} 分钟 | 预计剩余 {eta}",
        end="",
        flush=True,
    )


def save_attachment_report(
    results: List[AttachmentDocResult],
    stats: AttachmentExtractStats,
    log_dir: str,
) -> Optional[str]:
    """Persist attachment extraction summary to logs/attachment_extract.json."""
    docs_with_files = [r for r in results if r.files]
    if not docs_with_files and stats.files_extracted == 0 and stats.files_failed == 0:
        return None

    os.makedirs(log_dir, exist_ok=True)
    out_path = os.path.join(log_dir, "attachment_extract.json")
    payload = {
        "run_at": datetime.now().isoformat(),
        "stats": stats.to_dict(),
        "documents": [
            {
                "title": r.title,
                "node_token": r.node_token,
                "obj_token": r.obj_token,
                "source_path": r.source_path,
                "status": r.status,
                "error": r.error,
                "files": [
                    {
                        "name": f.name,
                        "ext": f.ext,
                        "status": f.status,
                        "error": f.error,
                    }
                    for f in r.files
                ],
            }
            for r in docs_with_files
        ],
        "failures": [
            {
                "title": r.title,
                "node_token": r.node_token,
                "source_path": r.source_path,
                "error": r.error,
                "failed_files": [f.name for f in r.files if f.status == "failed"],
            }
            for r in results
            if r.status in ("failed", "partial") or any(f.status == "failed" for f in r.files)
        ],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def print_attachment_summary(
    results: List[AttachmentDocResult],
    stats: AttachmentExtractStats,
) -> None:
    """Print human-readable attachment extraction summary."""
    if stats.checked == 0:
        return

    print(f"\n📎 附件提取汇总:")
    print(f"   - 检查文档: {stats.checked}")
    print(f"   - 无附件: {stats.no_attachments}")
    print(f"   - 含附件文档: {stats.with_attachments}")
    print(
        f"   - 文档状态: 新提取 {stats.documents_extracted} | "
        f"已全部跳过 {stats.documents_skipped} | "
        f"部分失败 {stats.documents_partial} | "
        f"失败 {stats.documents_failed}"
    )
    print(
        f"   - 附件文件: 共 {stats.files_total} | "
        f"新提取 {stats.files_extracted} | "
        f"已跳过 {stats.files_skipped} | "
        f"失败 {stats.files_failed}"
    )
    if stats.files_total:
        rate = stats.files_extracted / stats.files_total * 100
        print(f"   - 附件提取成功率: {rate:.1f}%")

    failures = [
        r for r in results
        if r.status in ("failed", "partial")
        or any(f.status == "failed" for f in r.files)
    ]
    if failures:
        print(f"\n📋 附件提取失败/部分失败: 共 {len(failures)} 篇")
        for item in failures[:20]:
            failed_names = [f.name for f in item.files if f.status == "failed"]
            print(f"   - {item.title}")
            if item.source_path:
                print(f"     路径: {item.source_path}")
            if failed_names:
                print(f"     失败附件: {', '.join(failed_names)}")
            if item.error:
                print(f"     原因: {item.error}")
        if len(failures) > 20:
            print(f"   ... 还有 {len(failures) - 20} 篇，详见 logs/attachment_extract.json")


class AttachmentExtractor:
    """Download supported attachments and append extracted text to source docx."""

    def __init__(self, token_manager):
        self.tm = token_manager
        self._extractors = {
            "pdf": PDFExtractor(token_manager),
            "word": WordExtractor(token_manager),
            "ppt": PPTExtractor(token_manager),
        }
        self._root_id_cache: Dict[str, str] = {}

    @property
    def _token(self) -> str:
        return self.tm.get_token()

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def process_documents(
        self,
        docs: List[Dict[str, Any]],
        *,
        progress_interval: int = 5,
    ) -> tuple[AttachmentExtractStats, List[AttachmentDocResult]]:
        stats = AttachmentExtractStats()
        results: List[AttachmentDocResult] = []
        total = len(docs)
        start_time = datetime.now()

        for idx, doc in enumerate(docs, 1):
            stats.checked += 1
            node_token = doc.get("node_token") or ""
            title = doc.get("title") or node_token
            source_path = doc.get("source_path") or ""

            if not node_token:
                continue

            try:
                doc_result = self.process_document(
                    node_token,
                    title=title,
                    source_path=source_path,
                )
            except Exception as exc:
                logger.exception("附件提取异常: %s", title)
                doc_result = AttachmentDocResult(
                    title=title,
                    node_token=node_token,
                    source_path=source_path,
                    status="failed",
                    error=str(exc),
                )
                print(f"\n❌ 附件提取异常: {title} — {exc}")

            results.append(doc_result)
            self._update_stats(stats, doc_result)

            if idx == 1 or idx == total or idx % progress_interval == 0:
                _print_progress(idx, total, stats, start_time)

        print()
        elapsed = (datetime.now() - start_time).total_seconds()
        print(
            f"📎 附件提取阶段完成: 检查 {stats.checked} 篇 | "
            f"含附件 {stats.with_attachments} 篇 | "
            f"新提取文件 {stats.files_extracted} | "
            f"耗时 {elapsed / 60:.1f} 分钟"
        )
        return stats, results

    @staticmethod
    def _update_stats(stats: AttachmentExtractStats, doc: AttachmentDocResult) -> None:
        if not doc.files:
            stats.no_attachments += 1
            return

        stats.with_attachments += 1
        stats.files_total += len(doc.files)
        for f in doc.files:
            if f.status == "extracted":
                stats.files_extracted += 1
            elif f.status == "skipped":
                stats.files_skipped += 1
            elif f.status == "failed":
                stats.files_failed += 1

        if doc.status == "extracted":
            stats.documents_extracted += 1
        elif doc.status == "skipped":
            stats.documents_skipped += 1
        elif doc.status == "partial":
            stats.documents_partial += 1
        elif doc.status == "failed":
            stats.documents_failed += 1

    def process_document(
        self,
        node_token: str,
        *,
        title: Optional[str] = None,
        source_path: str = "",
    ) -> AttachmentDocResult:
        label = title or node_token
        result = AttachmentDocResult(
            title=label,
            node_token=node_token,
            source_path=source_path,
        )

        doc_token = self._get_doc_token(node_token)
        if not doc_token:
            return result

        result.obj_token = doc_token
        attachments = self._list_attachments(doc_token)
        if not attachments:
            return result

        names = [a["name"] for a in attachments]
        print(f"\n📎 [{label}] 发现 {len(attachments)} 个附件: {names}")
        logger.info("发现附件 %s: %s", label, names)

        existing = self._list_existing_attachment_headings(doc_token)
        root_id = self._get_root_id(doc_token)
        if not root_id:
            result.status = "failed"
            result.error = "无法获取文档根块 ID"
            print(f"  ❌ {result.error}")
            logger.error("%s: %s", label, result.error)
            return result

        extracted_count = 0
        skipped_count = 0
        failed_count = 0

        for att in attachments:
            heading = f"{ATTACHMENT_HEADING_PREFIX}{att['name']}"
            if heading in existing:
                result.files.append(
                    AttachmentFileResult(att["name"], att["ext"], "skipped")
                )
                skipped_count += 1
                print(f"  ⏭️ 已提取，跳过: {att['name']}")
                continue

            file_result = self._process_one(doc_token, root_id, att)
            result.files.append(file_result)
            if file_result.status == "extracted":
                extracted_count += 1
            elif file_result.status == "failed":
                failed_count += 1

        if extracted_count and not failed_count and skipped_count < len(attachments):
            result.status = "extracted"
        elif extracted_count and failed_count:
            result.status = "partial"
            result.error = f"{failed_count} 个附件提取失败"
        elif skipped_count == len(attachments):
            result.status = "skipped"
        elif failed_count:
            result.status = "failed"
            result.error = "全部附件提取失败"

        return result

    def clear_orphan_attachment_headings(
        self,
        doc_token: str,
        failed_file_names: List[str],
    ) -> int:
        """Remove heading-only blocks left by previous failed extractions."""
        target_headings = {
            f"{ATTACHMENT_HEADING_PREFIX}{name}" for name in failed_file_names
        }
        if not target_headings:
            return 0

        children = self._list_root_children_ordered(doc_token)
        orphan_indexes: List[int] = []
        for index, block in enumerate(children):
            if block.get("block_type") not in HEADING_BLOCK_TYPES:
                continue
            heading = _block_heading_text(block)
            if heading not in target_headings:
                continue
            if self._is_orphan_attachment_heading(children, index, heading):
                orphan_indexes.append(index)

        deleted = 0
        for index in sorted(orphan_indexes, reverse=True):
            if self._delete_root_child_at(doc_token, index):
                deleted += 1
            else:
                logger.warning("删除空标题失败 doc=%s index=%s", doc_token, index)
        return deleted

    @staticmethod
    def _is_orphan_attachment_heading(
        children: List[Dict[str, Any]],
        index: int,
        heading_text: str,
    ) -> bool:
        if not heading_text.startswith(ATTACHMENT_HEADING_PREFIX):
            return False
        if index + 1 >= len(children):
            return True

        next_block = children[index + 1]
        next_type = next_block.get("block_type")
        if next_type in EXTRACTED_CONTENT_BLOCK_TYPES:
            return False
        if next_type in HEADING_BLOCK_TYPES:
            return True
        if next_type == 23:
            return True
        return True

    def _list_root_children_ordered(self, doc_token: str) -> List[Dict[str, Any]]:
        root_id = self._get_root_id(doc_token)
        if not root_id:
            return []

        url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents/"
            f"{doc_token}/blocks/{root_id}/children"
        )
        items: List[Dict[str, Any]] = []
        page_token = ""
        while True:
            params: Dict[str, Any] = {"document_revision_id": -1, "page_size": 500}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_request("GET", url, headers=self._headers, params=params)
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("获取子块失败 %s: %s", doc_token, data.get("msg"))
                break
            items.extend(data.get("data", {}).get("items", []))
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
            if not page_token:
                break
        return items

    def _delete_root_child_at(self, doc_token: str, index: int) -> bool:
        root_id = self._get_root_id(doc_token)
        if not root_id:
            return False
        url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents/"
            f"{doc_token}/blocks/{root_id}/children/batch_delete"
        )
        resp = feishu_request(
            "DELETE",
            url,
            headers=self._headers,
            params={"document_revision_id": -1},
            json={"start_index": index, "end_index": index + 1},
        )
        data = resp.json() if resp.text else {}
        return resp.status_code == 200 and data.get("code") == 0

    def _get_doc_token(self, node_token: str) -> Optional[str]:
        r = feishu_request(
            "GET",
            "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node",
            headers=self._headers,
            params={"token": node_token},
        )
        data = r.json()
        if data.get("code") != 0:
            msg = data.get("msg", "unknown")
            logger.warning("获取节点失败 %s: %s", node_token, msg)
            return None
        node = data.get("data", {}).get("node", {})
        if node.get("obj_type") != "docx":
            return None
        return node.get("obj_token")

    def _iter_blocks(self, doc_token: str) -> List[Dict[str, Any]]:
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/blocks"
        items: List[Dict[str, Any]] = []
        page_token = ""
        while True:
            params = {"page_token": page_token} if page_token else None
            r = feishu_request("GET", url, headers=self._headers, params=params)
            if r.status_code != 200:
                logger.warning("读取 blocks 失败 HTTP %s: %s", r.status_code, doc_token)
                break
            data = r.json()
            if data.get("code") != 0:
                logger.warning("读取 blocks 失败: %s", data.get("msg"))
                break
            items.extend(data.get("data", {}).get("items", []))
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
            if not page_token:
                break
        return items

    def _list_attachments(self, doc_token: str) -> List[Dict[str, str]]:
        attachments: List[Dict[str, str]] = []
        seen: Set[str] = set()
        for block in self._iter_blocks(doc_token):
            if block.get("block_type") != 23:
                continue
            fi = block.get("file", {})
            token = fi.get("token")
            name = fi.get("name", "")
            ext = name[name.rfind(".") :].lower() if "." in name else ""
            if token and ext in SUPPORTED_ATTACHMENT_EXTS and token not in seen:
                seen.add(token)
                attachments.append({"file_token": token, "name": name, "ext": ext})
        return attachments

    def _list_existing_attachment_headings(self, doc_token: str) -> Set[str]:
        headings: Set[str] = set()
        for block in self._iter_blocks(doc_token):
            if block.get("block_type") not in (3, 4, 5):
                continue
            for key in ("heading1", "heading2", "heading3"):
                heading = block.get(key, {})
                for el in heading.get("elements", []):
                    text = el.get("text_run", {}).get("content", "")
                    if text.startswith(ATTACHMENT_HEADING_PREFIX):
                        headings.add(text.strip())
        return headings

    def _get_root_id(self, doc_token: str) -> Optional[str]:
        if doc_token in self._root_id_cache:
            return self._root_id_cache[doc_token]
        root_id = self._extractors["pdf"].get_root_block_id(doc_token)
        if root_id:
            self._root_id_cache[doc_token] = root_id
        return root_id

    def _process_one(
        self, doc_token: str, root_id: str, att: Dict[str, str]
    ) -> AttachmentFileResult:
        ext = att["ext"]
        name = att["name"]
        kind = EXT_TO_KIND.get(ext)
        extractor = self._extractors.get(kind or "")
        if not extractor:
            return AttachmentFileResult(name, ext, "failed", error="不支持的格式")

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            local_path = tmp.name

        try:
            print(f"  ⬇️ 下载: {name}")
            extractor.download_file(att["file_token"], local_path)
            extractor.append_blocks(
                doc_token,
                [
                    {
                        "block_type": 3,
                        "heading1": {
                            "elements": [
                                {
                                    "text_run": {
                                        "content": f"{ATTACHMENT_HEADING_PREFIX}{name}"
                                    }
                                }
                            ]
                        },
                    }
                ],
            )
            extractor.extract(local_path, doc_token, root_id)
            print(f"  ✅ {name}")
            logger.info("附件提取成功: %s", name)
            return AttachmentFileResult(name, ext, "extracted")
        except Exception as e:
            msg = str(e)
            print(f"  ❌ {name}: {msg}")
            logger.warning("附件提取失败 %s: %s", name, msg)
            return AttachmentFileResult(name, ext, "failed", error=msg)
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)
