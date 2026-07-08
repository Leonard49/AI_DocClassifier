"""Convert legacy Office formats (.doc / .ppt) for python-docx / python-pptx."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional

# Word: wdFormatXMLDocument = 16
# PowerPoint: ppSaveAsOpenXMLPresentation = 24
_SOFFICE_TARGETS = {
    ".doc": "docx",
    ".ppt": "pptx",
}


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


def _convert_with_soffice(source_path: str, out_dir: str, target_ext: str) -> str:
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError("未找到 LibreOffice (soffice)")

    result = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            target_ext,
            "--outdir",
            out_dir,
            source_path,
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"LibreOffice 转换失败: {stderr[:200]}")

    base = os.path.splitext(os.path.basename(source_path))[0]
    converted = os.path.join(out_dir, f"{base}.{target_ext}")
    if not os.path.isfile(converted):
        raise RuntimeError(f"LibreOffice 转换后未找到 .{target_ext} 文件")
    return converted


def _convert_doc_with_word_com(doc_path: str, out_dir: str) -> str:
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


def _convert_ppt_with_powerpoint_com(ppt_path: str, out_dir: str) -> str:
    ppt_path = os.path.abspath(ppt_path)
    out_dir = os.path.abspath(out_dir)
    base = os.path.splitext(os.path.basename(ppt_path))[0]
    pptx_path = os.path.join(out_dir, f"{base}.pptx")

    ps = f"""
$ErrorActionPreference = 'Stop'
$ppt = New-Object -ComObject PowerPoint.Application
$ppt.Visible = [Microsoft.Office.Core.MsoTriState]::msoFalse
try {{
    $pres = $ppt.Presentations.Open('{ppt_path.replace("'", "''")}', $true, $true, $false)
    try {{
        $pres.SaveAs('{pptx_path.replace("'", "''")}', 24)
    }} finally {{
        $pres.Close()
    }}
}} finally {{
    $ppt.Quit()
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
        raise RuntimeError(f"PowerPoint COM 转换失败: {stderr[:200]}")
    if not os.path.isfile(pptx_path):
        raise RuntimeError("PowerPoint COM 转换后未找到 .pptx 文件")
    return pptx_path


def _convert_legacy(source_path: str, source_ext: str) -> str:
    if not source_path.lower().endswith(source_ext):
        raise ValueError(f"不是 {source_ext} 文件: {source_path}")
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)

    target_ext = _SOFFICE_TARGETS[source_ext]
    out_dir = tempfile.mkdtemp(prefix=f"{source_ext.strip('.')}_convert_")
    errors: list[str] = []

    if _find_soffice():
        try:
            return _convert_with_soffice(source_path, out_dir, target_ext)
        except Exception as exc:
            errors.append(f"LibreOffice: {exc}")

    if os.name == "nt":
        try:
            if source_ext == ".doc":
                return _convert_doc_with_word_com(source_path, out_dir)
            return _convert_ppt_with_powerpoint_com(source_path, out_dir)
        except Exception as exc:
            label = "Word COM" if source_ext == ".doc" else "PowerPoint COM"
            errors.append(f"{label}: {exc}")

    if source_ext == ".doc":
        hint = "请安装 LibreOffice，或在本机安装 Microsoft Word"
    else:
        hint = "请安装 LibreOffice，或在本机安装 Microsoft PowerPoint"
    detail = "; ".join(errors) if errors else "无可用转换器"
    raise RuntimeError(f"{source_ext} 转换失败 ({detail})。{hint}")


def convert_doc_to_docx(doc_path: str) -> str:
    """Convert .doc to .docx in a temp directory."""
    return _convert_legacy(doc_path, ".doc")


def convert_ppt_to_pptx(ppt_path: str) -> str:
    """Convert .ppt to .pptx in a temp directory."""
    return _convert_legacy(ppt_path, ".ppt")
