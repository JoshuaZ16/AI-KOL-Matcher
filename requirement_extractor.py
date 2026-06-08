"""LLM + local fallback requirement extraction for natural-language briefs.

The extractor only produces structured requirements. Ranking still happens in
the scorer with deterministic business weights.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from utils import call_qwen_json


STANDARD_FIELDS = [
    "校园",
    "职场",
    "科技",
    "数码",
    "美妆",
    "美食",
    "生活",
    "穿搭",
    "母婴",
    "健身",
    "旅游",
    "学习",
    "求职",
]

STANDARD_PLATFORMS = ["小红书", "抖音", "B站", "微博"]
GOALS = ["拉新", "转化", "曝光", "种草"]
RISK_PREFERENCES = ["保守", "平衡", "激进"]

FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "校园": ("校园", "大学", "大学生", "学生", "应届", "毕业", "军训", "奖学金", "考研"),
    "职场": ("职场", "求职", "就业", "实习", "面试", "简历", "职业", "工作"),
    "科技": ("科技", "计算机", "AI", "人工智能", "程序员", "编程", "软件", "开发", "数码", "电脑"),
    "数码": ("数码", "科技", "计算机", "AI", "程序员", "编程", "软件", "电脑", "手机", "硬件"),
    "美妆": ("美妆", "护肤", "彩妆", "口红", "底妆"),
    "美食": ("美食", "探店", "烹饪", "甜品", "火锅"),
    "生活": ("生活", "日常", "vlog", "真实", "自然", "不商业", "不太商业", "不硬广"),
    "穿搭": ("穿搭", "服饰", "搭配"),
    "母婴": ("母婴", "育儿", "宝妈", "辅食", "早教"),
    "健身": ("健身", "运动", "减脂", "瑜伽", "普拉提", "增肌"),
    "旅游": ("旅游", "旅行", "摄影", "民宿", "自驾", "海岛", "古镇"),
    "学习": ("学习", "课程", "考试", "考研", "方法"),
    "求职": ("求职", "就业", "应届", "简历", "面试", "实习", "职业规划"),
}

STYLE_KEYWORDS = ("专业", "真实", "自然", "可信", "不要太硬广", "不硬广", "不太商业", "低商业感", "校园感")


def extract_requirements(query: str, base_requirements: dict[str, Any]) -> dict[str, Any]:
    """Fill missing structured fields from a natural-language query.

    Form fields in ``base_requirements`` take priority. LLM output is sanitized
    and then merged. If the LLM is unavailable, a conservative local extractor
    handles common budget/platform/field/goal expressions.
    """
    result = _with_defaults(copy.deepcopy(base_requirements))
    if not str(query or "").strip():
        result["structured_source"] = result.get("structured_source") or "form"
        return result

    extracted = _extract_with_llm(query, result) or _extract_locally(query)
    extracted = _sanitize_extracted(extracted)
    result = _merge_with_form_priority(result, extracted)
    result["structured_source"] = "llm" if extracted.get("_source") == "llm" else "rule_fallback"
    return result


def _extract_with_llm(query: str, base: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""
请从用户投放需求中抽取结构化字段，只返回 JSON。

标准内容领域只能从这些值里选择：{STANDARD_FIELDS}
标准平台只能从这些值里选择：{STANDARD_PLATFORMS}
推广目标只能从这些值里选择：{GOALS}
风险偏好只能从这些值里选择：{RISK_PREFERENCES}

规则：
- fields 尽量映射到标准内容领域。例如“计算机、AI、程序员、编程”映射到 ["科技", "数码", "职场"]。
- expanded_keywords 保留用户原始语义词。
- hard_filters.fields 默认 false，除非用户明确说“只要/必须/仅限某领域达人”。
- hard_filters.platforms 在用户明确指定平台时为 true；平台不限时 false。
- hard_filters.budget 在用户明确写预算上限/下限时为 true。
- 不要推荐达人，不要排序。

已填写表单字段（这些字段优先，缺失时才补全）：
{base}

用户自然语言需求：
{query}

返回格式：
{{
  "product": "",
  "target_audience": "",
  "content_style": "",
  "platforms": [],
  "fields": [],
  "expanded_keywords": [],
  "budget_min": null,
  "budget_max": null,
  "total_budget": null,
  "promotion_goal": "种草",
  "risk_preference": "平衡",
  "hard_filters": {{"platforms": false, "budget": false, "fields": false}}
}}
""".strip()
    parsed = call_qwen_json(prompt, max_tokens=900)
    if not parsed:
        return {}
    parsed["_source"] = "llm"
    return parsed


