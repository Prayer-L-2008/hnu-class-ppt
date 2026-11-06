# -*- coding: utf-8 -*-
"""生成后的排版自检：文本框越界 / 文字溢出，并尝试自动缩小字号。"""
from __future__ import annotations

import io
import os

from pptx import Presentation
from pptx.util import Emu

from .textfit import LINE_FACTOR, wrap_text


def _font_of(run, default: float = 18.0) -> tuple[float, bool, bool]:
    size = run.font.size.pt if run.font.size is not None else default
    bold = bool(run.font.bold)
    name = (run.font.name or "").lower()
    mono = "consol" in name or "courier" in name
    return float(size), bold, mono


def _para_height(p, width_pt: float, default_size: float) -> float:
    text = "".join(r.text for r in p.runs)
    if not p.runs:
        return default_size * 0.6
    size, bold, mono = _font_of(p.runs[0], default_size)
    for r in p.runs[1:]:
        s2, b2, m2 = _font_of(r, default_size)
        size = max(size, s2)
        bold = bold or b2
        mono = mono or m2
    if not text.strip():
        return size * 0.62
    lines = wrap_text(text, size, width_pt, bold, mono)
    h = len(lines) * size * (1.22 if len(lines) == 1 else 1.30)
    if p.space_before is not None:
        h += p.space_before.pt
    if p.space_after is not None:
        h += p.space_after.pt
    return h


def _frame_need(tf, box_w_emu: int) -> float:
    """返回文本框内容所需高度（pt）。"""
    ml = tf.margin_left.pt if tf.margin_left is not None else 7.2
    mr = tf.margin_right.pt if tf.margin_right is not None else 7.2
    mt = tf.margin_top.pt if tf.margin_top is not None else 3.6
    mb = tf.margin_bottom.pt if tf.margin_bottom is not None else 3.6
    width_pt = max(10.0, box_w_emu / 12700.0 - ml - mr)
    total = mt + mb
    for p in tf.paragraphs:
        total += _para_height(p, width_pt, 18.0)
    return total


def _shrink(tf, factor: float = 0.94, floor: float = 9.0) -> bool:
    changed = False
    for p in tf.paragraphs:
        for r in p.runs:
            cur = r.font.size.pt if r.font.size is not None else 18.0
            new = max(floor, cur * factor)
            if new < cur - 0.05:
                r.font.size = Emu(int(new * 12700))
                changed = True
    return changed


def audit(path: str, fix: bool = True, max_passes: int = 6) -> list[str]:
    """检查并（可选）修复越界文本框，返回问题列表。"""
    with open(path, "rb") as f:
        prs = Presentation(io.BytesIO(f.read()))
    sw, sh = prs.slide_width, prs.slide_height
    issues: list[str] = []
    seen: set[tuple[int, int]] = set()
    slides = list(prs.slides)
    changed = False

    for _ in range(max_passes):
        changed = False
        for idx, slide in enumerate(slides, 1):
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                tf = shape.text_frame
                txt = tf.text.strip()
                if not txt:
                    continue
                if shape.width < sw * 0.95:
                    if shape.left < 0:
                        shape.left = 0
                        changed = True
                    if shape.top < 0:
                        shape.top = 0
                        changed = True
                    if shape.left + shape.width > sw:
                        shape.left = Emu(max(0, sw - shape.width))
                        changed = True
                    if shape.top + shape.height > sh:
                        shape.top = Emu(max(0, sh - shape.height))
                        changed = True
                need = _frame_need(tf, shape.width)
                have = shape.height / 12700.0
                if need > have + 4.0:
                    tag = ""
                    if fix and _shrink(tf):
                        changed = True
                        tag = "，已自动缩小字号"
                    key = (idx, shape.shape_id)
                    if key not in seen:
                        seen.add(key)
                        issues.append(
                            f"第 {idx} 页文本框溢出：需要 {need:.0f}pt，实际 {have:.0f}pt（{txt[:24]}…）{tag}"
                        )
        if not changed:
            break

    if changed:
        tmp = path + ".tmp"
        prs.save(tmp)
        os.replace(tmp, path)
    return issues
