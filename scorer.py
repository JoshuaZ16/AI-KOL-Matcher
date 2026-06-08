# scorer.py
# 达人评分模块（原子任务 3-6）
# 实现受众匹配分、性价比分、风险分、综合加权总分
# 所有分数归一化到 0-100；当前阶段不接入任何 LLM

import re
from typing import Any, Iterable, List, Optional
import pandas as pd


# ------------------------------------------------------------------ #
#  1. 标签化与语义意图（原子任务 3 升级）                                #
# ------------------------------------------------------------------ #

TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("校园", ("校园", "大学", "学生", "考研", "奖学金")),
    ("职场", ("职场", "实习", "求职", "应届", "效率", "新人")),
    ("科技数码", ("科技", "数码", "计算机", "AI", "人工智能", "编程", "程序员", "软件", "电脑", "手机", "评测", "开箱")),
    ("美妆", ("美妆", "护肤", "彩妆")),
    ("真实感", ("真实", "生活", "记录", "日记", "经验", "指南", "攻略", "vlog", "数据真实")),
    ("素人感", ("素人", "日常", "生活", "记录", "日记", "不精致")),
    ("日常分享", ("日常", "生活", "记录", "日记", "vlog", "分享")),
    ("种草型", ("种草", "美妆", "护肤", "穿搭", "教程", "清单", "省钱", "好物")),
    ("转化型", ("转化", "省钱", "攻略", "兼职", "求职", "优惠")),
    ("曝光型", ("曝光", "挑战", "话题", "传播", "头部")),
    ("学生党", ("学生党", "大学生", "大学", "校园", "考研", "奖学金")),
    ("女性用户", ("女性", "女生", "美妆", "护肤", "穿搭", "宝妈", "母婴")),
    ("平台影响力", ("影响力", "粉丝", "头部")),
    ("内容传播力", ("传播", "互动", "评论", "点赞", "爆款")),
]

SEMANTIC_TAG_RULES: dict[str, tuple[str, ...]] = {
    "校园": ("校园", "学生党", "日常分享"),
    "大学生": ("校园", "学生党"),
    "学生": ("校园", "学生党"),
    "应届": ("职场", "学生党"),
    "职场": ("职场",),
    "科技": ("科技数码", "专业向"),
    "数码": ("科技数码", "专业向"),
    "计算机": ("科技数码", "专业向"),
    "AI": ("科技数码", "专业向"),
    "人工智能": ("科技数码", "专业向"),
    "程序员": ("科技数码", "专业向", "职场"),
    "编程": ("科技数码", "专业向"),
    "软件开发": ("科技数码", "专业向", "职场"),
    "专业": ("专业向",),
    "美妆": ("美妆", "女性用户", "种草型"),
    "女性": ("女性用户",),
    "女生": ("女性用户",),
    "真实": ("真实感", "素人感", "日常分享"),
    "可信": ("真实感", "低风险"),
    "自然": ("真实感", "素人感", "日常分享"),
    "不精致": ("真实感", "素人感", "日常分享"),
    "素人": ("素人感", "真实感", "日常分享"),
    "日常": ("日常分享", "真实感", "素人感"),
    "生活感": ("日常分享", "真实感", "素人感"),
    "不商业": ("真实感", "低风险"),
    "种草": ("种草型",),
    "转化": ("转化型",),
    "拉新": ("转化型",),
    "曝光": ("曝光型", "平台影响力", "内容传播力"),
    "粉丝": ("平台影响力", "曝光型"),
    "影响力": ("平台影响力", "曝光型"),
    "传播": ("内容传播力", "曝光型"),
    "互动": ("高互动", "内容传播力"),
    "低风险": ("低风险",),
}


