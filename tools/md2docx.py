"""把 Markdown 转成 Word（.docx），给参赛材料用。

为什么自己写而不是装 pandoc：参赛报告要的是**能直接交的中文排版**——
正文宋体、标题黑体、表格有框线。pandoc 出来的默认样式全是西文字体，
中文字号行距都要手工再调一遍，不如在这里一次设好。

只支持本项目的文档实际用到的那几种语法，不做通用 Markdown：

    # ## ### ####   标题
    普通段落
    - 无序列表  /  1. 有序列表
    ``` 代码块 ```
    > 引用（渲染成缩进的灰底段落）
    | a | b |        表格（第二行必须是 |---|---|）
    **粗体**  `等宽`

用法：

    python tools/md2docx.py docs/技术方案.md
    # 输出 docs/技术方案.docx
"""

import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

BODY_FONT = "宋体"
HEAD_FONT = "黑体"
MONO_FONT = "Consolas"
BODY_SIZE = Pt(10.5)          # 五号
MONO_SIZE = Pt(9)

# 标题层级 -> 字号
HEAD_SIZE = {1: Pt(18), 2: Pt(15), 3: Pt(13), 4: Pt(11.5)}


def set_run(run, name=BODY_FONT, size=BODY_SIZE, bold=None, color=None):
    """设字体。中文必须额外写 w:eastAsia，只设 font.name 对中文不生效。"""
    run.font.name = name
    run.font.size = size
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run._element.rPr.rFonts.set(qn("w:ascii"), name)


# 行内：**粗体** 和 `等宽`。按捕获组切开，奇数下标是标记内容。
INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def add_inline(par, text, base_font=BODY_FONT, base_size=BODY_SIZE):
    for piece in INLINE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            set_run(par.add_run(piece[2:-2]), base_font, base_size, bold=True)
        elif piece.startswith("`") and piece.endswith("`"):
            set_run(par.add_run(piece[1:-1]), MONO_FONT, MONO_SIZE)
        else:
            set_run(par.add_run(piece), base_font, base_size)


def add_code_block(doc, lines):
    """代码块：等宽字体 + 浅灰底。用单元格当容器比段落底纹省事。"""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.style = "Table Grid"
    cell = tbl.cell(0, 0)
    cell.paragraphs[0].text = ""
    for i, ln in enumerate(lines):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        set_run(p.add_run(ln), MONO_FONT, MONO_SIZE)
    doc.add_paragraph()


def add_table(doc, rows):
    """rows: list[list[str]]，第一行是表头。** 和 ` 也在这里解析。"""
    n_col = max(len(r) for r in rows)
    tbl = doc.add_table(rows=len(rows), cols=n_col)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j in range(n_col):
            cell = tbl.cell(i, j)
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            text = row[j] if j < len(row) else ""
            # 表头居中，正文左对齐
            if i == 0:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            # 单元格里的 <br> 当成换行，否则整行会串成一句
            for k, seg in enumerate(text.split("<br>")):
                if k:
                    p.add_run().add_break()
                add_inline(p, seg, base_size=Pt(9))
                if i == 0:
                    for r in p.runs:
                        r.font.bold = True
    doc.add_paragraph()


def split_row(line):
    """| a | b | -> ['a', 'b']"""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_sep_row(line):
    return bool(re.fullmatch(r"\|[\s:\-|]+\|", line.strip()))


def convert(md_text, doc):
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # 代码块
        if s.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            add_code_block(doc, buf or [""])
            continue

        # 表格：当前行是 |...| 且下一行是分隔行
        if s.startswith("|") and i + 1 < len(lines) and is_sep_row(lines[i + 1]):
            rows = [split_row(s)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            add_table(doc, rows)
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lv = len(m.group(1))
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12 if lv <= 2 else 8)
            p.paragraph_format.space_after = Pt(6)
            add_inline(p, m.group(2), base_font=HEAD_FONT, base_size=HEAD_SIZE[lv])
            for r in p.runs:
                r.font.bold = True
            i += 1
            continue

        # 分隔线
        if re.fullmatch(r"-{3,}", s):
            i += 1
            continue

        # 引用
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            add_inline(p, " ".join(buf))
            for r in p.runs:
                r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            continue

        # 列表
        m = re.match(r"^([-*]|\d+\.)\s+(.*)$", s)
        if m:
            ordered = m.group(1)[0].isdigit()
            p = doc.add_paragraph(style="List Number" if ordered else "List Bullet")
            add_inline(p, m.group(2))
            i += 1
            continue

        # 空行
        if not s:
            i += 1
            continue

        # 普通段落
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.25
        add_inline(p, s)
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md", help="输入的 .md")
    ap.add_argument("-o", "--out", default=None, help="输出的 .docx，默认同名同目录")
    args = ap.parse_args()

    src = Path(args.md)
    dst = Path(args.out) if args.out else src.with_suffix(".docx")

    doc = Document()
    # 正文默认样式也设一遍，否则新段落会回落到西文字体
    st = doc.styles["Normal"]
    st.font.name = BODY_FONT
    st.font.size = BODY_SIZE
    st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    convert(src.read_text(encoding="utf-8"), doc)
    doc.save(dst)
    print(f"{src} -> {dst}")


if __name__ == "__main__":
    main()
