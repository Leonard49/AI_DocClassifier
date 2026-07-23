"""Quectel module / project-name → product-line mapping (QT-SOP-PM-048E V12)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

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

# Non-alphanumeric boundaries so "AG35模组" / "SG882G-如何" still match.
_B_L = r"(?<![A-Za-z0-9])"
_B_R = r"(?![A-Za-z0-9])"

# Tokens that look like module PNs but are interface/storage jargon.
_FALSE_POSITIVE_TOKENS: Set[str] = {
    "RGMII",
    "SGMII",
    "RMII",
    "XMII",
    "EMMC",
    "EMCP",
    "EEPROM",
    "SDIO",
    "PCIE",
    "USB",
    "UART",
    "GPIO",
    "I2C",
    "I2S",
    "SPI",
    "CAN",
    "ADP",
    "APN",
    "IMS",
    "SMS",
    "OTA",
    "FOTA",
    "DFOTA",
}

# Ordered rules: more specific families first.
# Digits are required for short Cellular prefixes to avoid RGMII/eMMC false hits.
_MODULE_FAMILY_RULES: Sequence[Tuple[str, str, int]] = (
    # Automotive (AG35 / AG52x / AG59x / AM…)
    (rf"{_B_L}AG\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "Automotive", 12),
    (rf"{_B_L}AM\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "Automotive", 10),
    # Smart: SC/SE/SP/SH/SG/SA (SG530 / SG882 / SC200 / SA800…)
    (rf"{_B_L}S[CEPHGA]\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "Smart", 12),
    # Satellite: CC660 / CC950…
    (rf"{_B_L}CC\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "Satellite", 12),
    # GNSS: LC29 / LG69 / LS200 / L76 / L89 / LUA…
    (rf"{_B_L}L[CGUSAML]\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "GNSS", 11),
    (rf"{_B_L}L[789]\d[A-Za-z0-9\-]*{_B_R}", "GNSS", 10),
    (rf"{_B_L}LUA\d{{3}}[A-Za-z0-9\-]*{_B_R}", "GNSS", 10),
    # ShortRange: FC41 / FCM360 / HC25 / KC…
    (rf"{_B_L}F[CGMLSAPX]\w{{0,2}}\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "ShortRange", 11),
    (rf"{_B_L}H[CGMLSAP]\w{{0,2}}\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "ShortRange", 11),
    (rf"{_B_L}K[CGMLSAP]\w{{0,2}}\d{{2,4}}[A-Za-z0-9\-]*{_B_R}", "ShortRange", 10),
    # Cellular classic families — require ≥2 digits after prefix
    (
        rf"{_B_L}(?:EC|EG|BG|BC|RG|RM|EM|UC|UG|MC|MG|RC)\d{{2,4}}[A-Za-z0-9\-]*{_B_R}",
        "Cellular",
        10,
    ),
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


def _is_false_positive_token(token: str) -> bool:
    raw = (token or "").strip()
    if not raw:
        return True
    upper = raw.upper()
    if upper in _FALSE_POSITIVE_TOKENS:
        return True
    # Reject pure interface words with trailing letters but no digit (RGMII, eMMC…)
    if not re.search(r"\d", raw):
        return True
    return False


def _find_module_hits(text: str, source: str, title_boost: int = 0) -> List[ModuleHit]:
    if not text:
        return []
    hits: List[ModuleHit] = []
    seen = set()
    for pattern, line, base_w in _MODULE_FAMILY_RULES:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            token = match.group(0)
            if _is_false_positive_token(token):
                continue
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
        scores[hit.product_line] += hit.weight

    body = (content or "")[:8000]
    for pattern, line, base_w in _MODULE_FAMILY_RULES:
        valid = [
            m.group(0)
            for m in re.finditer(pattern, body, flags=re.IGNORECASE)
            if not _is_false_positive_token(m.group(0))
        ]
        if len(valid) > 1:
            scores[line] += (len(valid) - 1) * max(1, base_w // 3)

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
    # Title-only unique module family always wins (strongest signal).
    title_hits = extract_module_mentions(title, None)
    title_lines = {h.product_line for h in title_hits}
    if len(title_lines) == 1:
        return next(iter(title_lines))

    scores = score_product_lines(title, content)
    if not scores:
        return None
    best_line, best_score = scores.most_common(1)[0]
    if best_score < min_score:
        return None
    top = scores.most_common(2)
    if len(top) >= 2 and top[0][1] - top[1][1] < 4:
        # Prefer title module if unique; else no forced domain.
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
- Smart: 首字母 S（SC/SG/SP/SE/SH/SA…）智能模组 / Android / Yocto
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
若推荐顶层域已给出，禁止输出 Others，必须在该域子树内选叶子。
===================="""
