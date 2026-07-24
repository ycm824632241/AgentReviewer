"""
RAG 检索模块 v2：真正的向量检索（Gitee AI Qwen3-Embedding-4B）。

解决的问题：
1. 长论文 token 溢出 —— 每次只取最相关的 chunk
2. 审稿-quality —— 语义检索比关键词匹配更精准
3. 费用 —— 减少 60-80% token 消耗

技术栈：
- Embedding: Qwen3-Embedding-4B (1024 维, Gitee AI)
- 向量检索: 余弦相似度（纯 Python，无需 FAISS）
- 分块: 按章节边界 + 段落边界，~1000 字/块
"""
import re
import os
from typing import List
from dotenv import load_dotenv
from paper_reviewer.config import get_env_path, get_env_value

# 加载 .env
load_dotenv(dotenv_path=get_env_path())

from openai import OpenAI

_EMBED_MODEL = get_env_value("EMBEDDING_MODEL", "GITEE_EMBED_MODEL", "Qwen3-Embedding-4B")
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 150
_TOP_K = 5        # 短论文的默认值
_TOP_K_MAX = 20  # 长论文的上限（防止输入过多）
_CHUNK_MAX_BYTES = 12 * 1024
_EMBED_BATCH_MAX_ITEMS = 16
_EMBED_BATCH_MAX_BYTES = 18 * 1024


def _split_long_text(text: str, size: int, overlap: int) -> List[str]:
    """Split a paragraph that has no natural breaks using a bounded sliding window."""
    if len(text) <= size:
        return [text]

    step = max(1, size - overlap)
    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start:start + size].strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks


def _split_text_by_byte_limit(text: str, max_bytes: int) -> List[str]:
    """Split text so every piece is within the UTF-8 byte limit."""
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    chunks = []
    current = []
    current_bytes = 0
    for char in text:
        char_bytes = len(char.encode("utf-8"))
        if current and current_bytes + char_bytes > max_bytes:
            chunks.append("".join(current))
            current = []
            current_bytes = 0
        current.append(char)
        current_bytes += char_bytes

    if current:
        chunks.append("".join(current))
    return chunks


def _enforce_chunk_limits(chunks: List[str], max_bytes: int = None) -> List[str]:
    """Validate and split chunks again after natural-boundary chunking."""
    max_bytes = max_bytes or _CHUNK_MAX_BYTES
    bounded: List[str] = []
    for chunk in chunks:
        bounded.extend(_split_text_by_byte_limit(chunk, max_bytes))
    return [chunk for chunk in bounded if chunk.strip()]


def _select_fallback_chunks(chunks: List[str], limit: int) -> List[str]:
    """Select a deterministic spread of chunks when semantic retrieval is unavailable."""
    if len(chunks) <= limit:
        return chunks
    if limit <= 1:
        return chunks[:1]

    selected_indexes = []
    seen = set()
    max_index = len(chunks) - 1
    for i in range(limit):
        idx = round(i * max_index / (limit - 1))
        if idx not in seen:
            selected_indexes.append(idx)
            seen.add(idx)

    idx = 0
    while len(selected_indexes) < limit and idx < len(chunks):
        if idx not in seen:
            selected_indexes.append(idx)
            seen.add(idx)
        idx += 1

    return [chunks[i] for i in sorted(selected_indexes)]


