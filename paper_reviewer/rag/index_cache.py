import hashlib
from threading import RLock


_RAG_INDEX_CACHE = {}
_RAG_DIAGNOSTICS_CACHE = {}
_RAG_CACHE_LOCK = RLock()


def _paper_cache_key(paper: str) -> str:
    return hashlib.sha256(paper.encode("utf-8")).hexdigest()


def clear_rag_cache() -> None:
    """Clear process-local RAG indexes after embedding configuration changes."""
    with _RAG_CACHE_LOCK:
        _RAG_INDEX_CACHE.clear()
        _RAG_DIAGNOSTICS_CACHE.clear()


def get_rag_diagnostics(paper: str) -> dict:
    """Return process-local diagnostics for a paper's RAG index."""
    if not paper:
        return {}
    if len(paper) <= 3000:
        return {
            "enabled": False,
            "paper_chars": len(paper),
            "reason": "paper_too_short",
        }

    cache_key = _paper_cache_key(paper)
    with _RAG_CACHE_LOCK:
        diagnostics = _RAG_DIAGNOSTICS_CACHE.get(cache_key)
        if diagnostics is None:
            return {
                "enabled": True,
                "paper_chars": len(paper),
                "chunk_embedding_status": "not_built",
            }
        return dict(diagnostics)


def get_rag_index_for_paper(paper: str):
    """Build or return a shared process-local RAG index for a paper."""
    if len(paper) <= 3000:
        return None

    cache_key = _paper_cache_key(paper)
    with _RAG_CACHE_LOCK:
        if cache_key in _RAG_INDEX_CACHE:
            index = _RAG_INDEX_CACHE[cache_key]
            diagnostics = getattr(index, "diagnostics", None)
            if isinstance(diagnostics, dict):
                diagnostics["cache_hit"] = True
                _RAG_DIAGNOSTICS_CACHE[cache_key] = diagnostics
            return index

        try:
            from paper_reviewer.rag.retriever import PaperIndex

            index = PaperIndex(paper)
            diagnostics = getattr(index, "diagnostics", {})
            if not isinstance(diagnostics, dict) or not diagnostics:
                diagnostics = {
                    "paper_chars": len(paper),
                    "chunk_count": len(getattr(index, "chunks", [])),
                    "chunk_embedding_status": "success",
                }
            diagnostics["enabled"] = True
            diagnostics["cache_hit"] = False
            _RAG_DIAGNOSTICS_CACHE[cache_key] = diagnostics
            _RAG_INDEX_CACHE[cache_key] = index
            return index
        except Exception as exc:
            _RAG_DIAGNOSTICS_CACHE[cache_key] = {
                "enabled": True,
                "paper_chars": len(paper),
                "chunk_embedding_status": "failed",
                "last_error": repr(exc),
            }
            return None
