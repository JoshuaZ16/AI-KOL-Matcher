# filter.py
# 达人初筛模块（原子任务 2）
# 根据用户需求（平台、预算、内容领域等）从达人库中过滤出候选达人
# 当前阶段：纯规则筛选，不涉及 AI

from typing import Iterable, Optional
import pandas as pd


def filter_by_platform(df: pd.DataFrame, platforms: Optional[Iterable[str]]) -> pd.DataFrame:
    """按平台筛选。

    参数:
        df: 待筛选 DataFrame
        platforms: 平台列表（如 ["小红书", "抖音"]），为空则不过滤
    返回:
        过滤后的 DataFrame
    """
    # 平台为空 → 不做过滤，直接返回
    if not platforms:
        return df
    # isin 支持多平台精确匹配
    return df[df["platform"].isin(list(platforms))]


def filter_by_budget(
    df: pd.DataFrame,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
) -> pd.DataFrame:
    """按预算区间筛选（基于 price 字段）。

    参数:
        df: 待筛选 DataFrame
        budget_min: 预算下限（含），为 None 则不限
        budget_max: 预算上限（含），为 None 则不限
    返回:
        过滤后的 DataFrame
    """
    result = df
    # 下限过滤
    if budget_min is not None:
        result = result[result["price"] >= budget_min]
    # 上限过滤
    if budget_max is not None:
        result = result[result["price"] <= budget_max]
    return result


def filter_by_field(df: pd.DataFrame, fields: Optional[Iterable[str]]) -> pd.DataFrame:
    """按内容领域筛选。

    数据库中的 field 字段形如 "校园/职场"、"美妆/护肤"，可能包含多个子领域。
    因此使用"包含任一关键词"的模糊匹配。

    参数:
        df: 待筛选 DataFrame
        fields: 用户期望的内容领域关键词列表，为空则不过滤
    返回:
        过滤后的 DataFrame
    """
    # 字段为空或字段不存在 → 不过滤
    if not fields:
        return df
    if "field" not in df.columns:
        return df

    # 任一关键词命中即保留（不区分大小写，na 视为不匹配）
    pattern = "|".join([str(f).strip() for f in fields if str(f).strip()])
    if not pattern:
        return df
    return df[df["field"].str.contains(pattern, case=False, na=False)]


def filter_kols(
    df: pd.DataFrame,
    platforms: Optional[Iterable[str]] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    fields: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """达人初筛主函数：依次执行平台、预算、内容领域筛选。

    参数:
        df: 完整达人数据库
        platforms: 平台列表，可为空
        budget_min: 预算下限，可为空
        budget_max: 预算上限，可为空
        fields: 内容领域关键词列表，可为空
    返回:
        筛选后的候选达人 DataFrame
    """
    # 复制一份避免修改原数据
    result = df.copy()
    # 1) 按平台筛选
    result = filter_by_platform(result, platforms)
    # 2) 按预算区间筛选
    result = filter_by_budget(result, budget_min, budget_max)
    # 3) 按内容领域筛选（字段存在时才生效）
    result = filter_by_field(result, fields)
    # 重置索引，便于后续处理
    return result.reset_index(drop=True)


def apply_optional_filters(df: pd.DataFrame, optional: Optional[dict] = None) -> pd.DataFrame:
    """按可选条件继续筛选达人。

    支持字段：followers_min / followers_max / engagement_min /
    conversion_min / cooperation_min。字段为空则跳过。
    """
    conditions = optional or {}
    result = df.copy()

    if conditions.get("followers_min") is not None:
        result = result[result["followers"] >= conditions["followers_min"]]
    if conditions.get("followers_max") is not None:
        result = result[result["followers"] <= conditions["followers_max"]]
    if conditions.get("engagement_min") is not None:
        result = result[result["engagement_rate"] >= conditions["engagement_min"]]
    if conditions.get("conversion_min") is not None:
        result = result[result["conversion_rate"] >= conditions["conversion_min"]]
    if conditions.get("cooperation_min") is not None:
        result = result[result["cooperation_count"] >= conditions["cooperation_min"]]

    return result.reset_index(drop=True)
