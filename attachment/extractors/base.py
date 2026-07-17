"""Base extractor with shared Feishu docx API helpers."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import config
from feishu.http import feishu_request


class BaseExtractor:
    """Common Feishu API methods for attachment text/image extraction."""

    def __init__(self, token_manager):
        self.tm = token_manager

    @property
    def _token(self) -> str:
        return self.tm.get_token()

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def sanitize(text: str, max_len: int = 5000) -> str:
        if not text:
            return ""
        text = text.replace("\x00", "")
        cleaned = []
        for ch in text:
            cp = ord(ch)
            if cp < 32 and cp not in (9, 10, 13):
                continue
            cleaned.append(ch)
        text = "".join(cleaned)
        if len(text) > max_len:
            text = text[:max_len] + "..."
        return text.strip()

    def get_root_block_id(self, doc_token: str) -> Optional[str]:
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/blocks"
        resp = feishu_request("GET", url, headers=self._headers)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("code") != 0:
            return None

        items = data.get("data", {}).get("items", [])
        root = next((b for b in items if b.get("parent_id") == ""), None)
        if root:
            return root["block_id"]

        has_more = data.get("data", {}).get("has_more", False)
        page_token = data.get("data", {}).get("page_token", "")
        while has_more and page_token:
            resp = feishu_request(
                "GET",
                url,
                headers=self._headers,
                params={"page_token": page_token},
            )
            data = resp.json()
            if data.get("code") != 0:
                break
            items = data.get("data", {}).get("items", [])
            root = next((b for b in items if b.get("parent_id") == ""), None)
            if root:
                return root["block_id"]
            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token", "")
        return None

    def insert_image(
        self,
        doc_token: str,
        root_block_id: str,
        image_bytes: bytes,
        image_ext: str,
        img_size: int,
    ) -> None:
        url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents/"
            f"{doc_token}/blocks/{root_block_id}/children"
        )
        r = feishu_request(
            "POST",
            url,
            headers=self._headers,
            json={"children": [{"block_type": 27, "image": {}}]},
        )
        jr = r.json()
        if jr.get("code") != 0:
            print(f"    创建图块失败: {jr.get('msg', '')[:80]}")
            return
        bid = jr["data"]["children"][0]["block_id"]

        r = feishu_request(
            "POST",
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {self._token}"},
            files={"file": (f"img.{image_ext}", image_bytes, f"image/{image_ext}")},
            data={
                "file_name": f"img.{image_ext}",
                "parent_type": "docx_image",
                "parent_node": bid,
                "size": str(img_size),
            },
            timeout=config.FEISHU_DOWNLOAD_TIMEOUT,
        )
        ur = r.json()
        if ur.get("code") != 0:
            print(f"    上传失败: {ur.get('msg', '')[:80]}")
            return
        ftok = ur["data"]["file_token"]

        r = feishu_request(
            "PATCH",
            f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/blocks/{bid}",
            headers=self._headers,
            json={"replace_image": {"token": ftok}},
        )
        jr = r.json() if r.text else {}
        if jr.get("code") == 0:
            print("    图片 ✓")
        else:
            print(f"    PATCH失败: {jr.get('msg', '')[:80]}")

    def append_blocks(self, doc_token: str, blocks: List[Dict[str, Any]]) -> None:
        if not blocks:
            return
        root_id = self.get_root_block_id(doc_token)
        if not root_id:
            raise RuntimeError("无法获取文档根块 ID")
        for i in range(0, len(blocks), 10):
            batch = blocks[i : i + 10]
            url = (
                f"https://open.feishu.cn/open-apis/docx/v1/documents/"
                f"{doc_token}/blocks/{root_id}/children"
            )
            r = feishu_request(
                "POST",
                url,
                headers=self._headers,
                json={"children": batch},
            )
            jr = r.json() if r.text else {}
            if r.status_code == 200 and jr.get("code") == 0:
                print(f"    ✓ {len(batch)}块")
            else:
                msg = jr.get("msg", "")[:120]
                raise RuntimeError(f"写入 blocks 失败: {jr.get('code', '?')} {msg}")

    def download_file(self, file_token: str, save_path: str) -> None:
        url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
        resp = feishu_request(
            "GET",
            url,
            headers=self._headers,
            stream=True,
            timeout=config.FEISHU_DOWNLOAD_TIMEOUT,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"下载失败 HTTP {resp.status_code}")
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        if os.path.getsize(save_path) == 0:
            raise RuntimeError("文件大小为0")

    def extract(self, file_path: str, doc_token: str, root_block_id: str) -> None:
        raise NotImplementedError
