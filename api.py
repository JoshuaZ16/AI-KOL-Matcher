# api.py
# 服务层入口：接收结构化/半结构化需求，执行筛选、评分、ROI、理由生成并返回 JSON。

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from embeddings import compute_semantic_scores
from filter import apply_optional_filters, filter_kols
from input_parser import parse_requirements
from requirement_extractor import extract_requirements
from report import generate_api_advice, generate_api_reason
from roi import compute_roi_for_df, conversion_value_for_goal, exposure_rate_for_goal
from scorer import score_for_requirements, sort_top_k
from utils import load_kol_database, load_kol_database_from_text


COMMON_FIELDS = (
    "校园",
    "职场",
    "美妆",
    "科技",
    "数码",
    "美食",
    "旅游",
    "健身",
    "母婴",
    "生活",
    "穿搭",
    "求职",
    "学习",
)

GOAL_CONTENT_FORMS: dict[str, str] = {
    "拉新": "新人福利测评、场景痛点切入、评论区承接私信",
    "转化": "限时优惠口播、真实使用前后对比、带明确行动入口的种草笔记",
    "曝光": "话题挑战、清单合集、强视觉封面与高频短视频分发",
    "种草": "体验日记、教程清单、软性植入的真实使用分享",
}


def get_filter_options() -> dict[str, Any]:
    """返回前端表单所需的筛选选项和数值范围。"""
    df = load_kol_database()
    available_fields: set[str] = set()
    for raw in df["field"].dropna().astype(str):
        available_fields.update(part.strip() for part in re.split(r"[/、,，]", raw) if part.strip())
    fields = [field for field in COMMON_FIELDS if field in available_fields]

    return {
        "platforms": sorted(df["platform"].dropna().unique().tolist()),
        "fields": fields,
        "goals": ["拉新", "转化", "曝光", "种草"],
        "riskPreferences": ["保守", "平衡", "激进"],
        "ranges": {
            "followersMin": int(df["followers"].min()),
            "followersMax": int(df["followers"].max()),
            "priceMin": int(df["price"].min()),
            "priceMax": int(df["price"].max()),
            "engagementMin": float(df["engagement_rate"].min()),
            "engagementMax": float(df["engagement_rate"].max()),
            "conversionMin": float(df["conversion_rate"].min()),
            "conversionMax": float(df["conversion_rate"].max()),
            "cooperationMin": int(df["cooperation_count"].min()),
            "cooperationMax": int(df["cooperation_count"].max()),
        },
    }


def recommend(payload: dict[str, Any]) -> dict[str, Any]:
    """主服务流程：需求 → 筛选达人 → 评分排序 → ROI → 理由 → JSON。"""
    df, data_source = _load_request_kol_database(payload)
    requirements = parse_requirements(payload)
    if requirements.get("raw_query"):
        requirements = extract_requirements(requirements["raw_query"], requirements)

    hard_filters = requirements.get("hard_filters") or {}

    filtered = filter_kols(
        df,
        platforms=requirements["platforms"] if hard_filters.get("platforms") else None,
        budget_min=requirements["budget_min"] if hard_filters.get("budget") else None,
        budget_max=requirements["budget_max"] if hard_filters.get("budget") else None,
        fields=requirements["fields"] if hard_filters.get("fields") else None,
    )
    filtered = apply_optional_filters(filtered, requirements["optional"])

    if filtered.empty:
        return _empty_response(df, requirements, data_source)

    semantic_result = compute_semantic_scores(filtered, requirements, top_n=50)
    semantic_source = semantic_result.get("source", "rule_fallback")
    if semantic_source == "embedding" and semantic_result.get("topIndexes"):
        filtered = filtered.loc[semantic_result["topIndexes"]].copy()

    scored = score_for_requirements(
        filtered,
        requirements,
        semantic_scores=semantic_result.get("scores") if semantic_source == "embedding" else None,
        semantic_source=semantic_source,
    )
    scored = compute_roi_for_df(
        scored,
        exposure_rate=exposure_rate_for_goal(requirements["promotion_goal"]),
        conversion_value=conversion_value_for_goal(requirements["promotion_goal"]),
    )
    top10 = sort_top_k(scored, 10)

    recommendations = [_serialize_row(row, requirements) for _, row in top10.iterrows()]
    planned_spend = min(
        int(sum(item["price"] for item in recommendations)),
        int(requirements["total_budget"]),
    )

    return {
        "requirements": requirements,
        "summary": {
            "candidateCount": int(len(filtered)),
            "totalCount": int(len(df)),
            "plannedSpend": planned_spend,
            "averageScore": round(_safe_mean([item["score"] for item in recommendations]), 1),
            "message": _summary_message(recommendations, requirements, data_source),
            "dataSource": data_source,
        },
        "placementAdvice": generate_api_advice(recommendations, requirements),
        "recommendations": recommendations,
    }


