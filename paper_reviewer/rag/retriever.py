"""
RAG 检索模块 v2：真正的向量检索（Gitee AI Qwen3-Embedding-4B）。

解决的问题：
1. 长论文 token 溢出 —— 每次只取最相关的 chunk
2. 审稿-quality —— 语义检索比关键词匹配更精准
3. 费用 —— 减少 60-80% token 消耗

技术栈：
- Embedding: Qwen3-Embedding-4B (1024 维, Gitee AI)
- 向量检索: 余弦相似度（纯 Python，无需 FAISS）
- 分块: 按章节边界 + 段落边界，~500 字/块
"""
import re
import os
from typing import List
from dotenv import load_dotenv

# 加载 .env
env_path = os.path.join(os.path.dirname(__file__), "..", "..", "20-multi-agent-debate", ".env")
load_dotenv(dotenv_path=env_path)

from openai import OpenAI

# Gitee AI Embedding API
_client = OpenAI(
    api_key=os.getenv("GITEE_API_KEY", ""),
    base_url=os.getenv("GITEE_BASE_URL", "https://ai.gitee.com/v1"),
)

_EMBED_MODEL = os.getenv("GITEE_EMBED_MODEL", "Qwen3-Embedding-4B")
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
_TOP_K = 5        # 短论文的默认值
_TOP_K_MAX = 15  # 长论文的上限（防止输入过多）


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

    return merged if merged else [text]


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
    resp = _client.embeddings.create(model=_EMBED_MODEL, input=texts)
    return [item.embedding for item in resp.data]


class PaperIndex:
    """论文向量索引：分块 + embedding + 语义检索。"""

    def __init__(self, paper_text: str):
        self.chunks = _chunk_text(paper_text)
        self.embeddings = None
        if len(self.chunks) > 1:
            self.embeddings = _embed(self.chunks)

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

        # 获取查询的 embedding
        query_emb = _embed([query])[0]
        # 计算与每个 chunk 的相似度
        scores = [
            (i, _cosine_similarity(query_emb, emb))
            for i, emb in enumerate(self.embeddings)
        ]
        scores.sort(key=lambda x: x[1], reverse=True)

        # 取 actual_k，按原文顺序拼接
        selected = sorted(scores[:actual_k], key=lambda x: x[0])
        return "\n\n---\n\n".join(self.chunks[i] for i, _ in selected)