def extract_kol_tags(row: pd.Series) -> list[str]:
    """从达人基础字段中抽取业务标签。

    CSV 暂无独立 tag 字段，因此先用达人名称、内容领域、受众画像、
    风险备注和指标阈值生成稳定标签，后续可直接替换为人工标签库。
    """
    text = " ".join(
        str(row.get(key, ""))
        for key in ("kol_name", "field", "audience", "risk_note")
    ).lower()
    tags: list[str] = []
    for tag, keywords in TAG_RULES:
        if any(keyword.lower() in text for keyword in keywords):
            tags.append(tag)

    if float(row.get("engagement_rate", 0) or 0) >= 4.0:
        tags.extend(["高互动", "内容传播力"])
    if "科技数码" in tags and float(row.get("engagement_rate", 0) or 0) >= 3.8:
        tags.append("专业向")
    if float(row.get("conversion_rate", 0) or 0) >= 3.6:
        tags.append("转化型")
    if int(row.get("followers", 0) or 0) >= 100_000:
        tags.extend(["曝光型", "平台影响力"])
    if risk_score(row.get("risk_note", "")) >= 90:
        tags.append("低风险")

    return _unique(tags)


def expand_semantic_tags(terms: Optional[Iterable[str]]) -> list[str]:
    """把用户自然语言词汇扩展成系统可识别标签。

    例如："真实、不精致但可信" 会扩展为 "真实感/素人感/日常分享/低风险"。
    """
    tags: list[str] = []
    for raw_term in _clean_terms(terms):
        term = raw_term.lower()
        for trigger, mapped_tags in SEMANTIC_TAG_RULES.items():
            trigger_lower = trigger.lower()
            if trigger_lower in term or term in trigger_lower:
                tags.extend(mapped_tags)
        for canonical_tag, _ in TAG_RULES:
            if canonical_tag.lower() in term:
                tags.append(canonical_tag)
        if "高互动" in raw_term:
            tags.append("高互动")
        if "低风险" in raw_term:
            tags.append("低风险")
    return _unique(tags)


def matched_semantic_tags(kol_tags: Iterable[str], terms: Optional[Iterable[str]]) -> list[str]:
    """返回达人标签与用户语义意图的交集。"""
    wanted = set(expand_semantic_tags(terms))
    return [tag for tag in kol_tags if tag in wanted]


def audience_match_score(
    audience: str,
    target_keywords: List[str],
    kol_tags: Optional[Iterable[str]] = None,
) -> float:
    """计算受众/语义匹配分（0-100）。

    先做原始关键词命中，再把用户描述扩展成标签并与达人标签匹配。
    这样既保留"大学生/18-25岁"这类精确筛选，也支持"真实、不精致但可信"
    这类非标准表达。

    参数:
        audience: 达人受众画像字符串（如 "大学生、应届生、18-25岁"）
        target_keywords: 用户输入的目标受众关键词列表（如 ["大学生", "应届生"]）
        kol_tags: 达人标签列表（如 ["校园", "学生党", "真实感"]）
    返回:
        0-100 的浮点数
    """
    keywords = _clean_terms(target_keywords)
    semantic_tags = expand_semantic_tags(keywords)
    # 无关键词时返回中性分，避免因为不填关键词就得 0 分
    if not keywords and not semantic_tags:
        return 50.0

    audience_lower = str(audience).lower()
    tag_set = set(kol_tags or [])
    tag_text = " ".join(tag_set).lower()
    matched = sum(
        1 for kw in keywords
        if kw.lower() in audience_lower or kw.lower() in tag_text
    )
    keyword_score = (matched / len(keywords)) * 100 if keywords else 0

    semantic_hits = sum(1 for tag in semantic_tags if tag in tag_set)
    semantic_score = (semantic_hits / len(semantic_tags)) * 100 if semantic_tags else 0

    if keywords and semantic_tags:
        score = max(keyword_score, keyword_score * 0.45 + semantic_score * 0.55)
    elif semantic_tags:
        score = semantic_score
    else:
        score = keyword_score
    return round(score, 2)


