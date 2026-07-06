"""Convert legacy Word .doc files to .docx for python-docx extraction."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional


def _find_soffice() -> Optional[str]:
    env_path = os.getenv("SOFFICE_PATH", "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    which = shutil.which("soffice")
    if which:
        return which

    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _convert_with_soffice(doc_path: str, out_dir: str) -> str:
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError("未找到 LibreOffice (soffice)")

    result = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            out_dir,
            doc_path,
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"LibreOffice 转换失败: {stderr[:200]}")

    base = os.path.splitext(os.path.basename(doc_path))[0]
    docx_path = os.path.join(out_dir, f"{base}.docx")
    if not os.path.isfile(docx_path):
        raise RuntimeError("LibreOffice 转换后未找到 .docx 文件")
    return docx_path


def _convert_with_word_com(doc_path: str, out_dir: str) -> str:
    doc_path = os.path.abspath(doc_path)
    out_dir = os.path.abspath(out_dir)
    base = os.path.splitext(os.path.basename(doc_path))[0]
    docx_path = os.path.join(out_dir, f"{base}.docx")

    ps = f"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {{
    $doc = $word.Documents.Open('{doc_path.replace("'", "''")}')
    try {{
        $doc.SaveAs2([ref]'{docx_path.replace("'", "''")}', [ref]16)
    }} finally {{
        $doc.Close()
    }}
}} finally {{
    $word.Quit()
}}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Word COM 转换失败: {stderr[:200]}")
    if not os.path.isfile(docx_path):
        raise RuntimeError("Word COM 转换后未找到 .docx 文件")
    return docx_path


def convert_doc_to_docx(doc_path: str) -> str:
    """
    Convert .doc to .docx in a temp directory.
    Returns path to the converted .docx (caller should delete parent temp dir).
    """
    if not doc_path.lower().endswith(".doc"):
        raise ValueError(f"不是 .doc 文件: {doc_path}")
    if not os.path.isfile(doc_path):
        raise FileNotFoundError(doc_path)

    out_dir = tempfile.mkdtemp(prefix="doc_convert_")
    errors: list[str] = []

    soffice = _find_soffice()
    if soffice:
        try:
            return _convert_with_soffice(doc_path, out_dir)
        except Exception as exc:
            errors.append(f"LibreOffice: {exc}")

    if os.name == "nt":
        try:
            return _convert_with_word_com(doc_path, out_dir)
        except Exception as exc:
            errors.append(f"Word COM: {exc}")

    hint = "请安装 LibreOffice，或在本机安装 Microsoft Word"
    detail = "; ".join(errors) if errors else "无可用转换器"
    raise RuntimeError(f".doc 转换失败 ({detail})。{hint}")
