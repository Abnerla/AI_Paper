# -*- coding: utf-8 -*-
"""LaTeX 数学公式渲染工具。

把段落文本中的 LaTeX 数学片段切分出来，并通过 matplotlib mathtext
将单个 LaTeX 表达式渲染成 PIL 图像，供 Tkinter Text 控件嵌入显示。
"""

from __future__ import annotations

import io
import re
from functools import lru_cache
from typing import Iterator, Optional, Tuple

from PIL import Image


# 顺序敏感：先匹配多字符显式分隔符 \[...\] / \(...\)，再匹配 $$...$$ / $...$。
_MATH_PATTERN = re.compile(
    r'(?<!\\)\\\[(?P<display_bracket>.+?)(?<!\\)\\\]'
    r'|(?<!\\)\\\((?P<inline_paren>.+?)(?<!\\)\\\)'
    r'|(?<!\\)\$\$(?P<display_dollar>.+?)(?<!\\)\$\$'
    r'|(?<!\\)\$(?P<inline_dollar>[^\n$]+?)(?<!\\)\$',
    re.DOTALL,
)


def iter_math_segments(text: str) -> Iterator[Tuple[str, str]]:
    """把段落文本切成 (kind, content) 序列。

    kind 取值：'text'、'inline_math'、'display_math'。
    text 中的 LaTeX 分隔符不会出现在返回的 content 中（仅返回内部表达式）。
    """
    if not text:
        return
    cursor = 0
    for match in _MATH_PATTERN.finditer(text):
        if match.start() > cursor:
            yield 'text', text[cursor:match.start()]
        if match.group('display_bracket') is not None:
            yield 'display_math', match.group('display_bracket').strip()
        elif match.group('inline_paren') is not None:
            yield 'inline_math', match.group('inline_paren').strip()
        elif match.group('display_dollar') is not None:
            yield 'display_math', match.group('display_dollar').strip()
        elif match.group('inline_dollar') is not None:
            yield 'inline_math', match.group('inline_dollar').strip()
        cursor = match.end()
    if cursor < len(text):
        yield 'text', text[cursor:]


def wrap_math_source(latex: str, *, display: bool) -> str:
    """把 LaTeX 表达式包裹成原始分隔符形式，用于 round-trip。"""
    if display:
        return f'\\[{latex}\\]'
    return f'\\({latex}\\)'


@lru_cache(maxsize=512)
def _render_cached(
    latex: str,
    font_size: int,
    fg_color: str,
    bg_color: str,
    display: bool,
    dpi: int,
) -> Optional[bytes]:
    try:
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib import mathtext
        from matplotlib import rcParams
        from matplotlib.font_manager import FontProperties
    except Exception:
        return None

    rcParams['mathtext.fontset'] = 'cm'
    expression = f'${latex}$'
    effective_font_size = font_size + (2 if display else 0)
    try:
        buf = io.BytesIO()
        if hasattr(mathtext, 'math_to_image'):
            mathtext.math_to_image(
                expression,
                buf,
                prop=FontProperties(size=effective_font_size),
                dpi=dpi,
                format='png',
                color=fg_color,
            )
        else:
            parser = mathtext.MathTextParser('agg')
            parser.to_png(
                buf,
                expression,
                color=fg_color,
                fontsize=effective_font_size,
                dpi=dpi,
            )
        return buf.getvalue()
    except Exception:
        return None


def render_latex_to_image(
    latex: str,
    *,
    font_size: int = 14,
    fg_color: str = '#222222',
    bg_color: str = '#FFFFFF',
    display: bool = False,
    dpi: int = 150,
) -> Optional[Image.Image]:
    """把 LaTeX 表达式渲染成 PIL 图像；失败时返回 None。"""
    if not latex or not latex.strip():
        return None
    png_bytes = _render_cached(
        latex.strip(),
        int(font_size),
        str(fg_color),
        str(bg_color),
        bool(display),
        int(dpi),
    )
    if png_bytes is None:
        return None
    try:
        image = Image.open(io.BytesIO(png_bytes))
        image.load()
    except Exception:
        return None
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    if bg_color and bg_color.upper() not in ('', 'NONE', 'TRANSPARENT'):
        background = Image.new('RGBA', image.size, _hex_to_rgba(bg_color))
        background.alpha_composite(image)
        image = background
    return image


def _hex_to_rgba(color: str) -> Tuple[int, int, int, int]:
    value = (color or '').strip().lstrip('#')
    if len(value) == 6:
        try:
            r = int(value[0:2], 16)
            g = int(value[2:4], 16)
            b = int(value[4:6], 16)
            return r, g, b, 255
        except ValueError:
            pass
    return 255, 255, 255, 255
