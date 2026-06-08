# roi.py
# ROI 预估模块（原子任务 9）
# 根据达人数据逐步估算：曝光量 → 互动量 → 转化量 → ROI
# 全部使用简单规则公式，不接入任何 LLM

import pandas as pd

# ------------------------------------------------------------------ #
#  默认值：当数据行中对应字段缺失或为 0/NaN 时使用                      #
# ------------------------------------------------------------------ #
_DEFAULTS = {
    "followers":       50_000,  # 默认粉丝数
    "engagement_rate":    3.0,  # 默认互动率（%）
    "conversion_rate":    3.0,  # 默认转化率（%）
    "price":            2_000,  # 默认报价（元）
}

# 曝光系数：假设内容平均触达粉丝数的 30%
# 可通过函数参数覆盖
_DEFAULT_EXPOSURE_RATE: float = 0.30

# 单次转化价值假设（元）；品牌可根据客单价调整
_DEFAULT_CONVERSION_VALUE: float = 100.0


def exposure_rate_for_goal(goal: str) -> float:
    """根据推广目标给出曝光系数。"""
    return {"曝光": 0.42, "拉新": 0.34, "转化": 0.28, "种草": 0.32}.get(goal, _DEFAULT_EXPOSURE_RATE)


def conversion_value_for_goal(goal: str) -> float:
    """根据推广目标给出单次转化价值假设。"""
    return {"转化": 130.0, "拉新": 110.0, "曝光": 80.0, "种草": 100.0}.get(goal, _DEFAULT_CONVERSION_VALUE)


# ------------------------------------------------------------------ #
#  工具函数：安全取值                                                   #
# ------------------------------------------------------------------ #

def _safe_get(row: pd.Series, field: str) -> float:
    """从数据行中取值，缺失或非正数时返回对应默认值。"""
    val = row.get(field, None)
    # NaN / None / 零 / 负数 均回退到默认值
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return float(_DEFAULTS[field])
    val = float(val)
    return val if val > 0 else float(_DEFAULTS[field])


# ------------------------------------------------------------------ #
#  各步骤公式函数                                                       #
# ------------------------------------------------------------------ #

def estimate_exposure(followers: float, exposure_rate: float = _DEFAULT_EXPOSURE_RATE) -> float:
    """预计曝光量 = 粉丝数 × 曝光系数。

    参数:
        followers: 粉丝数
        exposure_rate: 曝光系数，默认 0.30（30%）
    返回:
        预计曝光量（浮点数）
    """
    return followers * exposure_rate


def estimate_interactions(exposure: float, engagement_rate_pct: float) -> float:
    """预计互动量 = 预计曝光量 × 互动率。

    参数:
        exposure: 预计曝光量
        engagement_rate_pct: 互动率（百分数，如 3.8 表示 3.8%）
    返回:
        预计互动量（浮点数）
    """
    return exposure * (engagement_rate_pct / 100)


def estimate_conversions(interactions: float, conversion_rate_pct: float) -> float:
    """预计转化量 = 预计互动量 × 转化率。

    参数:
        interactions: 预计互动量
        conversion_rate_pct: 转化率（百分数，如 3.5 表示 3.5%）
    返回:
        预计转化量（浮点数）
    """
    return interactions * (conversion_rate_pct / 100)


def estimate_roi_value(
    conversions: float,
    price: float,
    conversion_value: float = _DEFAULT_CONVERSION_VALUE,
) -> float:
    """预估 ROI 数值 = 预计转化价值 / 报价。

    参数:
        conversions: 预计转化量
        price: 合作报价（元）
        conversion_value: 单次转化价值假设（元，默认 100）
    返回:
        ROI 数值（如 2.9 表示投入 1 元回报 2.9 元）
    """
    if price <= 0:
        return 0.0
    return (conversions * conversion_value) / price


def format_roi(roi_value: float) -> str:
    """将 ROI 浮点数格式化为 "1:X.X" 字符串。

    示例：2.9 → "1:2.9"
    """
    return f"1:{roi_value:.1f}"


# ------------------------------------------------------------------ #
#  单行计算入口                                                         #
# ------------------------------------------------------------------ #

def compute_roi_metrics(
    row: pd.Series,
    exposure_rate: float = _DEFAULT_EXPOSURE_RATE,
    conversion_value: float = _DEFAULT_CONVERSION_VALUE,
) -> dict:
    """对单条达人数据计算全部 ROI 指标，返回结果字典。

    参数:
        row: 单行达人数据（pd.Series）
        exposure_rate: 曝光系数，默认 0.30
        conversion_value: 单次转化价值（元），默认 100
    返回:
        字典，包含 estimated_exposure / estimated_interactions /
        estimated_conversions / roi_value / roi_label 五个键
    """
    # 安全取值（缺失字段使用默认值，不报错）
    followers       = _safe_get(row, "followers")
    engagement_rate = _safe_get(row, "engagement_rate")
    conversion_rate = _safe_get(row, "conversion_rate")
    price           = _safe_get(row, "price")

    # 逐步计算
    exposure    = estimate_exposure(followers, exposure_rate)
    interactions = estimate_interactions(exposure, engagement_rate)
    conversions  = estimate_conversions(interactions, conversion_rate)
    roi_val      = estimate_roi_value(conversions, price, conversion_value)

    return {
        "estimated_exposure":     round(exposure),
        "estimated_interactions": round(interactions),
        "estimated_conversions":  round(conversions, 2),
        "roi_value":              round(roi_val, 2),
        "roi_label":              format_roi(roi_val),
    }


# ------------------------------------------------------------------ #
#  批量计算入口                                                         #
# ------------------------------------------------------------------ #

def compute_roi_for_df(
    df: pd.DataFrame,
    exposure_rate: float = _DEFAULT_EXPOSURE_RATE,
    conversion_value: float = _DEFAULT_CONVERSION_VALUE,
) -> pd.DataFrame:
    """对候选达人 DataFrame 批量计算 ROI，返回追加列后的副本。

    新增列：estimated_exposure / estimated_interactions /
            estimated_conversions / roi_value / roi_label

    参数:
        df: 候选达人 DataFrame
        exposure_rate: 曝光系数，默认 0.30
        conversion_value: 单次转化价值（元），默认 100
    返回:
        追加 ROI 相关列后的 DataFrame 副本
    """
    result = df.copy()

    # 逐行计算并展开为多列
    metrics = result.apply(
        lambda row: compute_roi_metrics(row, exposure_rate, conversion_value),
        axis=1,
    )
    metrics_df = pd.DataFrame(list(metrics), index=result.index)

    # 合并回原 DataFrame
    result = pd.concat([result, metrics_df], axis=1)
    return result
