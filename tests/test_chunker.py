"""结构感知分块（§4.3）：按标题分节、token 预算、overlap、seq 单调。"""

from app.knowledge.chunker import _count_tokens, chunk_markdown

MARKDOWN = """# 退货政策
## 退货条件
商品需在签收后 30 天内申请退货，包装完整不影响二次销售。

## 退款到账时间
退款在审核通过后 3-5 个工作日内原路退回。

## 退货运费
质量问题商家承担运费，其他情况买家承担。
"""


def test_sections_preserved():
    pieces = chunk_markdown(MARKDOWN)
    # 顶级 "# 退货政策" 无直接内容 => 不产生空 piece；只保留有内容的子节
    sections = {p.section for p in pieces}
    assert sections == {"退货条件", "退款到账时间", "退货运费"}


def test_seq_monotonic_unique():
    pieces = chunk_markdown(MARKDOWN)
    seqs = [p.seq for p in pieces]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_no_headings_means_single_section():
    pieces = chunk_markdown("这是没有标题的纯文本。\n第二行内容。", max_tokens=100)
    assert pieces and all(p.section == "" for p in pieces)


def test_chunks_respect_budget():
    long_text = "\n".join(f"这是第{i}行内容，包含一些词语用来凑字数达到预算。" for i in range(50))
    pieces = chunk_markdown(long_text, max_tokens=30, overlap_tokens=5)
    assert len(pieces) >= 2
    for p in pieces:
        assert _count_tokens(p.text) <= 30  # 单行 ~17 token，整块不超预算


def test_overlap_carries_previous_content():
    long_text = "\n".join(f"段落内容第{i}行，用于测试上下文衔接不丢失。" for i in range(30))
    pieces = chunk_markdown(long_text, max_tokens=25, overlap_tokens=10)
    assert len(pieces) >= 2
    # 后一块应包含前一块末尾的部分行（overlap），保证跨块语义不切断
    joined = pieces[1].text
    assert any(f"段落内容第{i}行" in joined for i in range(0, 5))
