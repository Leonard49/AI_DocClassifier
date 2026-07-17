"""Quectel module / project-name → product-line mapping (QT-SOP-PM-048E V12)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# Product lines that exist as tag1 in LABEL_TREE
PRODUCT_LINES = (
    "Cellular",
    "Automotive",
    "Smart",
    "ShortRange",
    "GNSS",
    "Satellite",
    "Antenna",
    "QuecOpen",
)

# Ordered rules: more specific families first.
# Derived from QT-SOP-PM-048E project-name product-line letters and common FAE titles.
_MODULE_FAMILY_RULES: Sequence[Tuple[str, str, int]] = (
    # Automotive (A + package letter + digits…); common AG35 / AG52x / AG59x
    (r"\bAG\d{2,4}[A-Z0-9\-]*\b", "Automotive", 12),
    (r"\bAM\d{2,4}[A-Z0-9\-]*\b", "Automotive", 10),
    # Smart: S + performance letter + series (SC20 / SC200 / SG368 / SP800…)
    (r"\bS[CEPH]\d{2,4}[A-Z0-9\-]*\b", "Smart", 12),
    # Satellite: C product line (CC660 / CC950…)
    (r"\bCC\d{2,4}[A-Z0-9\-]*\b", "Satellite", 12),
    # GNSS: L + package (LC29 / LG69 / LS200 / L89 / L76…)
    (r"\bL[CGUSAML]\d{2,4}[A-Z0-9\-]*\b", "GNSS", 11),
    (r"\bL[789]\d[A-Z0-9\-]*\b", "GNSS", 10),
    (r"\bLUA\d{3}[A-Z0-9\-]*\b", "GNSS", 10),
    # ShortRange: F/H/K product lines (FC41 / FCM360 / HC25 / KC…)
    (r"\bF[CGMLSAPX]\w{0,2}\d{2,4}[A-Z0-9\-]*\b", "ShortRange", 11),
    (r"\bH[CGMLSAP]\w{0,2}\d{2,4}[A-Z0-9\-]*\b", "ShortRange", 11),
    (r"\bK[CGMLSAP]\w{0,2}\d{2,4}[A-Z0-9\-]*\b", "ShortRange", 10),
    # Cellular classic families (exclude AG/SC/CC already matched)
    (
        r"\b(?:EC|EG|BG|BC|RG|RM|EM|UC|UG|MC|MG|RC|EG91|EG95|EG25|"
        r"EC25|EC21|BG95|BG96|BC95|BC660|RG500|RM500|RG520)\d{0,3}[A-Z0-9\-]*\b",
        "Cellular",
        10,
    ),
    (r"\b(?:EC|EG|BG|BC|RG|RM|EM|UC|UG)\d{2,4}[A-Z0-9\-]*\b", "Cellular", 9),
)

# Keyword fallbacks when no module PN is found
_KEYWORD_LINE_HINTS: Sequence[Tuple[str, str]] = (
    (r"\bquecopen\b|\bopen\s*linux\b|\brt?\.?os\b", "QuecOpen"),
    (r"\byocto\b|\bandroid\b|\bbsp\b|\bsc20\b|\bsc200\b", "Smart"),
    (r"\bv2x\b|\becall\b|\bng-?ecall\b|\bautomotive\b|\b车载\b", "Automotive"),
    (r"\bgnss\b|\bgps\b|\brtk\b|\bqgnss\b", "GNSS"),
    (r"\bwifi\b|\bwi-?fi\b|\bbluetooth\b|\bzigbee\b|\blora\b|\buwb\b|\bmatter\b", "ShortRange"),
    (r"\bntn\b|\bsatellite\b|\bstarlink\b|\bd2c\b", "Satellite"),
    (r"\bantenna\b|\b天线\b", "Antenna"),
    (r"\blte\b|\b5g\b|\bnb-?iot\b|\bcat\.?\s*m\b|\bqmi\b|\bmbim\b|\bat\+cfun\b", "Cellular"),
)


@dataclass(frozen=True)
class ModuleHit:
    token: str
    product_line: str
    weight: int
    source: str  # title | content | keyword


def _find_module_hits(text: str, source: str, title_boost: int = 0) -> List[ModuleHit]:
    if not text:
        return []
    hits: List[ModuleHit] = []
    seen = set()
    for pattern, line, base_w in _MODULE_FAMILY_RULES:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            token = match.group(0)
            key = token.upper()
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                ModuleHit(
                    token=token,
                    product_line=line,
                    weight=base_w + title_boost,
                    source=source,
                )
            )
    return hits


def extract_module_mentions(
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> List[ModuleHit]:
    """Collect module / project-name hits from title (boosted) and content."""
    hits: List[ModuleHit] = []
    hits.extend(_find_module_hits(title or "", "title", title_boost=8))
    # Content scan: keep cost bounded
    body = (content or "")[:8000]
    hits.extend(_find_module_hits(body, "content", title_boost=0))
    return hits


def score_product_lines(
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> Counter:
    """Weighted vote of product lines from module PNs and keywords."""
    scores: Counter = Counter()
    for hit in extract_module_mentions(title, content):
        # Title hits already have higher weight; content counts by mention
        scores[hit.product_line] += hit.weight

    # Count repeated content mentions of the same token family more accurately
    body = (content or "")[:8000]
    for pattern, line, base_w in _MODULE_FAMILY_RULES:
        n = len(re.findall(pattern, body, flags=re.IGNORECASE))
        if n > 1:
            scores[line] += (n - 1) * max(1, base_w // 3)

    text = f"{title or ''}\n{body}"
    for pattern, line in _KEYWORD_LINE_HINTS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            scores[line] += 3
    return scores


def detect_product_line(
    title: Optional[str] = None,
    content: Optional[str] = None,
    *,
    min_score: int = 8,
) -> Optional[str]:
    """
    Return best product-line tag1 when evidence is strong enough.
    Prefer title module PN, then most-mentioned content module, then keywords.
    """
    scores = score_product_lines(title, content)
    if not scores:
        return None
    best_line, best_score = scores.most_common(1)[0]
    if best_score < min_score:
        return None
    # Ambiguous: top two close → rely on title-only module if unique
    top = scores.most_common(2)
    if len(top) >= 2 and top[0][1] - top[1][1] < 4:
        title_hits = extract_module_mentions(title, None)
        title_lines = {h.product_line for h in title_hits}
        if len(title_lines) == 1:
            return next(iter(title_lines))
        return None
    return best_line


def product_line_prompt_block(
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> str:
    """Extra prompt context for the LLM from QT-SOP-PM-048E-derived hints."""
    scores = score_product_lines(title, content)
    hits = extract_module_mentions(title, content)
    if not scores and not hits:
        return ""
    top = ", ".join(f"{line}={score}" for line, score in scores.most_common(4))
    samples = ", ".join(f"{h.token}→{h.product_line}" for h in hits[:8])
    best = detect_product_line(title, content)
    return f"""====================
