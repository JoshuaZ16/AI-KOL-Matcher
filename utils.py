# utils.py
# 通用工具模块：数据加载、路径管理、LLM 客户端

import json
import os
import re
from io import StringIO
from pathlib import Path
from typing import Any
import pandas as pd
from dotenv import load_dotenv

# ------------------------------------------------------------------ #
#  路径配置                                                             #
# ------------------------------------------------------------------ #

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR     = PROJECT_ROOT / "data"
OUTPUT_DIR   = PROJECT_ROOT / "output"
KOL_CSV_PATH = DATA_DIR / "kol_database.csv"

# 自动加载项目根目录下的 .env（如有）
load_dotenv(PROJECT_ROOT / ".env")


# ------------------------------------------------------------------ #
#  数据加载                                                             #
# ------------------------------------------------------------------ #

def load_kol_database(csv_path: Path = KOL_CSV_PATH) -> pd.DataFrame:
    """读取达人数据库 CSV，返回 pandas DataFrame。"""
    return normalize_kol_dataframe(pd.read_csv(csv_path, encoding="utf-8-sig"))


REQUIRED_KOL_COLUMNS = (
    "kol_name",
    "platform",
    "followers",
    "field",
    "price",
    "engagement_rate",
    "conversion_rate",
    "audience",
)

OPTIONAL_KOL_DEFAULTS: dict[str, Any] = {
    "kol_id": "",
    "avg_likes": 0,
    "avg_comments": 0,
    "cooperation_count": 0,
    "risk_note": "无风险",
}

KOL_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "kol_id": ("kol_id", "达人ID", "达人编号", "id", "ID"),
    "kol_name": ("kol_name", "达人名称", "名称", "昵称", "name", "kol"),
    "platform": ("platform", "所属平台", "平台"),
    "followers": ("followers", "粉丝数", "粉丝量", "粉丝"),
    "field": ("field", "内容领域", "领域", "类目", "垂类"),
    "price": ("price", "合作报价（元）", "合作报价", "报价", "价格", "预算"),
    "avg_likes": ("avg_likes", "平均点赞数", "平均点赞", "点赞数"),
    "avg_comments": ("avg_comments", "平均评论数", "平均评论", "评论数"),
    "engagement_rate": ("engagement_rate", "互动率（%）", "互动率", "互动率%"),
    "conversion_rate": ("conversion_rate", "历史转化率（%）", "转化率", "转化率%"),
    "audience": ("audience", "受众画像", "目标受众", "受众", "粉丝画像"),
    "cooperation_count": ("cooperation_count", "历史合作次数", "合作次数", "合作数"),
    "risk_note": ("risk_note", "风险备注", "风险提示", "风险"),
}

NUMERIC_KOL_COLUMNS = (
    "followers",
    "price",
    "avg_likes",
    "avg_comments",
    "engagement_rate",
    "conversion_rate",
    "cooperation_count",
)


def load_kol_database_from_text(csv_text: str, source_name: str = "上传 CSV") -> pd.DataFrame:
    """从用户上传的 CSV 文本读取达人库，并做字段校验与标准化。"""
    text = str(csv_text or "").strip("\ufeff \n\r\t")
    if not text:
        raise ValueError("上传的达人 CSV 为空。")
    if len(text.encode("utf-8")) > 5 * 1024 * 1024:
        raise ValueError("上传的达人 CSV 超过 5MB，请精简后再试。")

    try:
        df = pd.read_csv(StringIO(text))
    except Exception as exc:
        raise ValueError(f"上传的达人 CSV 无法解析：{exc}") from exc

    return normalize_kol_dataframe(df, source_name=source_name)


