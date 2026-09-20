# -*- coding: utf-8 -*-
"""Patch the official contest plan: judge Q&A sections + diagrams. Keep original styles/images."""

from __future__ import annotations

import os
import shutil
from copy import deepcopy

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC_DIR = os.path.join(ROOT, "docs", "AI应用大赛相关材料")
DOC_PATH = os.path.join(DOC_DIR, "移远通信AI实战应用大赛_项目计划书_FAE知识智能治理平台.docx")
FIG_DIR = os.path.join(DOC_DIR, "_review_figs")

NAVY = (31, 58, 95)
NAVY2 = (44, 73, 110)
ORANGE = (196, 92, 38)
BG = (248, 250, 252)
CARD = (255, 255, 255)
LINE = (214, 221, 230)
TEXT = (32, 42, 54)
MUTED = (92, 103, 116)
SOFT = (232, 239, 247)
GREEN = (46, 125, 99)

FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_BD = r"C:\Windows\Fonts\msyhbd.ttc"


def font(size: int, bold: bool = False):
    path = FONT_BD if bold else FONT_REG
    try:
        return ImageFont.truetype(path, size, index=0)
    except OSError:
        return ImageFont.truetype(FONT_REG, size, index=0)


def rr(draw, xy, r, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def text_w(draw, s, f):
    b = draw.textbbox((0, 0), s, font=f)
    return b[2] - b[0], b[3] - b[1]


def wrap(draw, text, f, max_w):
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if text_w(draw, trial, f)[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def title_bar(draw, w, title):
    f = font(42, True)
    tw, th = text_w(draw, title, f)
    x = (w - tw) // 2
    y = 36
    draw.text((x, y), title, font=f, fill=NAVY)
    # decorative dots
    gap = 18
    draw.ellipse((x - 70, y + th // 2 - 4, x - 62, y + th // 2 + 4), fill=ORANGE)
    draw.line((x - 54, y + th // 2, x - 16, y + th // 2), fill=LINE, width=3)
    draw.ellipse((x + tw + 62, y + th // 2 - 4, x + tw + 70, y + th // 2 + 4), fill=ORANGE)
    draw.line((x + tw + 16, y + th // 2, x + tw + 54, y + th // 2), fill=LINE, width=3)


def save(img, name):
    os.makedirs(FIG_DIR, exist_ok=True)
    path = os.path.join(FIG_DIR, name)
    img.save(path, "PNG", optimize=True)
    return path


def fig_mindmap():
    w, h = 1800, 1080
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "飞书能力层  vs  自研 Agent 层")
    # center
    cx, cy, cr = w // 2, 560, 150
    d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=NAVY)
    cf = font(26, True)
    for i, line in enumerate(["FAE 知识", "智能治理", "平台"]):
        tw, th = text_w(d, line, cf)
        d.text((cx - tw // 2, cy - 52 + i * 36), line, font=cf, fill=(255, 255, 255))
    # left Feishu
    lf = font(22, True)
    sf = font(18)
    left = [
        ("飞书 Wiki 提供", True),
        ("页面编辑与目录", False),
        ("权限与协作", False),
        ("基础全文检索", False),
        ("OpenAPI 接入", False),
    ]
    rr(d, (70, 220, 520, 920), 22, CARD, LINE, 2)
    d.rectangle((70, 220, 520, 290), fill=NAVY2)
    d.text((110, 236), "企业存储 / 协作层", font=lf, fill=(255, 255, 255))
    for i, (t, _) in enumerate(left[1:], 0):
        y = 330 + i * 120
        rr(d, (110, y, 480, y + 88), 14, SOFT)
        d.text((140, y + 28), t, font=sf, fill=TEXT)
    d.line((520, 560, cx - cr, 560), fill=LINE, width=4)
    # right agents
    rr(d, (1280, 180, 1730, 980), 22, CARD, LINE, 2)
    d.rectangle((1280, 180, 1730, 250), fill=ORANGE)
    d.text((1320, 196), "自研 Agent（本项目）", font=lf, fill=(255, 255, 255))
    agents = [
        "抽取 Agent  PDF/Word/PPT",
        "分类 Agent  规则+LLM",
        "标题 / 元数据 Agent",
        "编排 Agent  增量·去重·限流",
        "修复 Agent  裂图重绑",
    ]
    for i, t in enumerate(agents):
        y = 280 + i * 128
        rr(d, (1320, y, 1690, y + 100), 14, SOFT)
        d.text((1350, y + 34), t, font=sf, fill=TEXT)
    d.line((cx + cr, 560, 1280, 560), fill=ORANGE, width=4)
    foot = font(18)
    msg = "飞书提供存储与协作；感知、约束决策与治理编排由本项目自研 Agent 完成。"
    tw, _ = text_w(d, msg, foot)
    d.text(((w - tw) // 2, 1000), msg, font=foot, fill=MUTED)
    return save(img, "fig4_agent_mindmap.png")


def fig_agents_table():
    w, h = 1800, 980
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "原生 Agent · 模型 · 工具")
    headers = ["Agent", "做什么", "模型", "工具"]
    rows = [
        ["抽取", "附件→正文/表/图", "规则为主", "PyMuPDF · docx · pptx\n飞书媒体/图块 API"],
        ["分类", "产品线×技术叶子", "deepseek-v4-flash", "Wiki 扫描/读取/复制\nQT-SOP 正则 · 标签树"],
        ["标题元数据", "主题-型号-作者", "deepseek-v4-flash", "改标题 · 文内元数据表"],
        ["编排", "增量去重限流", "不调用 LLM", "快照 · 共享库 · 账本 · 控制台"],
        ["修复", "裂图重绑/重提", "不调用 LLM", "wiki token extra · 转码"],
    ]
    cols = [220, 420, 420, 620]
    x0, y0, row_h = 70, 160, 140
    # header
    x = x0
    for i, hname in enumerate(headers):
        rr(d, (x, y0, x + cols[i] - 12, y0 + 70), 10, NAVY)
        f = font(20, True)
        tw, th = text_w(d, hname, f)
        d.text((x + 20, y0 + 22), hname, font=f, fill=(255, 255, 255))
        x += cols[i]
    hf, sf = font(20, True), font(17)
    for ri, row in enumerate(rows):
        y = y0 + 86 + ri * row_h
        x = x0
        bg = CARD if ri % 2 == 0 else SOFT
        rr(d, (x0, y, x0 + sum(cols) - 12, y + row_h - 12), 10, bg, LINE, 1)
        for ci, cell in enumerate(row):
            lines = cell.split("\n")
            fnt = hf if ci == 0 else sf
            col = ORANGE if ci == 0 else TEXT
            for li, line in enumerate(lines):
                d.text((x + 18, y + 28 + li * 28), line, font=fnt, fill=col)
            x += cols[ci]
    return save(img, "fig5_agent_stack.png")


def fig_pdf():
    w, h = 1800, 1020
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "以 PDF 为例：正文 · 表格 · 图片如何抽取")
    stages = [
        ("1. 打开", "PyMuPDF 按页\n读取 PDF"),
        ("2. 正文", "get_text(blocks)\n按 y 坐标排序"),
        ("3. 表格", "单元格作文本块\nWord 表按行 “|”"),
        ("4. 图片", "XObject → RGB\nJPEG/PNG 转码"),
        ("5. 写入", "Wiki「附件：」区\n段落 + 图块"),
    ]
    f1, f2 = font(22, True), font(17)
    for i, (t, b) in enumerate(stages):
        x = 70 + i * 350
        rr(d, (x, 200, x + 310, 520), 20, CARD, LINE, 2)
        rr(d, (x, 200, x + 310, 270), 0, NAVY if i < 4 else ORANGE)
        # fake round top by covering - skip, just navy header
        d.rectangle((x, 240, x + 310, 270), fill=NAVY if i < 4 else ORANGE)
        tw, _ = text_w(d, t, f1)
        d.text((x + (310 - tw) // 2, 218), t, font=f1, fill=(255, 255, 255))
        for li, line in enumerate(b.split("\n")):
            tw, _ = text_w(d, line, f2)
            d.text((x + (310 - tw) // 2, 330 + li * 40), line, font=f2, fill=TEXT)
        if i < 4:
            d.polygon(
                [(x + 318, 350), (x + 342, 365), (x + 318, 380)],
                fill=ORANGE,
            )
    # notes
    notes = [
        ("图与表策略", "图供人阅读与页面展示，表内文字进入全文检索。属于多模态摄入 + 文本层检索，暂不做视觉向量。"),
        ("实施顺序", "先让 1.7 万篇附件进入索引、可检索，再在治理后的语料上建设向量 RAG。"),
        ("Word / PPT", "Word：段落 + 表内图 + VML；PPT：含组合图形递归。裂图按 wiki node token 重绑。"),
    ]
    nf, ns = font(20, True), font(17)
    for i, (t, b) in enumerate(notes):
        y = 580 + i * 130
        rr(d, (70, y, 1730, y + 112), 16, CARD, LINE, 1)
        d.rectangle((70, y, 86, y + 112), fill=ORANGE)
        d.text((120, y + 16), t, font=nf, fill=ORANGE)
        lines = wrap(d, b, ns, 1560)
        for li, line in enumerate(lines):
            d.text((120, y + 50 + li * 26), line, font=ns, fill=MUTED)
    return save(img, "fig6_pdf_extract.png")


def fig_store_recall():
    w, h = 1800, 1080
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "知识如何存储，召回做了哪些优化")
    hf, sf, bf = font(22, True), font(17), font(18, True)
    # left storage
    rr(d, (60, 170, 860, 1000), 22, CARD, LINE, 2)
    d.rectangle((60, 170, 860, 250), fill=NAVY)
    d.text((100, 192), "存储（不是先建向量库）", font=hf, fill=(255, 255, 255))
    left_items = [
        ("SCAN", "作者继续写作的源空间，不覆盖现场稿"),
        ("TARGET", "分类枢纽副本：治理、检索、后续 RAG 的语料"),
        ("知识包", "正文 +「附件：」抽取区 + 文首元数据表"),
        ("图片", "按 TARGET wiki token 重绑，避免副本裂图"),
        ("去噪", "周报/日报/纪要/跟踪表不入库"),
        ("账本", "obj_token 去重 · 增量快照 · 操作级跳过"),
    ]
    for i, (k, v) in enumerate(left_items):
        y = 280 + i * 112
        rr(d, (100, y, 820, y + 96), 12, SOFT)
        d.text((130, y + 14), k, font=bf, fill=ORANGE)
        d.text((130, y + 50), v, font=sf, fill=TEXT)
    # right recall
    rr(d, (940, 170, 1740, 1000), 22, CARD, LINE, 2)
    d.rectangle((940, 170, 1740, 250), fill=ORANGE)
    d.text((980, 192), "召回 L0–L4 已上线 / L5 规划", font=hf, fill=(255, 255, 255))
    layers = [
        ("L0 清洗", "附件正文化、裂图修复，字先进入索引"),
        ("L1 目录", "Product Line × Technical Category 先过滤"),
        ("L2 可读", "标题=主题-型号-作者，命中后 1 秒可判断"),
        ("L3 全文", "飞书检索 TARGET 正文+抽取区（含 PDF 字）"),
        ("L4 目录表", "多维表按作者/型号/路径筛选"),
        ("L5 RAG", "规划：仅在评分达标语料上建向量问答"),
    ]
    for i, (k, v) in enumerate(layers):
        y = 280 + i * 112
        fill = (255, 244, 236) if i == 5 else SOFT
        rr(d, (980, y, 1700, y + 96), 12, fill)
        d.text((1010, y + 14), k, font=bf, fill=ORANGE if i < 5 else NAVY)
        d.text((1010, y + 50), v, font=sf, fill=TEXT)
    return save(img, "fig7_storage_recall.png")


def fig_judge_mindmap():
    """Radial mind map of platform capabilities."""
    w, h = 1800, 1080
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "方案能力全景：从知识治理到后续服务")
    cx, cy, cr = w // 2, 560, 132
    cf, cs = font(24, True), font(16)

    nodes = [
        (90, 170, 520, 330, "分层架构", "飞书 + 自研 Agent", "Wiki 承担存储与协作；\n感知、决策、编排由本项目完成。"),
        (1280, 170, 1710, 330, "原生 Agent", "模型与工具", "抽取 / 分类 / 标题 / 编排 / 修复\ndeepseek-v4-flash + OpenAPI"),
        (70, 430, 430, 620, "附件抽取", "正文 · 表格 · 图片", "PDF 按块排序抽正文；表进文本；\n图转 RGB 写入飞书图块。"),
        (1370, 430, 1730, 620, "知识存储", "SCAN / TARGET", "源空间不覆盖现场稿；枢纽副本\n含正文、抽取区与元数据表。"),
        (160, 780, 620, 980, "召回策略", "L0–L4 已上线", "清洗、目录、可读标题、全文检索。\n向量 RAG 在治理语料上规划。"),
        (1180, 780, 1640, 980, "后续接入", "评分 · 问答 · 工单", "质量评分后接入检索问答与工单辅助；\nRewrite 可选，须人工确认。"),
    ]
    hf, bf, sf = font(16, True), font(20, True), font(16)
    for x1, y1, x2, y2, tag, title, body in nodes:
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        d.line((cx, cy, mx, my), fill=LINE, width=4)
    d.ellipse((cx - cr - 8, cy - cr - 8, cx + cr + 8, cy + cr + 8), outline=LINE, width=3)
    d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=NAVY)
    for i, line in enumerate(["能力全景", "治理先行", "再接问答"]):
        tw, _ = text_w(d, line, cf if i == 0 else cs)
        col = (255, 255, 255) if i == 0 else (210, 222, 236)
        d.text((cx - tw // 2, cy - 48 + i * 34), line, font=cf if i == 0 else cs, fill=col)
    for x1, y1, x2, y2, tag, title, body in nodes:
        rr(d, (x1, y1, x2, y2), 18, CARD, LINE, 2)
        d.rectangle((x1, y1, x1 + 10, y2), fill=ORANGE)
        d.text((x1 + 28, y1 + 16), tag, font=hf, fill=ORANGE)
        d.text((x1 + 28, y1 + 46), title, font=bf, fill=NAVY)
        for li, line in enumerate(body.split("\n")):
            d.text((x1 + 28, y1 + 88 + li * 28), line, font=sf, fill=TEXT)
    return save(img, "fig4_judge_mindmap.png")


def fig_roadmap():
    w, h = 1800, 820
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "知识生命周期：Agent 接入路线")
    phases = [
        ("已上线", "治理 Agent", "抽取 · 分类\n标题 · 编排 · 修复", ORANGE),
        ("试点", "质量评分 Agent", "5 维 25 分\n必须给证据", NAVY),
        ("下一步", "检索问答 Agent", "TARGET 向量 RAG\n目录过滤 + 全文", NAVY2),
        ("下一步", "工单辅助 Agent", "同型号历史案例\n步骤推荐", NAVY2),
        ("可选", "Rewrite Agent", "不覆盖原文\n人工确认", MUTED),
    ]
    f1, f2, f3 = font(18, True), font(22, True), font(16)
    for i, (st, name, body, col) in enumerate(phases):
        x = 50 + i * 350
        rr(d, (x, 180, x + 320, 640), 20, CARD, LINE, 2)
        d.rectangle((x, 180, x + 320, 250), fill=col)
        tw, _ = text_w(d, st, f1)
        d.text((x + (320 - tw) // 2, 200), st, font=f1, fill=(255, 255, 255))
        tw, _ = text_w(d, name, f2)
        d.text((x + (320 - tw) // 2, 290), name, font=f2, fill=NAVY)
        for li, line in enumerate(body.split("\n")):
            tw, _ = text_w(d, line, f3)
            d.text((x + (320 - tw) // 2, 380 + li * 36), line, font=f3, fill=MUTED)
        if i < 4:
            d.polygon([(x + 328, 390), (x + 348, 405), (x + 328, 420)], fill=ORANGE)
    foot = font(18)
    msg = "没有 L0–L3 治理就上 RAG，会检索到周报、裂图和日期标题。所以先治理，再问答。"
    tw, _ = text_w(d, msg, foot)
    d.text(((w - tw) // 2, 700), msg, font=foot, fill=MUTED)
    return save(img, "fig8_agent_roadmap.png")


def fig_replicate():
    w, h = 1800, 780
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "可复制的是治理流水线，不是某个飞书空间")
    steps = [
        ("1. 接入源", "配置 SCAN\n指定知识空间"),
        ("2. 领域规则", "标签树\n模组正则 · 排除表"),
        ("3. Agent 流水线", "抽取 · 分类\n标题 · 修复"),
        ("4. 枢纽语料", "TARGET 目录\n正文 + 图 + 元数据"),
        ("5. 下游供给", "评分 · 检索\n问答 / 对外候选"),
    ]
    f1, f2, f3 = font(18, True), font(20, True), font(16)
    for i, (st, body) in enumerate(steps):
        x = 50 + i * 350
        col = ORANGE if i in (2, 3) else NAVY
        rr(d, (x, 180, x + 320, 560), 20, CARD, LINE, 2)
        d.rectangle((x, 180, x + 320, 250), fill=col)
        tw, _ = text_w(d, st, f1)
        d.text((x + (320 - tw) // 2, 200), st, font=f1, fill=(255, 255, 255))
        for li, line in enumerate(body.split("\n")):
            tw, _ = text_w(d, line, f2 if li == 0 else f3)
            fill = NAVY if li == 0 else MUTED
            d.text((x + (320 - tw) // 2, 310 + li * 44), line, font=f2 if li == 0 else f3, fill=fill)
        if i < 4:
            d.polygon([(x + 328, 350), (x + 348, 365), (x + 328, 380)], fill=ORANGE)
    foot = font(18)
    msg = "换 SCAN/TARGET token 与标签树即可迁到研发、认证、培训等知识空间；代码不绑定单一 Wiki。"
    tw, _ = text_w(d, msg, foot)
    d.text(((w - tw) // 2, 640), msg, font=foot, fill=MUTED)
    return save(img, "fig10_replicate.png")


def fig_effect():
    w, h = 1800, 720
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    title_bar(d, w, "已落地、可核验的效果数据")
    cards = [
        ("17,105", "篇", "有效叶子完成分类复制", "过程稿已排除，进入 TARGET 枢纽"),
        ("17,092", "篇", "标题标准化", "主题-型号-作者，检索结果可读"),
        ("169,010", "张", "附件图完成重绑", "TARGET 17,255 篇裂图修复"),
        ("约 1.7", "FTE/年", "持续提效（同一口径）", "检索复用约占 1.44 FTE"),
    ]
    nf, uf, tf, sf = font(40, True), font(18, True), font(20, True), font(16)
    for i, (num, unit, title, sub) in enumerate(cards):
        x = 50 + i * 440
        rr(d, (x, 170, x + 410, 560), 20, CARD, LINE, 2)
        d.rectangle((x, 170, x + 410, 186), fill=ORANGE if i == 2 else NAVY)
        tw, _ = text_w(d, num, nf)
        d.text((x + (410 - tw) // 2, 230), num, font=nf, fill=ORANGE)
        tw, _ = text_w(d, unit, uf)
        d.text((x + (410 - tw) // 2, 290), unit, font=uf, fill=MUTED)
        tw, _ = text_w(d, title, tf)
        d.text((x + (410 - tw) // 2, 360), title, font=tf, fill=NAVY)
        lines = wrap(d, sub, sf, 350)
        for li, line in enumerate(lines):
            tw, _ = text_w(d, line, sf)
            d.text((x + (410 - tw) // 2, 430 + li * 28), line, font=sf, fill=MUTED)
    foot = font(18)
    msg = "存量一次性整理约 1 人年已兑现，不计入「每年」。提效公式与第三章同一口径。"
    tw, _ = text_w(d, msg, foot)
    d.text(((w - tw) // 2, 620), msg, font=foot, fill=MUTED)
    return save(img, "fig11_effect.png")


# -------------------- Word patch --------------------

def set_texts(el, text: str) -> None:
    ts = el.findall(".//" + qn("w:t"))
    if not ts:
        return
    ts[0].text = text
    ts[0].set(qn("xml:space"), "preserve")
    for t in ts[1:]:
        t.text = ""


def clone_p(src_p, text: str):
    el = deepcopy(src_p._element)
    set_texts(el, text)
    return el


def insert_after(anchor, nodes):
    cur = anchor
    for n in nodes:
        cur.addnext(n)
        cur = n
    return cur


def add_picture_p(doc, src_empty_p, image_path, width_cm=15.6):
    """Create a centered picture paragraph, then detach it for insert_after."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    tmp = doc.add_paragraph()
    tmp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tmp.paragraph_format.space_before = Pt(8)
    tmp.paragraph_format.space_after = Pt(4)
    tmp.paragraph_format.first_line_indent = Cm(0)
    run = tmp.add_run()
    run.add_picture(image_path, width=Cm(width_cm))
    pic_el = tmp._element
    doc.element.body.remove(pic_el)
    return pic_el


def fill_tbl_xml(tbl_el, data):
    trs = tbl_el.findall(qn("w:tr"))
    for ri, row in enumerate(data):
        if ri >= len(trs):
            break
        tcs = trs[ri].findall(qn("w:tc"))
        for ci, val in enumerate(row):
            if ci >= len(tcs):
                break
            set_texts(tcs[ci], val)


def clone_table(src_tbl, rows):
    """Deepcopy table and rewrite cell texts. rows must match size or we only fill existing."""
    el = deepcopy(src_tbl._element)
    from docx.table import Table
    # We'll fill after attaching using python-docx Table wrapper — fill in caller.
    return el


def fill_existing_table(table, data):
    for ri, row in enumerate(data):
        if ri >= len(table.rows):
            break
        for ci, val in enumerate(row):
            if ci >= len(table.columns):
                break
            cell = table.rows[ri].cells[ci]
            paras = cell.paragraphs
            if not paras:
                cell.text = val
                continue
            set_texts(paras[0]._element, val)
            for p in paras[1:]:
                set_texts(p._element, "")


def patch():
    bak = DOC_PATH + ".pre_review.bak"
    if not os.path.exists(bak):
        shutil.copy2(DOC_PATH, bak)
    else:
        shutil.copy2(bak, DOC_PATH)

    figs = {
        "judge": fig_judge_mindmap(),
        "mind": fig_mindmap(),
        "stack": fig_agents_table(),
        "pdf": fig_pdf(),
        "store": fig_store_recall(),
        "road": fig_roadmap(),
        "repl": fig_replicate(),
        "effect": fig_effect(),
    }

    doc = Document(DOC_PATH)
    paras = doc.paragraphs
    tables = doc.tables

    h1 = paras[42]  # 一、项目概述
    h2 = paras[43]  # （一）
    body = paras[44]
    bullet = paras[47]
    caption = paras[73]
    empty = paras[72]
    sub_h = paras[70]  # （二）技术实现路径

    # cover date
    set_texts(paras[10]._element, "申报日期：            2026 年 09 月 20 日")

    # TOC
    set_texts(paras[21]._element, "（三）创新点说明")
    toc_items = [
        "（四）原生 Agent、模型与工具",
        "（五）附件抽取：正文、表格与图片",
        "（六）知识存储与优化",
        "（七）召回机制与后续 RAG",
        "（八）后续 Agent 接入场景",
    ]
    toc_nodes = [clone_p(paras[21], t) for t in toc_items]
    insert_after(paras[21]._element, toc_nodes)
    toc5 = [
        "（四）落地效果数据",
        "（五）用户反馈与使用情况",
    ]
    insert_after(paras[32]._element, [clone_p(paras[32], t) for t in toc5])

    # intro
    set_texts(
        paras[44]._element,
        "本项目面向全球 FAE Sharing，建设的是「知识治理 Agent 平台」，而不是再包一层飞书知识库。"
        "飞书 Wiki 是企业指定的存储与协作入口；分类、抽取、标题、编排、裂图修复是自研 Agent 流水线。"
        "系统自动扫描历史与新增文档，解析 PDF/Word/PPT，按 QT-SOP-PM-048E 与标签树完成 "
        "Product Line × Technical Category 分类，写入统一 TARGET 枢纽，并生成「主题-型号-作者」标题与元数据。"
        "约 17,105 篇有效叶子已分类复制，17,092 篇标题标准化；枢纽侧已重绑约 16.9 万张附件图。"
        "当前优先完成附件可检索、目录可导航、标题可读，作为后续检索问答与 FAE Support Agent 的语料前提。"
        "下一阶段试点 5 维 25 分质量评分 Agent。",
    )

    # extra pain bullet after 052
    extra_bullet = clone_p(
        bullet,
        "• 飞书原生存储不解治理：Wiki 提供编辑、目录和基础检索，但不解析 PDF/PPT、不按模组规范分类、"
        "不改日期标题、不做增量编排。只靠飞书自带能力，FAE 仍要在人名文件夹里翻附件。",
    )
    paras[52]._element.addnext(extra_bullet)

    # tech path sentence
    set_texts(
        paras[71]._element,
        "项目采用「飞书存储 + 自研 Agent」分层架构：OpenAI 兼容网关调用 deepseek-v4-flash，"
        "工具为飞书 OpenAPI、PyMuPDF/python-docx/python-pptx 与本地账本。"
        "端到端流程见图 1；能力全景见图 4，飞书与自研 Agent 分层见图 5。",
    )

    # progress
    set_texts(
        paras[106]._element,
        "项目已完成大规模分类治理并持续增量运行。2026 年 9 月完成 TARGET 17,255 篇附件裂图修复："
        "有图 5,823 篇，重绑 169,010 张，空图块自动重提 698 篇。当前进入 AI 质量评分平台设计与试点；"
        "向量 RAG 规划在评分达标语料上接入，不把未治理文档直接向量化。",
    )

    # attachments note
    set_texts(
        paras[125]._element,
        "可验证证据：TARGET 分类目录截图、端到端架构图、治理闭环图，以及能力全景、Agent 分层、"
        "抽取/存储/召回示意图、可复制流水线与效果数据图。AI 评分真实页面待试点完成后补充。",
    )

    # update innovation table (T2)
    fill_existing_table(
        tables[2],
        [
            ["创新点", "实现方式", "业务价值"],
            ["受约束分类 Agent", "模组规则先定产品线，LLM 只在标签子树选叶子", "可运营、可纠偏，不是聊天分类"],
            ["附件结构化摄入", "PDF/PPT 进入正文和图块，而不是黑盒附件", "分类和检索能看见附件里的根因"],
            ["治理先于 RAG", "先目录+全文+质量分，再向量问答", "避免脏语料污染 Support Agent"],
            ["工程化编排", "增量、去重、限流、账本、控制台", "1.7 万篇可连续跑，而不是 Demo"],
        ],
    )

    # update progress table T5 last rows
    fill_existing_table(
        tables[5],
        [
            ["阶段", "状态", "主要成果 / 下一步"],
            ["Phase 1｜迁移与技术验证", "已完成", "Confluence → Lark Wiki；飞书读取、附件解析、AI 分类链路验证"],
            ["Phase 2｜历史知识结构化", "核心完成", "约 17,105 篇进 TARGET；17,092 标题标准化；169,010 张图重绑"],
            ["Phase 3｜持续知识治理", "运行/优化中", "增量扫描、元数据、Others 纠偏、空图块自动重提"],
            ["Phase 4｜AI Quality", "规则已定义，平台设计/试点中", "5 维 25 分评分、证据、人工复评；Rewrite 为后续可选"],
            ["Phase 5｜Knowledge Service", "规划 / 跨团队协同", "TARGET 上 RAG 与工单辅助；对外库由协作团队发布"],
        ],
    )

    # Build new section nodes before 三、实用性分析 (paras[85])
    h_sub = paras[43]
    h_body = paras[44]
    h_cap = paras[73]
    h_empty = paras[74]
    h_bullet = paras[47]

    def H(text):
        return clone_p(h_sub, text)

    def B(text):
        return clone_p(h_body, text)

    def C(text):
        return clone_p(h_cap, text)

    def L(text):
        return clone_p(h_bullet, text)

    def Pic(path):
        return add_picture_p(doc, empty, path)

    block = []
    block.append(H("（四）原生 Agent、模型与工具"))
    block.append(
        B(
            "本项目的 Agent 是批处理智能体：感知文档 → 调用工具 → 受约束决策 → 写回知识枢纽。"
            "模型当前为 deepseek-v4-flash，经公司 OpenAI 兼容网关调用；每个 Agent 有固定工具集，"
            "分类不得脱离标签树或模组正则。"
        )
    )
    block.append(Pic(figs["judge"]))
    block.append(C("图 4  方案能力全景：分层架构、抽取、存储、召回与后续 Agent"))
    qa_tbl = deepcopy(tables[3]._element)
    fill_tbl_xml(
        qa_tbl,
        [
            ["能力模块", "做法", "详见"],
            ["分层架构", "飞书 Wiki 负责存储与协作；感知、约束决策与编排由自研 Agent 完成", "图 4、图 5"],
            ["原生 Agent / 模型 / 工具", "抽取·分类·标题·编排·修复；deepseek-v4-flash；OpenAPI+解析库+账本", "（四）图 6"],
            ["附件抽取（正文 / 表格 / 图片）", "块排序正文；表进文本检索；图转码写入 Wiki。图供展示，检索走文本层", "（五）图 7"],
            ["知识存储与优化", "SCAN/TARGET 双空间；知识包=正文+抽取区+元数据；裂图重绑约 16.9 万张", "（六）图 8"],
            ["召回与后续服务", "L0–L4 目录与全文已上线；L5 向量 RAG 规划在评分达标语料上接入", "（七）（八）"],
        ],
    )
    block.append(qa_tbl)
    block.append(C("表  核心能力一览（与图 4 对应，下文分节展开）"))
    block.append(Pic(figs["mind"]))
    block.append(C("图 5  飞书只提供存储与协作；抽取、分类、标题、编排、修复均为自研 Agent"))
    block.append(Pic(figs["stack"]))
    block.append(C("图 6  已上线 Agent 的职责、模型与工具（飞书 OpenAPI 是被调用的工具，不是决策逻辑）"))
    block.append(
        L("• 抽取 Agent：PDF/Word/PPT → 正文、表格文字、可显示图片，写入「附件：」分区。")
    )
    block.append(
        L("• 分类 Agent：排除周报等过程稿后，输出 Product Line × Technical Category 叶子路径。")
    )
    block.append(L("• 标题与元数据 Agent：生成「主题-型号-作者」，并贴文内元数据表。"))
    block.append(L("• 编排 Agent：增量快照、共享去重、飞书/LLM 限流、控制台派发。不调用大模型。"))
    block.append(L("• 修复 Agent：副本裂图按 wiki node token 重绑；空图块从原附件重提。"))

    block.append(H("（五）附件抽取：正文、表格与图片"))
    block.append(
        B(
            "目标不是做通用文档解析 SaaS，而是让附件进入与飞书正文同一条分类和检索链路。"
            "抽取写回源文档「附件：」区，复制到 TARGET 后再按 wiki 鉴权重绑图片。"
        )
    )
    block.append(Pic(figs["pdf"]))
    block.append(C("图 7  PDF 抽取路径：正文按块排序，表格进文本检索，图片转码后写入图块"))
    block.append(
        L(
            "• 正文：PyMuPDF page.get_text(\"blocks\") 取文本块，按 y 坐标保持阅读顺序，页末插入「第 N 页」。"
        )
    )
    block.append(
        L(
            "• 表格：PDF 单元格作为空间相邻文本块抽出（稳定、可检索，暂不重建栅格表）。"
            "Word 表格按行写成「单元格 | 单元格」，结构更好。"
        )
    )
    block.append(
        L(
            "• 图片：取 PDF XObject，按页面坐标与正文交织插入；CMYK / JPEG2000 / GIF / WEBP / EMF 等转为 RGB JPEG 或 PNG，"
            "否则飞书图块会裂图。上传带 extra.drive_route_token（优先 wiki node token）。"
        )
    )
    block.append(
        L(
            "• 图与表：图供人阅读与页面展示，表内文字进入全文；关键示意图的 caption 与向量索引为后续优化。"
        )
    )

    block.append(H("（六）知识存储与优化"))
    block.append(
        B(
            "存储单元不是向量库，而是「受治理的飞书文档 + 元数据表 + 多维表目录」。"
            "这是有意选择：FAE 日常仍在飞书协作，治理结果必须落在他们已经打开的入口。"
        )
    )
    block.append(L("• 双空间：SCAN 是作者继续写作的源空间，不覆盖现场稿；TARGET 是分类枢纽副本，供检索与后续 RAG。"))
    block.append(L("• 知识包：一篇文档 = 原正文 +「附件：」抽取区（文本/表/图）+ 文首元数据表（原名、路径、作者、产品线、主题、型号）。"))
    block.append(L("• 图片优化：副本按 TARGET wiki node token 重绑，避免仍指向源空间媒体导致裂图；17,255 篇已修复，重绑 169,010 张。"))
    block.append(L("• 去噪与增量：周报/日报/纪要/跟踪表不入库；按 obj_token 去重；快照只处理新增；操作账本避免重复贴表改名。"))
    block.append(H("（七）召回机制与后续 RAG"))
    block.append(
        B(
            "当前召回采用结构化过滤 + 全文检索。"
            "已上线层与规划层分开描述：目录与全文已用于生产检索；向量 RAG 将在质量评分达标语料上接入。"
        )
    )
    block.append(Pic(figs["store"]))
    block.append(C("图 8  SCAN/TARGET 双空间存储，与 L0–L5 召回分层（L5 向量 RAG 为规划）"))
    block.append(
        L("• 已上线 L0–L4：清洗附件、产品线目录、可读标题、飞书全文、多维表筛选。")
    )
    block.append(
        L("• 规划 L5：仅在质量评分达标的 TARGET 语料上建向量索引，做案例问答与工单辅助。")
    )
    block.append(
        L("• 分类 Agent 的域强制、叶子约束、Others 纠偏，会直接降低未来 RAG 的脏召回。")
    )

    block.append(H("（八）后续 Agent 接入场景"))
    block.append(
        B(
            "本项目覆盖知识全生命周期：采集 → 解析 → 分类 → 质量评分 → 人工复核 → 供给下游 Agent。"
            "治理类 Agent 已上线，消费侧 Agent 按阶段接入。"
        )
    )
    block.append(Pic(figs["road"]))
    block.append(C("图 9  Agent 接入路线：已上线治理、试点评分、规划中的问答与工单辅助"))
    block.append(
        L("• 已上线：抽取、分类、标题元数据、编排、图片修复，覆盖历史 1.7 万篇与每日增量。")
    )
    block.append(L("• 试点：质量评分 Agent（5 维 25 分，必须给原文证据）。"))
    block.append(L("• 下一步：检索问答 Agent、工单辅助 Agent（同型号历史案例）。"))
    block.append(L("• 可选：Rewrite Agent，不覆盖原文，必须人工确认。"))
    block.append(
        B(
            "可复制性取决于这套流水线，而不是某个飞书空间。换标签树与 SCAN/TARGET token，"
            "即可迁到研发、认证、培训知识库。对外知识库、官网问答由协作团队建设，本项目输出已分类、可检索、带质量分的候选。"
        )
    )

    insert_after(paras[84]._element, block)

    # ----- 五、可复制性与推广价值（展开 + 效果数据 + 用户反馈） -----
    set_texts(
        paras[112]._element,
        "可复制的核心不是某个已分好类的飞书空间，而是一条可配置的知识生产流水线："
        "内容接入 → 附件结构化 → 受约束 AI 分类 → 标准标题与元数据 → 人工可纠偏 → 持续增量治理。"
        "换知识源、标签树和排除规则，同一套 Agent 即可迁到新空间；飞书只是当前企业指定的存储入口。",
    )
    promo_extra = []
    promo_extra.append(Pic(figs["repl"]))
    promo_extra.append(C("图 10  推广复制路径：配置知识源与领域规则后，复用同一套 Agent 流水线"))
    promo_extra.append(
        L(
            "• 复制条件：目标空间提供文档库 API（当前为飞书 Wiki）、一份领域标签树、一份过程稿排除规则。"
            "代码不绑定单一 space token。"
        )
    )
    promo_extra.append(
        L(
            "• 配置切换：更换 SCAN 根节点、TARGET 父节点、LABEL_TREE、模组正则（如 QT-SOP-PM-048E）后即可启动。"
            "增量快照与去重账本按新空间重建或分库，互不影响。"
        )
    )
    promo_extra.append(
        L(
            "• 复制边界：对外知识库与官网问答由协作团队发布。本流水线输出已分类、可检索、带质量分的候选，"
            "不替代内容发布和权限审批。"
        )
    )
    insert_after(paras[112]._element, promo_extra)
    set_texts(
        paras[113]._element,
        "• 其他内部知识空间：研发、认证、培训、质量等知识库。复制时只换知识源、标签树、排除规则和评分子权重，"
        "不重写 Agent 流水线。适合「文档在 Wiki 里按人/项目堆放、附件未进检索」的同类场景。",
    )
    set_texts(
        paras[114]._element,
        "• 内部检索问答 / 工单辅助：以 TARGET 中已分类、已抽附件、标题可读的语料为数据基础。"
        "向量 RAG 只在质量评分达标后接入，避免把周报和裂图带进问答。",
    )
    set_texts(
        paras[115]._element,
        "• 对外知识协同：向下游团队提供经评分与人工确认的 A 档候选及证据。"
        "发布渠道、客户可见范围由协作团队负责，本项目不自动公开。",
    )

    std_extra = []
    std_extra.append(
        L(
            "• 运行标准化：增量快照只处理新增，obj_token 全局去重，飞书/LLM 限流与失败续跑写在账本里。"
            "换目录后仍按同一运维节奏：日增量、按需纠偏、定期裂图巡检。"
        )
    )
    std_extra.append(
        L(
            "• 交付标准化：Web 控制台派发扫描/抽取/修复任务，命令行可复现同一操作；"
            "QUICK_START、CONSOLE、ARCHITECTURE 说明如何接入新空间。"
        )
    )
    insert_after(paras[120]._element, std_extra)

    set_texts(
        paras[122]._element,
        "推广分三步，与完成度阶段对齐。"
        "第一步：现有 FAE Sharing 稳定增量运行，目录、标题、附件图保持可检索（已完成主体，持续运维）。"
        "第二步：约 100 篇文档校准 5 维 25 分质量评分，20–30 篇黄金样本对照人工，确认分数可解释后再扩产品线。"
        "第三步：向下游提供 A 档候选及评分证据，并在达标语料上小流量接入检索问答；形成「日增量 + 月度质量抽查」机制。",
    )

    fx = []
    fx.append(H("（四）落地效果数据"))
    fx.append(
        B(
            "以下数据均可在 TARGET 枢纽、运行账本或修复报告中核对。提效测算与第三章同一口径："
            "提效率=(前−后)/前；年等效 FTE=年节省小时/2000（250 天×8 小时）。"
            "增量按 80 篇/周、48 周；检索按 150 人、每人每周 2 次找同类案例。不采用「人数×提效率」。"
            "存量一次性整理已完成，约 1,400 人时归档 + 约 570 人时改标题，约 1 人年，不计入「每年」。"
        )
    )
    fx.append(Pic(figs["effect"]))
    fx.append(C("图 11  生产侧效果一览（分类、标题、裂图修复、年等效提效）"))
    fx_tbl = deepcopy(tables[3]._element)
    fill_tbl_xml(
        fx_tbl,
        [
            ["效果项", "数据（可核验）", "说明"],
            ["统一知识枢纽", "约 17,105 篇叶子完成分类复制", "历史 Sharing 20,000+ 项中，排除过程稿后的有效治理对象"],
            ["标题标准化", "17,092 篇改为「主题-型号-作者」", "搜索命中后可直接判断是否值得打开"],
            ["附件裂图修复", "17,255 篇巡检；169,010 张重绑；698 篇空图块重提", "2026 年 9 月 TARGET 生产结果；有图文档 5,823 篇"],
            ["持续提效（每年）", "约 3,373 小时 / 约 1.7 FTE", "检索复用约 1.44 FTE 是大头；归档 0.14、改标题 0.06、附件预览 0.04"],
            ["存量一次性整理", "约 1 人年已兑现", "历史库分类+改标题不再需要按篇人工建目录，不计入年度口径"],
        ],
    )
    fx.append(fx_tbl)
    fx.append(C("表  落地效果数据（与第三章提效表同一口径，裂图数据为 2026 年 9 月生产结果）"))
    fx.append(
        L("• 人工分类归档：5 分钟/篇 → 0.5 分钟/篇，提效率 90%，增量约 0.14 FTE/年。")
    )
    fx.append(
        L("• 跨区域/人名目录找同类案例：15 分钟/次 → 3 分钟/次，提效率 80%，约 1.44 FTE/年。")
    )
    fx.append(
        L("• 标题改为「主题-型号-作者」：2 分钟/篇 → 0，提效率 100%，增量约 0.06 FTE/年。")
    )
    fx.append(
        L("• 打开 PDF/PPT 才能判断能否复用：8 分钟/次 → 2 分钟/次，提效率 75%，约 0.04 FTE/年。")
    )
    fx.append(
        B(
            "上述检索与附件预览时长来自作业拆解与抽样估计，将用 5–10 名 FAE 秒表任务替换假设值。"
            "分类规模、标题数量、裂图重绑张数为系统已产生的生产计数。"
        )
    )

    fx.append(H("（五）用户反馈与使用情况"))
    fx.append(
        B(
            "分类归档已进入生产运行：一线 FAE 仍在原 Sharing 目录写作，治理结果落在 TARGET 枢纽供检索与复用。"
            "下列为已发生的使用变化和知识运营侧日常问题；结构化问卷与秒表抽查按第三章计划补齐。"
        )
    )
    fb_tbl = deepcopy(tables[4]._element)
    fill_tbl_xml(
        fb_tbl,
        [
            ["角色", "可观察的变化 / 反馈", "依据"],
            ["一线 FAE（检索）", "可按产品线×技术类目录进入，标题可读，减少在人名文件夹中翻找", "TARGET 已按产品线展开；17,092 篇标题标准化"],
            ["一线 FAE（阅读附件）", "PDF/PPT 中的步骤和配图进入页面，不必先下载附件再判断能否复用", "抽取写入「附件：」区；裂图重绑后图可打开"],
            ["作者（写作侧）", "源目录不被覆盖，日常 Sharing 不受整理任务打断", "SCAN/TARGET 双空间：只改副本"],
            ["知识运营（6 人）", "增量、去重、限流可续跑；裂图可批处理，不再逐页手工补图", "控制台+账本；17,255 篇修复任务已跑完"],
            ["待补齐的验证", "秒表对比检索耗时、小样本满意度；评分试点后的专家对照", "计划 5–10 人同一任务计时；20–30 篇黄金样本"],
        ],
    )
    fx.append(fb_tbl)
    fx.append(C("表  用户反馈与使用情况（区分已发生的使用变化与待补齐的问卷/秒表）"))
    fx.append(
        L(
            "• 写作不被打断：整理、改标题、贴元数据默认只发生在 TARGET 副本，作者继续在原目录更新现场经验。"
        )
    )
    fx.append(
        L(
            "• 检索入口从「找人」变成「找型号/技术类」：目录按 Product Line × Technical Category 展开，"
            "搜索结果标题即可判断主题、模组和作者。"
        )
    )
    fx.append(
        L(
            "• 附件可读性：复制到枢纽后曾出现大规模裂图，影响阅读与检索信心；"
            "已按 wiki 鉴权重绑约 16.9 万张图，空图块从原附件重提 698 篇。"
        )
    )
    fx.append(
        L(
            "• 库内噪声下降：周报、日报、会议纪要、客户问题跟踪不进入枢纽，检索更集中在可复用的技术案例。"
        )
    )
    fx.append(
        L(
            "• 覆盖范围：扫描清单含国内外约 20 个源目录及 Smart、GNSS 等专业团队；"
            "直接服务全球 FAE/AE 与 6 名知识枢纽运营人员。"
        )
    )
    fx.append(
        B(
            "下一步把反馈做成可重复测量：抽 5–10 名 FAE 完成同一道「找某型号同类问题」任务并秒表记录；"
            "评分试点阶段用 20–30 篇黄金样本对比 AI 与专家。测完后用实测替换第三章假设时长。"
        )
    )
    insert_after(paras[123]._element, fx)

    doc.save(DOC_PATH)
    print("saved", DOC_PATH)
    for k, v in figs.items():
        print(k, v)


if __name__ == "__main__":
    patch()