def _load_request_kol_database(payload: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    csv_text = str(payload.get("customKolCsv") or "").strip()
    csv_name = str(payload.get("customKolCsvName") or "客户上传 CSV").strip()
    if csv_text:
        return load_kol_database_from_text(csv_text, csv_name), csv_name
    return load_kol_database(), "默认达人库"


def _empty_response(df: pd.DataFrame, requirements: dict[str, Any], data_source: str) -> dict[str, Any]:
    return {
        "requirements": requirements,
        "summary": {
            "candidateCount": 0,
            "totalCount": int(len(df)),
            "plannedSpend": 0,
            "averageScore": 0,
            "message": "当前条件没有命中达人，请放宽预算、平台或可选条件。",
            "dataSource": data_source,
        },
        "placementAdvice": generate_api_advice([], requirements),
        "recommendations": [],
    }


def _serialize_row(row: pd.Series, requirements: dict[str, Any]) -> dict[str, Any]:
    final_score = float(row["final_score_val"])
    roi_value = float(row.get("roi_value", 0))
    return {
        "rank": int(row["rank"]),
        "kolId": row.get("kol_id", ""),
        "name": row.get("kol_name", ""),
        "platform": row.get("platform", ""),
        "followers": int(row.get("followers", 0)),
        "followersLabel": _format_followers(row.get("followers", 0)),
        "field": row.get("field", ""),
        "audience": row.get("audience", ""),
        "price": int(row.get("price", 0)),
        "priceLabel": f"¥{int(row.get('price', 0)):,}",
        "score": round(final_score, 1),
        "semanticScore": round(float(row.get("semantic_score", row.get("audience_score", 0))), 1),
        "semanticSource": row.get("semantic_source", "rule_fallback"),
        "ruleAudienceScore": round(float(row.get("rule_audience_score", row.get("audience_score", 0))), 1),
        "businessScore": round(float(row.get("business_score", 0)), 1),
        "roi": row.get("roi_label", "-"),
        "roiValue": round(roi_value, 2),
        "risk": _risk_level(row.get("risk_score_val", 75), row.get("risk_note", "")),
        "riskNote": row.get("risk_note", "无风险"),
        "matchTags": list(row.get("match_tags", []) or []),
        "semanticMatchTags": list(row.get("semantic_match_tags", []) or []),
        "recommendation": generate_api_reason(row, requirements),
        "metrics": {
            "audienceScore": round(float(row.get("audience_score", 0)), 1),
            "costScore": round(float(row.get("cost_score", 0)), 1),
            "riskScore": round(float(row.get("risk_score_val", 0)), 1),
            "engagementRate": round(float(row.get("engagement_rate", 0)), 1),
            "conversionRate": round(float(row.get("conversion_rate", 0)), 1),
            "cooperationCount": int(row.get("cooperation_count", 0)),
            "estimatedExposure": int(row.get("estimated_exposure", 0)),
            "estimatedConversions": round(float(row.get("estimated_conversions", 0)), 1),
        },
        "scoreBreakdown": {
            "semantic": round(float(row.get("semantic_score", row.get("audience_score", 0))), 1),
            "audience": round(float(row.get("audience_score", 0)), 1),
            "ruleAudience": round(float(row.get("rule_audience_score", row.get("audience_score", 0))), 1),
            "business": round(float(row.get("business_score", 0)), 1),
            "cost": round(float(row.get("cost_score", 0)), 1),
            "risk": round(float(row.get("risk_score_val", 0)), 1),
            "followers": round(float(row.get("followers_score", 0)), 1),
            "engagement": round(float(row.get("engagement_score", 0)), 1),
            "conversion": round(float(row.get("conversion_score", 0)), 1),
            "roi": round(roi_value, 2),
        },
        "details": _detail_analysis(row, requirements),
    }


def _detail_analysis(row: pd.Series, requirements: dict[str, Any]) -> dict[str, str]:
    goal = requirements["promotion_goal"]
    risk_score_val = float(row.get("risk_score_val", 75))
    priority = "建议优先投放" if row.get("final_score_val", 0) >= 72 and risk_score_val >= 65 else "建议小预算测试"
    if requirements["risk_preference"] == "保守" and risk_score_val < 80:
        priority = "建议人工复核后再投放"
    elif requirements["risk_preference"] == "激进" and row.get("roi_value", 0) >= 1.2:
        priority = "可作为增长测试优先位"

    return {
        "why": (
            f"综合分{float(row.get('final_score_val', 0)):.1f}，"
            f"在{row.get('platform', '')}的{row.get('field', '')}内容中兼顾匹配度与预算效率。"
        ),
        "semanticFit": _semantic_fit_text(row),
        "audienceFit": (
            f"达人受众为{row.get('audience', '')}，"
            f"与目标人群的匹配分为{float(row.get('audience_score', 0)):.1f}/100。"
        ),
        "costValue": (
            f"报价{int(row.get('price', 0))}元，互动率{float(row.get('engagement_rate', 0)):.1f}%，"
            f"转化率{float(row.get('conversion_rate', 0)):.1f}%，预估ROI {row.get('roi_label', '-')}。"
        ),
        "risk": (
            f"风险判断：{row.get('risk_note', '无风险')}，"
            f"风险分{risk_score_val:.1f}/100。"
        ),
        "contentForm": GOAL_CONTENT_FORMS.get(goal, GOAL_CONTENT_FORMS["种草"]),
        "priority": priority,
    }


def _semantic_fit_text(row: pd.Series) -> str:
    tags = list(row.get("match_tags", []) or [])
    matched = list(row.get("semantic_match_tags", []) or [])
    source = row.get("semantic_source", "rule_fallback")
    semantic_score = float(row.get("semantic_score", row.get("audience_score", 0)) or 0)
    tag_text = "、".join(tags[:6]) if tags else "暂无明显标签"
    if source == "embedding":
        return f"语义匹配分{semantic_score:.1f}/100，来自用户自然语言需求与达人画像 embedding 相似度；达人标签：{tag_text}。"
    if matched:
        return f"规则兜底语义分{semantic_score:.1f}/100，命中语义标签：{'、'.join(matched[:5])}；达人标签：{tag_text}。"
    return f"规则兜底语义分{semantic_score:.1f}/100，达人标签：{tag_text}，未命中特定语义偏好。"


def _format_followers(value: Any) -> str:
    followers = int(float(value or 0))
    if followers >= 10_000:
        number = followers / 10_000
        return f"{number:.0f}万" if number.is_integer() else f"{number:.1f}万"
    return str(followers)


def _risk_level(score: Any, note: Any) -> str:
    risk_score_val = float(score or 0)
    note_text = str(note or "")
    if risk_score_val >= 90:
        return "低"
    if risk_score_val >= 65:
        return "中"
    return "高" if "异常" in note_text or "存疑" in note_text else "中高"


def _summary_message(
    recommendations: list[dict[str, Any]],
    requirements: dict[str, Any],
    data_source: str,
) -> str:
    if not recommendations:
        return "暂无推荐结果。"
    best = recommendations[0]
    source_text = f"使用{data_source}，" if data_source != "默认达人库" else ""
    return (
        f"{source_text}本次从候选达人中选出{len(recommendations)}位，"
        f"首推{best['name']}，适合围绕{requirements['promotion_goal']}目标启动投放。"
    )


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0