def _extract_locally(query: str) -> dict[str, Any]:
    text = str(query or "")
    compact = text.replace(" ", "")
    fields = _infer_fields(text)
    platforms = _infer_platforms(text)
    budget_max = _infer_budget_max(compact)
    total_budget = _infer_total_budget(compact)
    goal = _infer_goal(text)
    risk = _infer_risk_preference(text)
    style = "、".join([kw for kw in STYLE_KEYWORDS if kw in text])
    keywords = _expanded_keywords(text, fields)

    return {
        "_source": "rule_fallback",
        "product": _infer_product(text),
        "target_audience": _infer_audience(text),
        "content_style": style,
        "platforms": platforms,
        "fields": fields,
        "expanded_keywords": keywords,
        "budget_min": None,
        "budget_max": budget_max,
        "total_budget": total_budget,
        "promotion_goal": goal,
        "risk_preference": risk,
        "hard_filters": {
            "platforms": bool(platforms),
            "budget": budget_max is not None,
            "fields": _explicit_field_only(text),
        },
    }


def _sanitize_extracted(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {}
    hard = data.get("hard_filters") if isinstance(data.get("hard_filters"), dict) else {}
    return {
        "_source": data.get("_source", "rule_fallback"),
        "product": _clean_text(data.get("product")),
        "target_audience": _clean_text(data.get("target_audience")),
        "content_style": _clean_text(data.get("content_style")),
        "platforms": [p for p in _clean_list(data.get("platforms")) if p in STANDARD_PLATFORMS],
        "fields": [f for f in _clean_list(data.get("fields")) if f in STANDARD_FIELDS],
        "expanded_keywords": _clean_list(data.get("expanded_keywords"))[:12],
        "budget_min": _optional_number(data.get("budget_min")),
        "budget_max": _optional_number(data.get("budget_max")),
        "total_budget": _optional_number(data.get("total_budget")),
        "promotion_goal": data.get("promotion_goal") if data.get("promotion_goal") in GOALS else "",
        "risk_preference": data.get("risk_preference") if data.get("risk_preference") in RISK_PREFERENCES else "",
        "hard_filters": {
            "platforms": bool(hard.get("platforms")),
            "budget": bool(hard.get("budget")),
            "fields": bool(hard.get("fields")),
        },
    }


def _merge_with_form_priority(base: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    merged = _with_defaults(base)
    if not extracted:
        return merged

    for key in ("product", "target_audience", "content_style"):
        if not _has_form_text(merged.get(key)) and extracted.get(key):
            merged[key] = extracted[key]

    for key in ("platforms", "fields"):
        if not merged.get(key) and extracted.get(key):
            merged[key] = extracted[key]

    for key in ("budget_min", "budget_max", "total_budget"):
        if merged.get(key) is None and extracted.get(key) is not None:
            merged[key] = extracted[key]

    if not merged.get("promotion_goal") and extracted.get("promotion_goal"):
        merged["promotion_goal"] = extracted["promotion_goal"]
    if not merged.get("risk_preference") and extracted.get("risk_preference"):
        merged["risk_preference"] = extracted["risk_preference"]

    merged["promotion_goal"] = merged.get("promotion_goal") or "种草"
    merged["risk_preference"] = merged.get("risk_preference") or "平衡"
    merged["single_budget"] = merged.get("budget_max") or merged.get("single_budget") or 3000
    merged["total_budget"] = merged.get("total_budget") or 20000
    merged["expanded_keywords"] = _unique((merged.get("expanded_keywords") or []) + (extracted.get("expanded_keywords") or []))
    merged["hard_filters"] = _merge_hard_filters(merged.get("hard_filters"), extracted.get("hard_filters"))
    merged["keywords"] = _unique((merged.get("keywords") or []) + (merged.get("expanded_keywords") or []))
    return merged


def _merge_hard_filters(base_hard: Any, extracted_hard: Any) -> dict[str, bool]:
    base = base_hard if isinstance(base_hard, dict) else {}
    extracted = extracted_hard if isinstance(extracted_hard, dict) else {}
    return {
        "platforms": bool(base.get("platforms") or extracted.get("platforms")),
        "budget": bool(base.get("budget") or extracted.get("budget")),
        "fields": bool(extracted.get("fields")),
    }


def _with_defaults(requirements: dict[str, Any]) -> dict[str, Any]:
    requirements.setdefault("expanded_keywords", [])
    requirements.setdefault("hard_filters", {})
    hard = requirements["hard_filters"] if isinstance(requirements["hard_filters"], dict) else {}
    requirements["hard_filters"] = {
        "platforms": bool(hard.get("platforms") or requirements.get("platforms")),
        "budget": bool(hard.get("budget") or requirements.get("budget_min") is not None or requirements.get("budget_max") is not None),
        "fields": bool(hard.get("fields")),
    }
    return requirements


def _infer_fields(text: str) -> list[str]:
    fields: list[str] = []
    for field, synonyms in FIELD_SYNONYMS.items():
        if any(syn.lower() in text.lower() for syn in synonyms):
            fields.append(field)
    return _unique(fields)


def _infer_platforms(text: str) -> list[str]:
    lowered = text.lower()
    if "平台不限" in text or "不限平台" in text:
        return []
    aliases = {
        "小红书": "小红书",
        "抖音": "抖音",
        "b站": "B站",
        "bilibili": "B站",
        "哔哩哔哩": "B站",
        "微博": "微博",
    }
    found = []
    for key, platform in aliases.items():
        if key.lower() in lowered:
            found.append(platform)
    return _unique(found)


def _infer_budget_max(text: str) -> float | None:
    patterns = (
        r"(?:每人|单人|单个达人|达人|预算)[^\d]{0,8}(\d+(?:\.\d+)?)(万)?(?:元)?(?:以内|以下|内|之内)?",
        r"(\d+(?:\.\d+)?)(万)?(?:元)?(?:以内|以下|内|之内)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = float(match.group(1))
            if match.group(2):
                value *= 10000
            return value
    return None


def _infer_total_budget(text: str) -> float | None:
    match = re.search(r"总预算[^\d]{0,8}(\d+(?:\.\d+)?)(万)?", text)
    if not match:
        return None
    value = float(match.group(1))
    return value * 10000 if match.group(2) else value


def _infer_goal(text: str) -> str:
    if any(word in text for word in ("曝光", "声量", "传播", "粉丝量要大", "达人粉丝量要大")):
        return "曝光"
    if any(word in text for word in ("转化", "成交", "购买", "下单", "ROI")):
        return "转化"
    if any(word in text for word in ("拉新", "获客", "注册", "新用户")):
        return "拉新"
    if any(word in text for word in ("种草", "真实", "不硬广", "不太商业", "校园感")):
        return "种草"
    return ""


def _infer_risk_preference(text: str) -> str:
    if any(word in text for word in ("低风险", "稳妥", "保守", "数据真实", "真实", "不太商业", "不硬广", "广告比例")):
        return "保守"
    if any(word in text for word in ("激进", "增长测试", "冲量")):
        return "激进"
    return ""


def _infer_audience(text: str) -> str:
    terms = []
    for word in ("大学生", "应届生", "学生", "程序员", "开发者", "职场新人", "科技爱好者", "18-25岁", "18-35岁"):
        if word in text:
            terms.append(word)
    return "、".join(_unique(terms))


def _infer_product(text: str) -> str:
    if "课程" in text:
        return "课程"
    if "品牌曝光" in text:
        return "品牌曝光"
    return ""


def _expanded_keywords(text: str, fields: list[str]) -> list[str]:
    keywords = []
    raw_terms = re.split(r"[、,，/;；\s，。！？]+", text)
    for term in raw_terms:
        term = term.strip("“”\"'")
        if 1 < len(term) <= 12:
            keywords.append(term)
    for field in fields:
        keywords.extend(FIELD_SYNONYMS.get(field, ()))
    return _unique(keywords)[:12]


def _explicit_field_only(text: str) -> bool:
    return bool(re.search(r"(只要|仅限|必须是|只找|限定).{0,12}(达人|领域|类|方向)?", text))


def _has_form_text(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text != "未填写产品")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in re.split(r"[,，/、;；]", value) if item.strip()]
    return []


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
