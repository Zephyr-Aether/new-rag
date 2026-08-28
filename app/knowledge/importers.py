"""知识库文档导入（文件上传解析）：TXT/Markdown/PDF → 文本；CSV/Excel → FAQ 问答对。

FAQ 文件每行（问题, 答案）转为 `## 问：…\n答：…` 小节，配合现有 Markdown 分块器按小节切块。
上传文本先经 clean_document 清洗（去噪/规范化），再入库。
"""

import csv
import io
import re

_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB

# 常见噪音：独立页码行（- 1 - / — 3 — / 第 1 页 / 页 3 / 纯数字）、分隔线、PDF 页眉页脚
_PAGE_NO_RE = re.compile(
    r"^\s*(?:[-—–_]{1,}\s*\d+\s*[-—–_]{1,}|第\s*\d+\s*页|页\s*\d+|\d+\s*/\s*\d+|\d{1,4})\s*$"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH_RE = re.compile(r"[​-‍⁠﻿]")
_WS_LINE_RE = re.compile(r"[ \t]+$")


def clean_document(text: str) -> str:
    """文档清洗：统一换行、去控制字符/零宽、去独立页码行、压缩空行与行尾空格。"""
    text = _ZERO_WIDTH_RE.sub("", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    lines = []
    for line in text.split("\n"):
        line = _WS_LINE_RE.sub("", line).strip()
        if not line:
            lines.append("")
            continue
        if _PAGE_NO_RE.match(line):
            continue
        lines.append(line)
    # 压缩连续空行（最多 1 个）
    out: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                out.append("")
            prev_blank = True
        else:
            out.append(line)
            prev_blank = False
    return "\n".join(out).strip()


class ImportError_(Exception):
    pass


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 单页失败跳过
            text = ""
        if text.strip():
            pages.append(text)
    return "\n\n".join(pages)


def _rows_to_faq_markdown(rows: list[list[str]]) -> str:
    blocks = []
    for row in rows:
        if len(row) < 2 or not (row[0] or "").strip():
            continue
        q, a = (row[0] or "").strip(), (row[1] or "").strip()
        blocks.append(f"## 问：{q}\n答：{a}")
    return "\n\n".join(blocks)


def _parse_csv(data: bytes) -> str:
    text = _decode(data)
    rows = list(csv.reader(io.StringIO(text)))
    return _rows_to_faq_markdown(rows)


def _parse_excel(data: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows = [[(c if c is not None else "") for c in row] for row in ws.iter_rows(values_only=True)]
    return _rows_to_faq_markdown(rows)


def parse_document(filename: str, data: bytes) -> str:
    """按扩展名解析上传文件为 Markdown 文本，并做文档清洗。返回空串表示无可提取内容。"""
    if len(data) > _MAX_FILE_BYTES:
        raise ImportError_(f"file too large: {len(data)} > {_MAX_FILE_BYTES}")
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            text = _parse_pdf(data)
        elif name.endswith(".csv"):
            text = _parse_csv(data)
        elif name.endswith(".xlsx") or name.endswith(".xls"):
            text = _parse_excel(data)
        else:
            text = _decode(data)  # txt / md / 其它按文本
    except Exception as exc:  # noqa: BLE001
        raise ImportError_(f"parse failed: {exc}") from exc
    return clean_document(text)