def _text_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _batch_texts(
    texts: List[str],
    max_items: int = None,
    max_bytes: int = None,
) -> List[List[str]]:
    """Split embedding input into bounded batches while preserving order."""
    max_items = max_items or _EMBED_BATCH_MAX_ITEMS
    max_bytes = max_bytes or _EMBED_BATCH_MAX_BYTES
    batches: List[List[str]] = []
    current: List[str] = []
    current_bytes = 0

    bounded_texts: List[str] = []
    for text in texts:
        bounded_texts.extend(_split_text_by_byte_limit(text, max_bytes))

    for text in bounded_texts:
        text_bytes = _text_bytes(text)
        would_exceed_items = len(current) >= max_items
        would_exceed_bytes = current and current_bytes + text_bytes > max_bytes
        if would_exceed_items or would_exceed_bytes:
            batches.append(current)
            current = []
            current_bytes = 0

        current.append(text)
        current_bytes += text_bytes

    if current:
        batches.append(current)
    return batches


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[str]:
    """按段落边界切块（优先在章节标题和段落间切分）。"""
    # 支持中英文标题格式：1. Introduction / 一、引言 / 第一章 绪论 / 摘要 等
    # 策略：匹配行首的章节编号或常见标题关键词
    section_pattern = (
        r"(?:^|\n)\s*"                          # 行首
        r"(?:"
        r"第?[一二三四五六七八九十百千零\d]+"    # 中文/阿拉伯数字
        r"[章节篇节部分\.、\s]"                  # 分隔符（章、节、第、.、、、空格）
        r"|Abstract|Introduction|Conclusion"    # 英文标题
        r"|摘要|引言|绪论|背景|方法|实验|结果|讨论|结论|总结|展望|致谢|参考文献"  # 中文标题
        r"|Section\s+\d+"                       # Section 格式
        r")"
    )
    sections = re.split(section_pattern, text, flags=re.MULTILINE | re.IGNORECASE)
    sections = [s.strip() for s in sections if s.strip()]

    chunks = []
    for section in sections:
        if len(section) <= size:
            chunks.append(section)
        else:
            paragraphs = re.split(r"\n\s*\n", section)
            current = ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if len(para) > size:
                    if current:
                        chunks.append(current.strip())
                        current = ""
                    chunks.extend(_split_long_text(para, size, overlap))
                    continue
                if len(current) + len(para) <= size:
                    current += para + "\n"
                else:
                    if current:
                        chunks.append(current.strip())
                    current = para + "\n"
            if current:
                chunks.append(current.strip())

    # 合并过短的相邻 chunk
    merged = []
    for chunk in chunks:
        if merged and len(merged[-1]) < size // 2:
            merged[-1] += "\n" + chunk
        else:
            merged.append(chunk)

    return _enforce_chunk_limits(merged if merged else [text])


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed(texts: List[str]) -> List[List[float]]:
    """批量获取 embedding 向量。"""
    client = OpenAI(
        api_key=get_env_value("EMBEDDING_API_KEY", "GITEE_API_KEY", "") or "",
        base_url=get_env_value("EMBEDDING_BASE_URL", "GITEE_BASE_URL", "https://ai.gitee.com/v1"),
    )
    model = get_env_value("EMBEDDING_MODEL", "GITEE_EMBED_MODEL", _EMBED_MODEL)
    embeddings: List[List[float]] = []
    for batch in _batch_texts(texts):
        resp = client.embeddings.create(model=model, input=batch)
        embeddings.extend(item.embedding for item in resp.data)
    return embeddings


class PaperIndex:
    """论文向量索引：分块 + embedding + 语义检索。"""

    def __init__(self, paper_text: str):
        self.chunks = _chunk_text(paper_text, size=_CHUNK_SIZE, overlap=_CHUNK_OVERLAP)
        self.embeddings = None
        self.diagnostics = {
            "paper_chars": len(paper_text),
            "paper_bytes": _text_bytes(paper_text),
            "chunk_count": len(self.chunks),
            "chunk_size": _CHUNK_SIZE,
            "chunk_overlap": _CHUNK_OVERLAP,
            "chunk_max_bytes": _CHUNK_MAX_BYTES,
            "max_chunk_bytes": max((_text_bytes(chunk) for chunk in self.chunks), default=0),
            "embedding_batches": 0,
            "chunk_embedding_status": "skipped_single_chunk",
            "query_embedding_failures": 0,
            "fallback_used": False,
            "last_error": None,
        }
        if len(self.chunks) > 1:
            self.diagnostics["embedding_batches"] = len(_batch_texts(self.chunks))
            self.embeddings = _embed(self.chunks)
            self.diagnostics["chunk_embedding_status"] = "success"

    def retrieve(self, query: str, top_k: int = _TOP_K) -> str:
        """根据查询检索最相关的论文块。

        top_k 动态计算：论文越长取越多，但不超过 _TOP_K_MAX。
        """
        if self.embeddings is None:
            return "\n\n---\n\n".join(self.chunks)

        # 动态计算 top_k：论文越长取越多，有上限
        n_chunks = len(self.chunks)
        if n_chunks <= 6:
            actual_k = min(top_k, n_chunks)
        else:
            # 按比例增长，但不超过上限
            actual_k = min(max(top_k, n_chunks // 4), _TOP_K_MAX, n_chunks)

        # 获取查询的 embedding。若外部 embedding API 暂时拒绝短查询，保留可用上下文。
        try:
            query_emb = _embed([query])[0]
        except Exception as exc:
            self.diagnostics["query_embedding_failures"] += 1
            self.diagnostics["fallback_used"] = True
            self.diagnostics["last_error"] = repr(exc)
            return "\n\n---\n\n".join(_select_fallback_chunks(self.chunks, actual_k))

        # 计算与每个 chunk 的相似度
        scores = [
            (i, _cosine_similarity(query_emb, emb))
            for i, emb in enumerate(self.embeddings)
        ]
        scores.sort(key=lambda x: x[1], reverse=True)

        # 取 actual_k，按原文顺序拼接
        selected = sorted(scores[:actual_k], key=lambda x: x[0])
        return "\n\n---\n\n".join(self.chunks[i] for i, _ in selected)