def normalize_kol_dataframe(df: pd.DataFrame, source_name: str = "达人库") -> pd.DataFrame:
    """把达人库列名、数值和默认字段整理成推荐链路需要的结构。"""
    if df.empty:
        raise ValueError(f"{source_name} 没有任何达人记录。")

    result = df.copy()
    result.columns = [str(column).strip().lstrip("\ufeff") for column in result.columns]
    result = result.rename(columns=_column_rename_map(result.columns))

    missing = [column for column in REQUIRED_KOL_COLUMNS if column not in result.columns]
    if missing:
        raise ValueError(
            f"{source_name} 缺少必要字段：{', '.join(missing)}。"
            "请按模板提供 kol_name/platform/followers/field/price/"
            "engagement_rate/conversion_rate/audience。"
        )

    for column, default in OPTIONAL_KOL_DEFAULTS.items():
        if column not in result.columns:
            result[column] = default

    for column in NUMERIC_KOL_COLUMNS:
        result[column] = result[column].apply(_parse_number).fillna(0)

    text_columns = ["kol_id", "kol_name", "platform", "field", "audience", "risk_note"]
    for column in text_columns:
        result[column] = result[column].fillna("").astype(str).str.strip()

    result = result[result["kol_name"].astype(bool)].reset_index(drop=True)
    if result.empty:
        raise ValueError(f"{source_name} 没有有效的达人名称。")

    empty_ids = result["kol_id"].eq("")
    result.loc[empty_ids, "kol_id"] = [
        f"UPLOAD_{index + 1:03d}" for index in result.index[empty_ids]
    ]
    return result


def _column_rename_map(columns: pd.Index) -> dict[str, str]:
    normalized_lookup = {_normalize_header(column): column for column in columns}
    rename_map: dict[str, str] = {}
    for canonical, aliases in KOL_COLUMN_ALIASES.items():
        for alias in aliases:
            matched = normalized_lookup.get(_normalize_header(alias))
            if matched is not None:
                rename_map[matched] = canonical
                break
    return rename_map


def _normalize_header(value: Any) -> str:
    return re.sub(r"[\s_（）()%()]+", "", str(value or "").strip().lower())


def _parse_number(value: Any) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return 0.0
    multiplier = 1.0
    if "万" in text:
        multiplier = 10_000.0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    return float(match.group(0)) * multiplier


# ------------------------------------------------------------------ #
#  LLM 客户端（Qwen / DashScope，OpenAI 兼容协议）                       #
# ------------------------------------------------------------------ #

# DashScope 提供的 OpenAI 兼容入口
_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 默认模型：qwen-turbo 速度快、价格低，适合本场景的短文本生成
DEFAULT_QWEN_MODEL = "qwen-turbo"

# 全局单例，避免重复创建 client
_llm_client = None


def get_llm_client():
    """返回（懒加载的）OpenAI 兼容客户端，指向 DashScope。

    需要在环境变量或 .env 中提供 DASHSCOPE_API_KEY。
    """
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "未找到 DASHSCOPE_API_KEY，请在 .env 中配置或导出为环境变量。"
        )

    # 延迟 import，避免未安装 openai 时其它模块也加载失败
    from openai import OpenAI

    _llm_client = OpenAI(api_key=api_key, base_url=_QWEN_BASE_URL)
    return _llm_client


def call_qwen(
    prompt: str,
    system: str = "你是专业的市场投放顾问，回答务必简洁、口语化、可执行。",
    model: str = DEFAULT_QWEN_MODEL,
    temperature: float = 0.5,
    max_tokens: int = 400,
) -> str:
    """调用 Qwen 生成文本，失败时返回空字符串，由调用方决定降级策略。

    参数:
        prompt: 用户提示词
        system: 系统提示词
        model: Qwen 模型名，默认 qwen-turbo
        temperature: 采样温度
        max_tokens: 最大输出 token
    返回:
        生成的纯文本，去除前后空白
    """
    try:
        client = get_llm_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        # 失败时打印警告但不抛出，让调用方走降级模板
        print(f"[warn] Qwen 调用失败：{e}")
        return ""


def call_qwen_json(
    prompt: str,
    system: str = "你只返回合法 JSON，不返回 Markdown、解释或代码块。",
    model: str = DEFAULT_QWEN_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 800,
) -> dict:
    """调用 Qwen 并解析 JSON，失败时返回空 dict 供调用方降级。"""
    text = call_qwen(
        prompt=prompt,
        system=system,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if not text:
        return {}

    candidates = [text]
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    print(f"[warn] Qwen JSON 解析失败：{text[:160]}")
    return {}
