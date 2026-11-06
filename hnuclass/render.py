# -*- coding: utf-8 -*-
"""按「第5次小班作业覃禹嘉.pptx」的母版与版式渲染新课件。

设计原则
--------
* 母版、背景图、主题、字体全部沿用模板文件，绝不重画背景；
* 标题条、目录条、红色注记等样式参数从模板 XML 中提取后硬编码在此，
  数值与模板一致；
* 正文用真实字体度量后自动分页、自动缩字号，避免原稿“标题压正文”“目录溢出”；
* 输出仍是普通 .pptx，任何一页都可以继续手工编辑。
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.enum.dml import MSO_LINE
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Emu, Inches, Pt

from .model import CodePage, Deck, Problem
from .textfit import block_height, line_height, text_width, wrap_text

IN = 914400
YAHEI = "微软雅黑"
MONO = "Consolas"

WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0x00, 0x00, 0x00)
MAROON = RGBColor(0x58, 0x0A, 0x09)       # accent1 B01513 的 shade 50%
RED = RGBColor(0xB0, 0x15, 0x13)          # accent1
DARKGRAY = RGBColor(0x26, 0x26, 0x26)


def I(inches: float) -> Emu:
    return Emu(int(round(inches * IN)))


def _strip_style(shape) -> None:
    el = shape._element
    style = el.find(qn("p:style"))
    if style is not None:
        el.remove(style)


def _inner_shadow(shape) -> None:
    spPr = shape._element.spPr
    old = spPr.find(qn("a:effectLst"))
    if old is not None:
        spPr.remove(old)
    spPr.append(
        parse_xml(
            f'<a:effectLst {nsdecls("a")}>'
            '<a:innerShdw blurRad="63500" dist="50800" dir="18900000">'
            '<a:prstClr val="black"><a:alpha val="50000"/></a:prstClr>'
            "</a:innerShdw></a:effectLst>"
        )
    )


def _set_font(run, size: float, bold: bool = True, color: RGBColor = WHITE,
              font: str = YAHEI) -> None:
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.name = font
    f.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", font)


def _clear_tf(tf) -> None:
    """只保留第一个空段落。"""
    for p in list(tf.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    p0 = tf.paragraphs[0]
    for r in list(p0.runs):
        r._r.getparent().remove(r._r)
    return p0


def _add_para(tf, text: str, size: float, color: RGBColor = WHITE,
              bold: bool = False, font: str = YAHEI, align=PP_ALIGN.LEFT,
              spacing: float = 1.0) -> None:
    p = tf.add_paragraph()
    p.alignment = align
    p.line_spacing = spacing
    p.space_before = Pt(0)
    p.space_after = Pt(0)
    r = p.add_run()
    r.text = text
    _set_font(r, size, bold, color, font)


def _fill_para(p, text: str, size: float, color: RGBColor = WHITE,
               bold: bool = False, font: str = YAHEI, align=PP_ALIGN.LEFT,
               spacing: float = 1.0) -> None:
    p.alignment = align
    p.line_spacing = spacing
    p.space_before = Pt(0)
    p.space_after = Pt(0)
    r = p.add_run()
    r.text = text
    _set_font(r, size, bold, color, font)


@dataclass
class BodyBlock:
    text: str
    size: float | None = None       # None 表示沿用默认字号
    bold: bool = False
    mono: bool = False
    num: int | None = None          # 自动编号（1. 2. 3.）
    hang: float = 0.50              # 悬挂缩进（英寸）


class Renderer:
    def __init__(self, template_path: str):
        self.prs = Presentation(template_path)
        slides = self.prs.slides
        # 目录页左下的六边形组合图形：直接整组克隆，保证与原稿一致
        self._hex_group = copy.deepcopy(slides[1].shapes[0]._element)
        self.layout = slides[0].slide_layout      # slideLayout21（空白）
        self._drop_all_slides()

    # ------------------------------------------------------------------ 基础
    def _drop_all_slides(self) -> None:
        lst = self.prs.slides._sldIdLst
        for sld in list(lst):
            rId = sld.rId
            self.prs.part.drop_rel(rId)
            lst.remove(sld)

    def new_slide(self):
        return self.prs.slides.add_slide(self.layout)

    def save(self, path: str) -> None:
        self.prs.save(path)

    # ------------------------------------------------------------------ 组件
    def add_title(self, slide, text: str) -> None:
        size = 32.0
        max_w = 10.9          # 标题条最宽到红块前，留出安全距离
        # PIL 量出的字宽比 PowerPoint/LibreOffice 实际排版略窄，乘 1.10 兜底
        def need(sz: float) -> float:
            return text_width(text, sz, True) * 1.10 / 72.0 + 0.62
        while need(size) > max_w and size > 20:
            size -= 1
        w = max(2.2, min(max_w, need(size)))
        shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, I(0.13), I(0.156), I(w), I(0.637))
        _strip_style(shp)
        shp.fill.solid()
        shp.fill.fore_color.rgb = WHITE
        shp.line.color.rgb = MAROON
        shp.line.width = Pt(2.25)
        shp.line.dash_style = MSO_LINE.LONG_DASH_DOT
        _inner_shadow(shp)

        tf = shp.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE      # 保持原始 0.637in 高度，不随文字缩水
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = Emu(91440)
        tf.margin_right = Emu(91440)
        tf.margin_top = Emu(0)
        tf.margin_bottom = Emu(0)
        p = _clear_tf(tf)
        _fill_para(p, text, size, BLACK, True)

    def add_body(self, slide, blocks: Sequence[BodyBlock], left: float, top: float,
                 width: float, size: float, height: float | None = None) -> None:
        est = sum(
            block_height(b.text or " ", b.size or size, (width - 0.2) * 72,
                         b.bold, b.mono)
            for b in blocks
        )
        h = max(0.4, min(height or 7.0 - top - 0.2, est / 72.0 + 0.15))
        box = slide.shapes.add_textbox(I(left), I(top), I(width), I(h))
        tf = box.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        tf.vertical_anchor = MSO_ANCHOR.TOP
        first = True
        for b in blocks:
            sz = b.size or size
            txt = f"{b.num}.  {b.text}" if b.num is not None else b.text
            if first:
                p = _clear_tf(tf)
                _fill_para(p, txt, sz, WHITE, b.bold, MONO if b.mono else YAHEI)
                first = False
            else:
                _add_para(tf, txt, sz, WHITE, b.bold, MONO if b.mono else YAHEI)
                p = tf.paragraphs[-1]
            if b.num is not None or re.match(r"^\d+[.、]", b.text):
                pPr = p._p.get_or_add_pPr()
                pPr.set("marL", str(int(b.hang * IN)))
                pPr.set("indent", str(-int(b.hang * IN)))

    def add_note(self, slide, text: str) -> None:
        w = 7.05
        size = 14.0
        while text_width(text, size, False) / 72.0 > w - 0.25 and size > 10:
            size -= 1
        shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, I(5.09), I(0.23), I(w), I(0.40))
        _strip_style(shp)
        shp.fill.solid()
        shp.fill.fore_color.rgb = RED
        shp.line.fill.background()
        tf = shp.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        tf.margin_left = Emu(54864)
        tf.margin_right = Emu(36576)
        tf.margin_top = Emu(0)
        tf.margin_bottom = Emu(0)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = _clear_tf(tf)
        _fill_para(p, text, size, WHITE, False)

    # ------------------------------------------------------------------ 封面
    def cover(self, deck: Deck) -> None:
        s = self.new_slide()
        for y in (2.01, 5.49):
            ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, I(0), I(y), I(13.3333), I(y))
            ln.line.color.rgb = BLACK
            ln.line.width = Pt(1)

        box = s.shapes.add_textbox(I(0.60), I(3.76), I(12.02), I(0.91))
        tf = box.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        p = _clear_tf(tf)
        p.alignment = PP_ALIGN.CENTER
        _fill_para(p, deck.cover_title, 48, WHITE, True, YAHEI, PP_ALIGN.CENTER)

        for text, l, t, w, h, size in (
            ("POWERPOINT", 7.47, 2.65, 4.45, 0.64, 32),
        ):
            b = s.shapes.add_textbox(I(l), I(t), I(w), I(h))
            tf = b.text_frame
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
            p = _clear_tf(tf)
            _fill_para(p, text, size, WHITE, False, YAHEI, PP_ALIGN.CENTER)

        info = s.shapes.add_textbox(I(3.18), I(5.61), I(7.07), I(1.72))
        tf = info.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        lines = [
            deck.group,
            f"{deck.klass}        {deck.name}",
            f"学号：{deck.student_id}",
        ]
        for idx, line in enumerate(lines):
            p = _clear_tf(tf) if idx == 0 else tf.add_paragraph()
            _fill_para(p, line, 32, WHITE, False, YAHEI, PP_ALIGN.CENTER)

        ch = s.shapes.add_shape(MSO_SHAPE.CHEVRON, I(9.58), I(2.19), I(0.214), I(0.398))
        _strip_style(ch)
        ch.rotation = 90
        ch.fill.solid()
        ch.fill.fore_color.rgb = DARKGRAY
        ch.line.fill.background()

    # ------------------------------------------------------------------ 目录
    def toc(self, deck: Deck) -> None:
        s = self.new_slide()
        grp = copy.deepcopy(self._hex_group)
        s.shapes._spTree.append(grp)
        self._renumber(grp, 900)

        box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, I(9.16), I(0.62), I(2.15), I(1.01))
        _strip_style(box)
        box.fill.solid()
        box.fill.fore_color.rgb = WHITE
        box.line.color.rgb = MAROON
        box.line.width = Pt(2.25)
        box.line.dash_style = MSO_LINE.LONG_DASH_DOT
        _inner_shadow(box)
        tf = box.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        p = _clear_tf(tf)
        _fill_para(p, "目录", 54, BLACK, True, YAHEI, PP_ALIGN.CENTER)

        items = [p.display_name for p in deck.problems]
        n = len(items)
        top, bottom = 1.97, 7.16
        step = min(0.775, (bottom - top) / max(1, n))
        h = min(0.64, step - 0.12)
        if n * step < bottom - top:
            top += ((bottom - top) - n * step) / 2
        for i, text in enumerate(items):
            size = 32.0
            line = f"{i+1:02d} / {text}"
            # 与标题条同理：PIL 量宽偏窄，乘 1.10；放不下就缩字号，保证单行不压框
            while size > 16 and text_width(line, size, True) * 1.10 / 72.0 + 0.30 > 7.90:
                size -= 1
            shp = s.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, I(4.78), I(top + i * step), I(8.05), I(h)
            )
            _strip_style(shp)
            shp.fill.solid()
            shp.fill.fore_color.rgb = WHITE
            shp.line.color.rgb = MAROON
            shp.line.width = Pt(2.25)
            shp.line.dash_style = MSO_LINE.LONG_DASH_DOT
            _inner_shadow(shp)
            tf = shp.text_frame
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.NONE
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf.margin_left = Emu(91440)
            tf.margin_top = Emu(0)
            tf.margin_bottom = Emu(0)
            p = _clear_tf(tf)
            _fill_para(p, line, size, BLACK, True, YAHEI)

    @staticmethod
    def _renumber(el, start: int) -> None:
        n = start
        for c in el.iter():
            if c.tag in (qn("p:cNvPr"),):
                c.set("id", str(n))
                n += 1

    # ------------------------------------------------------------------ 分页
    @staticmethod
    def _paginate(blocks: Sequence[BodyBlock], width_in: float, height_in: float,
                  size: float) -> list[list[BodyBlock]]:
        width_pt = (width_in - 0.2) * 72
        max_h = height_in * 72
        pages: list[list[BodyBlock]] = [[]]
        used = 0.0
        for b in blocks:
            sz = b.size or size
            h = block_height(b.text or " ", sz, width_pt, b.bold, b.mono)
            if used + h > max_h and pages[-1]:
                pages.append([])
                used = 0.0
            if h > max_h:  # 单段就超过一整页：按行硬切
                lines = wrap_text(b.text, sz, width_pt, b.bold, b.mono)
                per = max(1, int(max_h // line_height(sz)))
                for i in range(0, len(lines), per):
                    chunk = "\n".join(lines[i:i + per])
                    if pages[-1]:
                        pages.append([])
                    pages[-1].append(BodyBlock(chunk, b.size, b.bold, b.mono))
                    used = max_h
                continue
            pages[-1].append(b)
            used += h
        return [p for p in pages if p]

    def _pick_size(self, blocks, width_in, height_in, sizes=(18, 17, 16, 15, 14)) -> float:
        for sz in sizes:
            pages = self._paginate(blocks, width_in, height_in, sz)
            if len(pages) <= 3:
                return sz
        return sizes[-1]

    # ------------------------------------------------------------------ 题目
    def _problem_blocks(self, p: Problem) -> list[BodyBlock]:
        blocks: list[BodyBlock] = [BodyBlock("【问题描述】")]
        desc = (p.description or "").strip()
        if desc:
            blocks.append(BodyBlock(""))
            for para in desc.split("\n"):
                blocks.append(BodyBlock(para))
        if p.input_form.strip():
            blocks += [BodyBlock(""), BodyBlock("【输入形式】"), BodyBlock(""),
                       *[BodyBlock(x) for x in p.input_form.strip().split("\n")]]
        if p.output_form.strip():
            blocks += [BodyBlock(""), BodyBlock("【输出形式】"), BodyBlock(""),
                       *[BodyBlock(x) for x in p.output_form.strip().split("\n")]]
        if not desc and not p.input_form and not p.output_form:
            blocks.append(BodyBlock("（题目内容为空，请检查抓取结果或手工补充。）"))
        return blocks

    def problem_pages(self, p: Problem) -> None:
        if p.images and not p.description.strip():
            # 截图型题面：一页放一张，等比缩放居中
            for idx, img in enumerate(p.images):
                if not os.path.exists(img):
                    continue
                s = self.new_slide()
                suffix = f"（P{idx+1}）" if len(p.images) > 1 else ""
                self.add_title(s, f"{p.number}、问题-{p.display_name}{suffix}")
                self._add_picture_fit(s, img, 0.59, 0.95, 12.15, 6.35)
            return
        blocks = self._problem_blocks(p)
        width, top = 11.35, 1.04
        height = 7.15 - top
        size = self._pick_size(blocks, width, height)
        pages = self._paginate(blocks, width, height, size)
        for i, page in enumerate(pages):
            s = self.new_slide()
            suffix = f"（P{i+1}）" if len(pages) > 1 else ""
            self.add_title(s, f"{p.number}、问题-{p.display_name}{suffix}")
            self.add_body(s, page, 1.04, top, width, size, height)

    def _add_picture_fit(self, slide, path: str, l: float, t: float, w: float, h: float) -> None:
        from PIL import Image

        with Image.open(path) as im:
            iw, ih = im.size
        scale = min(w / iw, h / ih)
        pw, ph = iw * scale, ih * scale
        left = l + (w - pw) / 2
        top = t + (h - ph) / 2
        slide.shapes.add_picture(path, I(left), I(top), I(pw), I(ph))

    def analysis_pages(self, p: Problem) -> None:
        paras = [x for x in (p.analysis or []) if x.strip()]
        if not paras:
            paras = ["（思路分析待补充：配置 LLM API 后将自动生成。）"]
        blocks: list[BodyBlock] = []
        numbered = bool(re.match(r"^\s*\d+[.、]", paras[0]))
        for i, para in enumerate(paras):
            if i:
                blocks.append(BodyBlock(""))
            blocks.append(BodyBlock(para, num=None if numbered else i + 1))
        width, top = 11.35, 1.04
        height = 7.15 - top
        size = self._pick_size(blocks, width, height, (20, 19, 18, 17, 16, 15, 14))
        pages = self._paginate(blocks, width, height, size)
        for i, page in enumerate(pages):
            s = self.new_slide()
            suffix = f"（P{i+1}）" if len(pages) > 1 else ""
            self.add_title(s, f"{p.number}-思路分析及原理{suffix}")
            self.add_body(s, page, 1.04, top, width, size, height)

    def code_pages(self, p: Problem) -> None:
        pages = p.code_pages or [
            CodePage(heading="", bullets=["（代码逐行讲解待补充：配置 LLM API 后将自动生成。）"])
        ]
        multi = len(pages) > 1
        for idx, cp in enumerate(pages):
            s = self.new_slide()
            suffix = f" (P{idx+1})" if multi else ""
            self.add_title(s, f"{p.number}-代码逐行讲解{suffix}")
            if cp.note.strip():
                self.add_note(s, cp.note.strip())
            blocks: list[BodyBlock] = []
            if cp.heading.strip():
                blocks.append(BodyBlock(cp.heading.strip(), bold=True))
            numbered = 0
            for b in cp.bullets:
                text = str(b).strip()
                if not text:
                    continue
                if re.match(r"^\d+[.、]", text):
                    blocks.append(BodyBlock(text, hang=0.42))
                else:
                    numbered += 1
                    blocks.append(BodyBlock(text, num=numbered, hang=0.42))
            top = 1.05 if cp.note.strip() else 0.83
            width = 10.27
            height = 7.15 - top
            size = self._pick_size(blocks, width, height, (18, 17, 16, 15, 14))
            pages_split = self._paginate(blocks, width, height, size)
            # 讲解页一般一页装得下；若超长，追加同标题页面
            for k, page in enumerate(pages_split):
                if k == 0:
                    self.add_body(s, page, 1.53, top, width, size, height)
                else:
                    s2 = self.new_slide()
                    self.add_title(s2, f"{p.number}-代码逐行讲解{suffix}")
                    self.add_body(s2, page, 1.53, top, width, size, height)

    def case_page(self, p: Problem) -> None:
        s = self.new_slide()
        self.add_title(s, f"{p.number}-用例及运行结果")
        case1 = p.samples[0] if p.samples else None
        case2 = p.samples[1] if len(p.samples) > 1 else None

        def case_text(title: str, c) -> str:
            if c is None:
                return f"{title}：\n\t（无）"
            body = c.input.strip("\n")
            return f"{title}：\n\t" + body.replace("\n", "\n\t") if body else f"{title}："

        blocks1 = [BodyBlock(x) for x in case_text("用例1", case1).split("\n")]
        self.add_body(s, blocks1, 1.85, 1.46, 6.15, 18, 2.6)
        if case2:
            blocks2 = [BodyBlock(x) for x in case_text("用例2", case2).split("\n")]
            self.add_body(s, blocks2, 1.85, 4.70, 6.15, 18, 1.95)

        out1 = (case1.output if case1 else "") or p.run_output
        out2 = (case2.output if case2 else "") or ""
        self._console(s, 8.35, 1.46, 4.45, 5.2 if not (case2 or out2) else 2.6, out1)
        if case2 or out2:
            self._console(s, 8.35, 4.70, 4.45, 1.95, out2)

        if p.tips.strip():
            self.add_body(s, [BodyBlock(p.tips.strip(), size=14)], 1.13, 6.82, 11.31, 14, 0.5)

    def _console(self, slide, l: float, t: float, w: float, h: float, text: str) -> None:
        raw = (text or "").strip("\n")
        lines = raw.split("\n") if raw else [""]
        nlines = len(lines) + sum(max(0, len(x) // 46) for x in lines)
        body_h = min(max(0.30, nlines * 0.185 + 0.22), h - 0.30)
        h = body_h + 0.30

        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, I(l), I(t), I(w), I(h))
        _strip_style(panel)
        panel.fill.solid()
        panel.fill.fore_color.rgb = RGBColor(0x12, 0x12, 0x12)
        panel.line.color.rgb = RGBColor(0x4A, 0x4A, 0x4A)
        panel.line.width = Pt(0.75)
        panel.adjustments[0] = 0.04

        bar = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, I(l), I(t), I(w), I(0.28))
        _strip_style(bar)
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(0x24, 0x24, 0x24)
        bar.line.fill.background()
        bar.adjustments[0] = 0.12
        for k, color in enumerate((0xE0, 0x5A, 0x52)):
            dot = slide.shapes.add_shape(
                MSO_SHAPE.OVAL, I(l + 0.10 + k * 0.14), I(t + 0.095), I(0.075), I(0.075))
            _strip_style(dot)
            dot.fill.solid()
            dot.fill.fore_color.rgb = RGBColor(
                (0xE0, 0xE0, 0x3F)[k], (0x5A, 0xBD, 0xBD)[k], (0x52, 0x44, 0x44)[k])
            dot.line.fill.background()

        label = slide.shapes.add_textbox(I(l + 0.55), I(t + 0.015), I(w - 0.7), I(0.24))
        tf = label.text_frame
        tf.margin_left = 0
        tf.margin_top = 0
        tf.margin_bottom = 0
        tf.word_wrap = False
        pp = _clear_tf(tf)
        _fill_para(pp, "运行结果", 9, RGBColor(0x9A, 0x9A, 0x9A), False, YAHEI)

        area = slide.shapes.add_textbox(I(l + 0.02), I(t + 0.32), I(w - 0.04), I(h - 0.34))
        tf = area.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.margin_left = Emu(64008)
        tf.margin_right = Emu(45720)
        tf.margin_top = Emu(27432)
        tf.margin_bottom = Emu(18288)
        tf.vertical_anchor = MSO_ANCHOR.TOP
        first = True
        for line in lines[:22]:
            pp = _clear_tf(tf) if first else tf.add_paragraph()
            first = False
            _fill_para(pp, line, 10.5, RGBColor(0xE8, 0xE8, 0xE8), False, MONO)

    # ------------------------------------------------------------------ 总结
    def summary_page(self, deck: Deck) -> None:
        s = self.new_slide()
        self.add_title(s, "小班分析与总结")
        points = deck.summary or [
            "理解题目背后的算法思想，比记住一份代码更重要；先想清楚“为什么”，再动手写“怎么写”。",
            "善用调试与用例验证：先跑通样例，再构造边界数据，养成自己检查程序的好习惯。",
            "把本讲的方法迁移到同类问题中，多总结、多复盘，才能真正把知识变成自己的能力。",
        ]
        blocks: list[BodyBlock] = []
        for i, p in enumerate(points):
            if i:
                blocks.append(BodyBlock(""))
            blocks.append(BodyBlock(p, num=i + 1, hang=0.45))
        self.add_body(s, blocks, 0.36, 1.67, 12.61, 20, 5.0)

    # ------------------------------------------------------------------ 生成
    def render(self, deck: Deck) -> None:
        for i, p in enumerate(deck.problems, 1):
            p.number = i
        self.cover(deck)
        self.toc(deck)
        for p in deck.problems:
            self.problem_pages(p)
            self.analysis_pages(p)
            self.code_pages(p)
            if p.samples or p.run_output:
                self.case_page(p)
        self.summary_page(deck)


def render_deck(deck: Deck, out_path: str, template_path: str) -> str:
    r = Renderer(template_path)
    r.render(deck)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    r.save(out_path)
    return out_path
