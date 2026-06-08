"""Embedding-based semantic similarity for KOL recommendation.

Embedding only measures semantic fit between the user brief and KOL profiles.
It does not rank directly and does not replace business scoring.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any

import pandas as pd

from utils import OUTPUT_DIR, get_llm_client


DEFAULT_EMBEDDING_MODEL = os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v4")
CACHE_PATH = OUTPUT_DIR / "embedding_cache.json"


def build_kol_profile_text(row: pd.Series) -> str:
    return "\n".join(
        [
            f"达人名称：{row.get('kol_name', '')}",
            f"平台：{row.get('platform', '')}",
            f"内容领域：{row.get('field', '')}",
            f"受众画像：{row.get('audience', '')}",
            f"风险备注：{row.get('risk_note', '')}",
            f"粉丝数：{int(row.get('followers', 0) or 0)}",
            f"互动率：{float(row.get('engagement_rate', 0) or 0):.1f}%",
            f"转化率：{float(row.get('conversion_rate', 0) or 0):.1f}%",
            f"历史合作次数：{int(row.get('cooperation_count', 0) or 0)}",
        ]
    )


def build_requirement_text(requirements: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"推广产品：{requirements.get('product') or ''}",
            f"目标受众：{requirements.get('target_audience') or ''}",
            f"内容领域：{'、'.join(requirements.get('fields') or [])}",
            f"内容风格：{requirements.get('content_style') or ''}",
            f"自然语言需求：{requirements.get('raw_query') or ''}",
            f"扩展关键词：{'、'.join(requirements.get('expanded_keywords') or [])}",
            f"推广目标：{requirements.get('promotion_goal') or ''}",
        ]
    )


def compute_semantic_scores(
    df: pd.DataFrame,
    requirements: dict[str, Any],
    top_n: int | None = None,
) -> dict[str, Any]:
    """Return embedding semantic scores aligned to df.index.

    On any embedding-client failure this returns source ``rule_fallback`` and an
    empty score map, allowing the scorer to keep using its rule semantic logic.
    """
    requirement_text = build_requirement_text(requirements)
    if not requirement_text.strip():
        return {"source": "rule_fallback", "scores": {}, "topIndexes": list(df.index)}

    try:
        cache = _load_cache()
        query_embedding = _embed_text(requirement_text)
        scores: dict[int, float] = {}
        updated = False

        for idx, row in df.iterrows():
            profile_text = build_kol_profile_text(row)
            cache_key = _cache_key(row, profile_text)
            if cache_key in cache:
                kol_embedding = cache[cache_key]
            else:
                kol_embedding = _embed_text(profile_text)
                cache[cache_key] = kol_embedding
                updated = True
            scores[idx] = _similarity_to_score(_cosine_similarity(query_embedding, kol_embedding))

        if updated:
            _save_cache(cache)

        ordered_indexes = [
            idx for idx, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ]
        if top_n is not None and len(ordered_indexes) > top_n:
            ordered_indexes = ordered_indexes[:top_n]
        return {"source": "embedding", "scores": scores, "topIndexes": ordered_indexes}
    except Exception as exc:
        print(f"[warn] Embedding 语义相似度不可用，降级到规则语义：{exc}")
        return {"source": "rule_fallback", "scores": {}, "topIndexes": list(df.index)}


def _embed_text(text: str) -> list[float]:
    client = get_llm_client()
    resp = client.embeddings.create(model=DEFAULT_EMBEDDING_MODEL, input=text)
    return [float(value) for value in resp.data[0].embedding]


def _cache_key(row: pd.Series, profile_text: str) -> str:
    kol_id = str(row.get("kol_id") or row.name)
    digest = hashlib.sha256(profile_text.encode("utf-8")).hexdigest()
    return f"{kol_id}:{digest}"


def _load_cache() -> dict[str, list[float]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, list[float]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _similarity_to_score(similarity: float) -> float:
    # Cosine can be [-1, 1]. Map to [0, 100] and clamp.
    score = (similarity + 1.0) / 2.0 * 100
    return round(max(0.0, min(100.0, score)), 2)
