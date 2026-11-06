# -*- coding: utf-8 -*-
"""文本测量：用真实字体度量，保证排版不溢出、分页准确。"""
from __future__ import annotations

import os
from functools import lru_cache

from PIL import ImageFont

FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_MONO = r"C:\Windows\Fonts\consola.ttf"

# 一行文字的实际行高相对字号的比例（微软雅黑约 1.32）
LINE_FACTOR = 1.34


@lru_cache(maxsize=256)
def _font(size_pt: float, bold: bool = False, mono: bool = False):
    path = FONT_MONO if mono else (FONT_BOLD if bold else FONT_REG)
    if not os.path.exists(path):
        path = FONT_REG
    return ImageFont.truetype(path, max(4, int(round(size_pt * 4))))


def text_width(text: str, size_pt: float, bold: bool = False, mono: bool = False) -> float:
    """返回文本在给定字号下的宽度（单位 pt）。"""
    if not text:
        return 0.0
    return _font(size_pt, bold, mono).getlength(text) / 4.0


def line_height(size_pt: float) -> float:
    return size_pt * LINE_FACTOR


def _tokens(text: str):
    """把文本切成不可分割的排版单元：英文单词整体、中文逐字、空白整体。"""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\u3000":
            j = i
            while j < n and text[j] in " \t\u3000":
                j += 1
            out.append(text[i:j])
            i = j
        elif ch.isascii() and (ch.isalnum() or ch in "_'@#./\\:+-*=%<>[]{}()"):
            j = i
            while j < n and text[j].isascii() and (
                text[j].isalnum() or text[j] in "_'@#./\\:+-*=%<>[]{}()"
            ):
                j += 1
            out.append(text[i:j])
            i = j
        else:
            out.append(ch)
            i += 1
    return out


def wrap_text(text: str, size_pt: float, max_width_pt: float,
              bold: bool = False, mono: bool = False) -> list[str]:
    """按真实字宽换行；保留显式换行符。"""
    max_width_pt = max(8.0, max_width_pt)
    lines: list[str] = []
    for raw in text.split("\n"):
        if raw == "":
            lines.append("")
            continue
        line = ""
        for tok in _tokens(raw):
            candidate = line + tok
            if text_width(candidate, size_pt, bold, mono) <= max_width_pt or not line:
                if text_width(candidate, size_pt, bold, mono) > max_width_pt and not line:
                    # 单个超长 token：逐字符硬切
                    for ch in tok:
                        if text_width(line + ch, size_pt, bold, mono) > max_width_pt and line:
                            lines.append(line)
                            line = ch
                        else:
                            line += ch
                else:
                    line = candidate
            else:
                lines.append(line.rstrip())
                line = tok.lstrip() if tok.isspace() else tok
                while text_width(line, size_pt, bold, mono) > max_width_pt:
                    cut = len(line)
                    while cut > 1 and text_width(line[:cut], size_pt, bold, mono) > max_width_pt:
                        cut -= 1
                    lines.append(line[:cut])
                    line = line[cut:]
        if line or not lines:
            lines.append(line.rstrip())
    return lines


def block_height(text: str, size_pt: float, max_width_pt: float,
                 bold: bool = False, mono: bool = False) -> float:
    return len(wrap_text(text, size_pt, max_width_pt, bold, mono)) * line_height(size_pt)