【模组/项目名产品线提示 — 基于 QT-SOP-PM-048E】
检测到的模组/项目名: {samples or '无'}
产品线加权得分: {top or '无'}
推荐顶层域(tag1): {best or '暂不强制'}

命名规则速查（用于选择 tag1，禁止无依据时乱选 Others）:
- Cellular: 首字母 E/R/B/M/U/T + 封装字母（EC/EG/BG/BC/RG/RM…），不含 Smart/Automotive
- Automotive: AG / AM 等车载模组与毫米波雷达
- Smart: 首字母 S（SC/SG/SP/SE/SH…）智能模组 / Android / Yocto
- GNSS: 首字母 L（LC/LG/LS/L76/L89/LUA…）
- ShortRange: 首字母 F/H/K（FC/FCM/HC/KC… WiFi/BT/Zigbee/LoRa）
- Satellite: 首字母 C 的卫星模组（CC660/CC950…）及 NTN/D2C
- Antenna: 天线产品线
- QuecOpen: 开放系统 SDK / 拨号 / 外设驱动（常叠加在 Cellular/Smart 模组上）

裁决优先级:
1) 标题中的模组型号
2) 正文提及次数最多、且为操作对象的模组
3) 来源文件夹域（若有）
尽量输出具体叶子路径；仅在完全无法判断时才用 Others。
===================="""