def _intent_terms_from_requirements(requirements: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    terms.extend(requirements.get("keywords") or [])
    terms.extend(_terms_from_text(requirements.get("target_audience")))
    terms.extend(requirements.get("fields") or [])
    terms.extend(requirements.get("expanded_keywords") or [])
    terms.extend(_terms_from_text(requirements.get("product")))
    terms.extend(_terms_from_text(requirements.get("content_style")))
    terms.extend(_terms_from_text(requirements.get("raw_query")))
    if requirements.get("promotion_goal"):
        terms.append(str(requirements["promotion_goal"]))
    return _unique(_clean_terms(terms))


def _terms_from_text(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[、,，/;；\s]+", raw) if part.strip()]


def _clean_terms(terms: Optional[Iterable[str]]) -> list[str]:
    return [str(term).strip() for term in (terms or []) if str(term).strip()]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


# ------------------------------------------------------------------ #
#  2. 性价比分（原子任务 4）                                            #
# ------------------------------------------------------------------ #

def _raw_cost_effectiveness(row: pd.Series) -> float:
    """计算单行达人的性价比原始值。

    公式：(互动率 × 转化率 × 粉丝数) / 报价
    互动率和转化率以百分数形式直接使用（3.8 而非 0.038），
    与文档公式一致，归一化后量纲不影响结果。
    """
    return (row["engagement_rate"] * row["conversion_rate"] * row["followers"]) / row["price"]


def cost_effectiveness_score(df: pd.DataFrame) -> pd.Series:
    """对 DataFrame 内全部达人计算性价比分（0-100），使用 min-max 归一化。

    需要整批传入，以便跨候选达人进行归一化比较。

    参数:
        df: 候选达人 DataFrame（至少含 engagement_rate / conversion_rate /
            followers / price 字段）
    返回:
        与 df 索引对齐的 0-100 分 Series，字段名为 "cost_score"
    """
    raw = df.apply(_raw_cost_effectiveness, axis=1)

    min_val, max_val = raw.min(), raw.max()

    # 所有达人性价比完全相同时，给中性分 50
    if max_val == min_val:
        return pd.Series(50.0, index=df.index, name="cost_score")

    normalized = (raw - min_val) / (max_val - min_val) * 100
    return normalized.rename("cost_score").round(2)


# ------------------------------------------------------------------ #
#  3. 风险分（原子任务 5）                                              #
# ------------------------------------------------------------------ #

# 风险关键词 → 分数映射（100 = 无风险，越低风险越高）
# 按"含任意关键词"匹配，优先取分数最低的一条（最悲观原则）
_RISK_RULES: List[tuple] = [
    ("数据异常",    40),   # 高风险：数据造假迹象
    ("粉丝质量存疑", 50),  # 高风险：僵尸粉嫌疑
    ("广告比例较高", 65),  # 中风险：内容商业味重
    ("无风险",     100),   # 低风险：平台/机构认证
    ("数据真实",    90),   # 低风险：第三方核验
]
_DEFAULT_RISK_SCORE = 75  # 无法识别时给中性偏好分


def risk_score(risk_note: str) -> float:
    """根据风险备注返回风险分（0-100），分数越高表示风险越低。

    匹配逻辑：遍历规则表，取命中规则中分数最低的（最悲观原则）。
    未命中任何规则时返回默认中性分。

    参数:
        risk_note: 达人风险备注字符串（如 "广告比例较高"）
    返回:
        0-100 浮点数
    """
    note = str(risk_note).strip()
    matched_scores = [score for keyword, score in _RISK_RULES if keyword in note]

    if not matched_scores:
        return float(_DEFAULT_RISK_SCORE)
    # 取最低分（最悲观），避免混合风险描述被高估
    return float(min(matched_scores))


# ------------------------------------------------------------------ #
#  4. 综合加权总分（原子任务 6）                                        #
# ------------------------------------------------------------------ #

# 各维度权重（三者之和必须 = 1.0）
_WEIGHT_AUDIENCE      = 0.40  # 受众匹配权重
_WEIGHT_COST          = 0.35  # 性价比权重
_WEIGHT_RISK          = 0.25  # 风险评估权重


GOAL_WEIGHTS: dict[str, dict[str, float]] = {
    "拉新": {"audience": 0.36, "cost": 0.24, "risk": 0.16, "followers": 0.08, "engagement": 0.08, "conversion": 0.08},
    "转化": {"audience": 0.24, "cost": 0.28, "risk": 0.14, "conversion": 0.26, "engagement": 0.08},
    "曝光": {"audience": 0.20, "cost": 0.12, "risk": 0.12, "followers": 0.42, "engagement": 0.14},
    "种草": {"audience": 0.36, "cost": 0.16, "risk": 0.16, "engagement": 0.24, "conversion": 0.08},
}

RISK_WEIGHT_ADJUSTMENTS: dict[str, float] = {
    "保守": 0.10,
    "平衡": 0.00,
    "激进": -0.08,
}


def final_score(
    audience_s: float,
    cost_s: float,
    risk_s: float,
) -> float:
    """综合加权总分（0-100）。

    公式：受众匹配 × 0.4 + 性价比 × 0.35 + 风险分 × 0.25

    参数:
        audience_s: 受众匹配分（0-100）
        cost_s: 性价比分（0-100）
        risk_s: 风险分（0-100）
    返回:
        0-100 浮点数
    """
    score = (
        audience_s * _WEIGHT_AUDIENCE
        + cost_s    * _WEIGHT_COST
        + risk_s    * _WEIGHT_RISK
    )
    # 钳位到 [0, 100]，防止极端值越界
    return round(max(0.0, min(100.0, score)), 2)


# ------------------------------------------------------------------ #
#  5. 批量评分（便捷入口）                                              #
# ------------------------------------------------------------------ #

def score_all(df: pd.DataFrame, target_keywords: Optional[List[str]] = None) -> pd.DataFrame:
    """对候选达人 DataFrame 批量计算四项分数，返回带分数列的新 DataFrame。

    新增列：match_tags / semantic_match_tags / audience_score / cost_score /
    risk_score_val / final_score_val

    参数:
        df: 候选达人 DataFrame
        target_keywords: 目标受众关键词列表，为空时受众匹配分统一取 50
    返回:
        原 DataFrame 追加四列分数后的副本
    """
    result = df.copy()
    keywords = target_keywords or []

    result["match_tags"] = result.apply(extract_kol_tags, axis=1)
    result["semantic_match_tags"] = result["match_tags"].apply(
        lambda tags: matched_semantic_tags(tags, keywords)
    )

    # 受众匹配分（逐行计算）
    result["audience_score"] = result.apply(
        lambda row: audience_match_score(row["audience"], keywords, row["match_tags"]),
        axis=1,
    )

    # 性价比分（批量归一化）
    result["cost_score"] = cost_effectiveness_score(result)

    # 风险分（逐行计算）
    result["risk_score_val"] = result["risk_note"].apply(risk_score)

    # 综合总分
    result["final_score_val"] = result.apply(
        lambda row: final_score(
            row["audience_score"],
            row["cost_score"],
            row["risk_score_val"],
        ),
        axis=1,
    )

    return result


def score_for_requirements(
    df: pd.DataFrame,
    requirements: dict[str, Any],
    semantic_scores: Optional[dict[Any, float]] = None,
    semantic_source: str = "rule_fallback",
) -> pd.DataFrame:
    """按结构化需求评分。

    升级后的链路为：达人标签化 → 目标权重匹配 → 语义意图匹配。
    在保留原有三维评分（受众/性价比/风险）的基础上，根据推广目标补充
    粉丝量、互动率、转化率等业务权重，供前端服务化推荐使用。
    """
    result = df.copy()
    match_terms = _intent_terms_from_requirements(requirements)

    result["match_tags"] = result.apply(extract_kol_tags, axis=1)
    result["semantic_match_tags"] = result["match_tags"].apply(
        lambda tags: matched_semantic_tags(tags, match_terms)
    )
    result["rule_audience_score"] = result.apply(
        lambda row: max(
            audience_match_score(row["audience"], match_terms, row["match_tags"]),
            _field_match_score(row.get("field", ""), requirements.get("fields") or []),
        ),
        axis=1,
    )
    if semantic_scores:
        result["semantic_score"] = result.index.map(lambda idx: float(semantic_scores.get(idx, 50.0)))
        result["semantic_source"] = semantic_source or "embedding"
        result["audience_score"] = (
            result["semantic_score"] * 0.75 + result["rule_audience_score"] * 0.25
        ).round(2)
    else:
        result["semantic_score"] = result["rule_audience_score"]
        result["semantic_source"] = "rule_fallback"
        result["audience_score"] = result["rule_audience_score"]
    result["cost_score"] = cost_effectiveness_score(result)
    result["risk_score_val"] = result["risk_note"].apply(risk_score)
    result["followers_score"] = _minmax_score(result["followers"])
    result["engagement_score"] = _minmax_score(result["engagement_rate"])
    result["conversion_score"] = _minmax_score(result["conversion_rate"])
    result["cooperation_score"] = _minmax_score(result["cooperation_count"])
    result["business_score"] = result.apply(_business_score, axis=1)

    weights = weights_for(
        requirements.get("promotion_goal", "种草"),
        requirements.get("risk_preference", "平衡"),
    )
    result["final_score_val"] = result.apply(lambda row: _weighted_total(row, weights), axis=1)
    return result


def sort_top_k(df: pd.DataFrame, k: int = 10) -> pd.DataFrame:
    """按综合分和 ROI 排序，返回 TOP K，并追加 rank 列。"""
    sort_columns = ["final_score_val"]
    ascending = [False]
    if "roi_value" in df.columns:
        sort_columns.append("roi_value")
        ascending.append(False)

    top = df.sort_values(sort_columns, ascending=ascending).reset_index(drop=True).head(k)
    top.insert(0, "rank", range(1, len(top) + 1))
    return top


def weights_for(goal: str, risk_preference: str) -> dict[str, float]:
    """根据推广目标和风险偏好返回归一化后的评分权重。"""
    weights = GOAL_WEIGHTS.get(goal, GOAL_WEIGHTS["种草"]).copy()
    adjustment = RISK_WEIGHT_ADJUSTMENTS.get(risk_preference, 0)
    weights["risk"] = max(0.06, weights.get("risk", 0) + adjustment)

    non_risk_keys = [key for key in weights if key != "risk"]
    non_risk_total = sum(weights[key] for key in non_risk_keys)
    available = 1.0 - weights["risk"]
    for key in non_risk_keys:
        weights[key] = weights[key] / non_risk_total * available
    return weights


def _weighted_total(row: pd.Series, weights: dict[str, float]) -> float:
    score_map = {
        "audience": row.get("audience_score", 50),
        "cost": row.get("cost_score", 50),
        "risk": row.get("risk_score_val", 75),
        "followers": row.get("followers_score", 50),
        "engagement": row.get("engagement_score", 50),
        "conversion": row.get("conversion_score", 50),
        "cooperation": row.get("cooperation_score", 50),
    }
    total = sum(float(score_map.get(key, 50)) * weight for key, weight in weights.items())
    return round(max(0.0, min(100.0, total)), 2)


def _business_score(row: pd.Series) -> float:
    score = (
        float(row.get("cost_score", 50)) * 0.35
        + float(row.get("followers_score", 50)) * 0.20
        + float(row.get("engagement_score", 50)) * 0.20
        + float(row.get("conversion_score", 50)) * 0.20
        + float(row.get("cooperation_score", 50)) * 0.05
    )
    return round(max(0.0, min(100.0, score)), 2)


def _field_match_score(kol_field: Any, wanted_fields: Iterable[str]) -> float:
    wanted = [str(field).strip() for field in wanted_fields if str(field).strip()]
    if not wanted:
        return 0.0
    field_text = str(kol_field or "")
    hits = sum(1 for field in wanted if field in field_text)
    if hits == 0:
        return 0.0
    if hits >= 2:
        return 100.0
    return 78.0


def _minmax_score(series: pd.Series) -> pd.Series:
    min_val = series.min()
    max_val = series.max()
    if max_val == min_val:
        return pd.Series(50.0, index=series.index)
    return ((series - min_val) / (max_val - min_val) * 100).round(2)
