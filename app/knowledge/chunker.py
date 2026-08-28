"""结构感知分块（§4.3）：按 Markdown 标题分节，节内按 token 预算切块 + overlap。"""

from pydantic import BaseModel

from app.knowledge.embedding import tokenize


class ChunkPiece(BaseModel):
    text: str
    section: str
    seq: int


def _count_tokens(text: str) -> int:
    return len(tokenize(text))


def _split_into_lines(text: str) -> list[str]:
    return text.splitlines()


def _is_heading(line: str) -> bool:
    s = line.strip()
    return s.startswith("#") and bool(s.lstrip("#").strip())


def _chunk_lines(lines: list[str], max_tokens: int, overlap_tokens: int) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for line in lines:
        t = _count_tokens(line)
        if cur and cur_tokens + t > max_tokens:
            chunks.append("\n".join(cur))
            # overlap：保留末尾若干行（不超过 overlap_tokens）
            carry: list[str] = []
            carry_tokens = 0
            for prev in reversed(cur):
                pt = _count_tokens(prev)
                if carry_tokens + pt > overlap_tokens:
                    break
                carry.insert(0, prev)
                carry_tokens += pt
            cur = carry
            cur_tokens = carry_tokens
        cur.append(line)
        cur_tokens += t
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def chunk_markdown(text: str, *, max_tokens: int = 400, overlap_tokens: int = 50) -> list[ChunkPiece]:
    """按标题分节，节内按预算切块。无标题则整篇一节。"""
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    buf: list[str] = []
    for line in _split_into_lines(text):
        if _is_heading(line):
            if buf:
                sections.append((current_title, buf))
                buf = []
            current_title = line.strip().lstrip("#").strip()
        else:
            buf.append(line)
    if buf:
        sections.append((current_title, buf))

    pieces: list[ChunkPiece] = []
    seq = 0
    for title, lines in sections:
        for block in _chunk_lines(lines, max_tokens, overlap_tokens):
            if not block.strip():
                continue
            pieces.append(ChunkPiece(text=block, section=title, seq=seq))
            seq += 1
    return pieces
