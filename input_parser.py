# input_parser.py
# 用户需求解析模块：把前端/脚本传入的需求统一成后端可处理的结构。
# 后续如接入 LLM 解析自由文本，也只输出结构化需求，不直接参与评分排序。

from __future__ import annotations

import math
import re
from typing import Any


GOAL_LABELS = ("拉新", "转化", "曝光", "种草")
RISK_PREFERENCES = ("保守", "平衡", "激进")


def parse_requirements(payload: dict[str, Any] | None) -> dict[str, Any]:
    """解析用户需求，返回服务内部统一使用的结构化需求对象。

    同时兼容前端 camelCase 字段和早期文档里的中文字段，便于脚本、
    API、未来其它前端入口共用同一套后端逻辑。
    """
    data = payload or {}
    optional = data.get("optional") or {}
    form_touched = data.get("formTouched") or {}
    raw_query = _text(data, "query", "requirementText", "需求描述", "自然语言需求")
    budget_min, budget_max = _parse_budget_range(data)
    content_style = _text(data, "contentStyle", "contentPreference", "内容风格", "内容偏好")
    promotion_goal = _one_of(_pick(data, "promotionGoal", "推广目标"), GOAL_LABELS, "种草")
    risk_preference = _one_of(_pick(data, "riskPreference", "风险偏好"), RISK_PREFERENCES, "平衡")
    if raw_query and not form_touched.get("promotionGoal"):
        promotion_goal = ""
    if raw_query and not form_touched.get("riskPreference"):
        risk_preference = ""

    return {
        "product": _text(data, "product", "推广产品/行业"),
        "target_audience": _text(data, "targetAudience", "目标受众"),
        "content_style": content_style,
        "raw_query": raw_query,
        "platforms": _clean_list(_pick(data, "platforms", "投放平台")),
        "budget_min": budget_min,
        "budget_max": budget_max,
        "single_budget": budget_max or _optional_number(_pick(data, "singleBudget", "单个达人预算")) or 3000,
        "total_budget": _optional_number(_pick(data, "totalBudget", "总预算")) or 20000,
        "fields": _clean_list(_pick(data, "fields", "内容领域")),
        "expanded_keywords": _clean_list(_pick(data, "expandedKeywords", "扩展关键词")),
        "promotion_goal": promotion_goal,
        "risk_preference": risk_preference,
        "hard_filters": {
            "platforms": bool(_clean_list(_pick(data, "platforms", "投放平台"))),
            "budget": budget_min is not None or budget_max is not None,
            "fields": False,
        },
        "optional": {
            "followers_min": _optional_number(_pick(optional, "followersMin", "粉丝数下限")),
            "followers_max": _optional_number(_pick(optional, "followersMax", "粉丝数上限")),
            "engagement_min": _optional_number(_pick(optional, "engagementMin", "互动率下限")),
            "conversion_min": _optional_number(_pick(optional, "conversionMin", "转化率下限")),
            "cooperation_min": _optional_number(_pick(optional, "cooperationMin", "合作次数下限")),
        },
        "keywords": keywords_from_text(_pick(data, "targetAudience", "目标受众")),
    }


def requirements_for_report(requirements: dict[str, Any]) -> dict[str, str]:
    """转换成 Markdown 报告里更适合展示的中文需求字典。"""
    budget_min = requirements.get("budget_min")
    budget_max = requirements.get("budget_max")
    if budget_min is not None and budget_max is not None:
        budget_text = f"{int(budget_min)}-{int(budget_max)} 元"
    elif budget_max is not None:
        budget_text = f"{int(budget_max)} 元以内"
    else:
        budget_text = "不限"

    return {
        "推广产品/行业": requirements.get("product") or "未填写",
        "目标受众": requirements.get("target_audience") or "不限",
        "内容风格": requirements.get("content_style") or "不限",
        "内容领域": "、".join(requirements.get("fields") or []) or "不限",
        "预算范围": budget_text,
        "投放平台": "、".join(requirements.get("platforms") or []) or "不限",
        "推广目标": requirements.get("promotion_goal", "种草"),
        "风险偏好": requirements.get("risk_preference", "平衡"),
    }


def keywords_from_text(text: Any) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[、,，/;；()（）\s]+", raw)
    return [part.strip() for part in parts if part.strip()][:8]


def _parse_budget_range(data: dict[str, Any]) -> tuple[float | None, float | None]:
    form_touched = data.get("formTouched") or {}
    ignore_single_budget = bool(_text(data, "query", "requirementText", "需求描述", "自然语言需求")) and not form_touched.get("singleBudget")
    explicit_min = _optional_number(_pick(data, "budgetMin", "预算下限"))
    explicit_max = _optional_number(_pick(data, "budgetMax", "预算上限"))
    if explicit_max is None and not ignore_single_budget:
        explicit_max = _optional_number(_pick(data, "singleBudget", "单个达人预算"))
    if explicit_min is not None or explicit_max is not None:
        return explicit_min, explicit_max

    raw = _pick(data, "budgetRange", "预算范围")
    if raw in (None, ""):
        return None, None

    numbers = re.findall(r"\d+(?:\.\d+)?", str(raw).replace(",", ""))
    if len(numbers) >= 2:
        low, high = float(numbers[0]), float(numbers[1])
        return min(low, high), max(low, high)
    if len(numbers) == 1:
        return None, float(numbers[0])
    return None, None


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _text(data: dict[str, Any], *keys: str, default: str = "") -> str:
    value = _pick(data, *keys)
    text = str(value or default).strip()
    return text or default


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(result) or result < 0:
        return float(default)
    return result


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or result < 0:
        return None
    return result


def _one_of(value: Any, choices: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip()
    return text if text in choices else default


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in re.split(r"[,，/、]", value) if item.strip()]
    return []
