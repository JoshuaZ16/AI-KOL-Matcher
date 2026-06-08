# main.py
# 项目主入口
# 当前阶段：默认启动前端工作台；Markdown 报告仅作为开发备用导出

import argparse
import re
import pandas as pd

from utils import load_kol_database
from filter import filter_kols
from input_parser import GOAL_LABELS, RISK_PREFERENCES, parse_requirements, requirements_for_report
from report import build_report, generate_report, save_report
from roi import compute_roi_for_df, conversion_value_for_goal, exposure_rate_for_goal
from scorer import score_for_requirements, sort_top_k
from web_app import run as run_web_app


DEFAULT_PROMOTION_GOAL = "种草"
DEFAULT_RISK_PREFERENCE = "平衡"
PLATFORM_ALIASES = {
    "b站": "B站",
    "B站": "B站",
    "bilibili": "B站",
    "哔哩哔哩": "B站",
}


def _ask_required_text(label: str, hint: str = "") -> str:
    """读取必填文本字段。"""
    while True:
        suffix = f"（{hint}）" if hint else ""
        value = input(f"{label}{suffix}：").strip()
        if not value:
            print(f"  {label}为必填项，请补充。")
            continue
        if len(value) > 100:
            print("  文本过长，建议控制在 100 字以内。")
            continue
        if len(value) < 2:
            print("  描述过短，请再具体一点。")
            continue
        return value


def _ask_optional_text(label: str, default: str = "") -> str:
    """读取可选文本字段。"""
    default_hint = f"，默认：{default}" if default else ""
    value = input(f"{label}（可选{default_hint}）：").strip()
    return value or default


def _ask_budget_range() -> tuple[float, float]:
    """读取并校验预算区间。"""
    while True:
        raw = input("预算范围（单个达人，例：1000-3000）：").strip()
        numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", raw.replace(",", ""))]

        if len(numbers) < 2:
            print("  请输入预算下限和上限，例如 1000-3000。")
            continue

        budget_min, budget_max = min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
        if budget_min < 500:
            print("  预算下限不能低于 500 元。")
            continue
        if budget_max > 50000:
            print("  预算上限不能超过 50000 元。")
            continue
        if budget_min >= budget_max:
            print("  预算下限必须小于预算上限。")
            continue
        return budget_min, budget_max


def _ask_platforms(available_platforms: list[str]) -> list[str]:
    """读取并校验投放平台。"""
    available_set = set(available_platforms)
    while True:
        raw = input(f"投放平台（可多选，用 / 或 、 分隔；可选：{'、'.join(available_platforms)}）：").strip()
        if not raw:
            print("  投放平台为必填项，请至少选择 1 个。")
            continue

        parts = [item.strip() for item in re.split(r"[/、,，;；\s]+", raw) if item.strip()]
        platforms = []
        invalid = []
        for item in parts:
            normalized = PLATFORM_ALIASES.get(item, PLATFORM_ALIASES.get(item.lower(), item))
            if normalized in available_set:
                if normalized not in platforms:
                    platforms.append(normalized)
            else:
                invalid.append(item)

        if invalid:
            print(f"  暂不支持平台：{'、'.join(invalid)}。请从可选平台中选择。")
            continue
        if not platforms:
            print("  请至少选择 1 个有效投放平台。")
            continue
        return platforms


def _ask_choice(label: str, choices: tuple[str, ...], default: str) -> str:
    """读取可选枚举字段。"""
    raw = input(f"{label}（可选：{'/'.join(choices)}，默认：{default}）：").strip()
    if not raw:
        return default
    if raw in choices:
        return raw
    print(f"  未识别“{raw}”，已使用默认值：{default}")
    return default


def collect_requirements(available_platforms: list[str]) -> dict:
    """通过命令行表单收集结构化投放需求。"""
    print("请填写本次投放需求。带 * 的字段必填。\n")
    target_audience = _ask_required_text("* 目标受众", "例：大学生、职场新人、宝妈、科技爱好者")
    fields = _ask_required_text("* 内容领域", "例：校园/职场/美妆/科技/美食")
    budget_min, budget_max = _ask_budget_range()
    platforms = _ask_platforms(available_platforms)

    product = _ask_optional_text("推广产品/行业", "未填写产品")
    content_style = _ask_optional_text("内容风格/偏好", "真实、可信、自然")
    promotion_goal = _ask_choice("推广目标", GOAL_LABELS, DEFAULT_PROMOTION_GOAL)
    risk_preference = _ask_choice("风险偏好", RISK_PREFERENCES, DEFAULT_RISK_PREFERENCE)

    return parse_requirements(
        {
            "targetAudience": target_audience,
            "fields": fields,
            "budgetMin": budget_min,
            "budgetMax": budget_max,
            "platforms": platforms,
            "product": product,
            "contentStyle": content_style,
            "promotionGoal": promotion_goal,
            "riskPreference": risk_preference,
        }
    )


def _save_empty_report(requirements: dict) -> str:
    """候选集为空时也输出一份可追踪的报告。"""
    report_text = build_report(
        pd.DataFrame(
            columns=[
                "排名",
                "kol_name",
                "platform",
                "followers",
                "price",
                "final_score_val",
                "roi_label",
                "risk_note",
            ]
        ),
        requirements=requirements_for_report(requirements),
        advice=(
            "**预算分配**：当前条件没有命中达人，建议先放宽预算区间或内容领域。\n\n"
            "**平台组合**：可保留核心平台，同时增加一个相近平台做候选池扩容。\n\n"
            "**注意事项**：放宽条件后仍需人工复核达人内容调性、档期和数据真实性。"
        ),
    )
    return str(save_report(report_text))


def run_cli_export():
    """开发备用：命令行输入并导出 Markdown。客户主流程应使用前端工作台。"""
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)
    pd.set_option("display.unicode.east_asian_width", True)

    # ===== 1. 读取数据 =====
    df = load_kol_database()
    print(f"达人库已加载，共 {len(df)} 条记录。\n")

    # ===== 2. 交互式输入需求 =====
    available_platforms = sorted(df["platform"].dropna().unique().tolist())
    requirements_for_scoring = collect_requirements(available_platforms)
    requirements = requirements_for_report(requirements_for_scoring)

    # ===== 3. 初筛 =====
    filtered = filter_kols(
        df,
        requirements_for_scoring["platforms"],
        requirements_for_scoring["budget_min"],
        requirements_for_scoring["budget_max"],
        requirements_for_scoring["fields"],
    )
    print(f"初筛结果：{len(df)} → {len(filtered)} 位候选达人")
    if filtered.empty:
        saved_path = _save_empty_report(requirements_for_scoring)
        print("当前条件没有命中达人，请放宽预算、平台或内容领域后重试。")
        print(f"\n报告已保存至：{saved_path}")
        return

    # ===== 4. 评分 =====
    scored = score_for_requirements(filtered, requirements_for_scoring)

    # ===== 5. ROI 预估 =====
    scored = compute_roi_for_df(
        scored,
        exposure_rate=exposure_rate_for_goal(requirements_for_scoring["promotion_goal"]),
        conversion_value=conversion_value_for_goal(requirements_for_scoring["promotion_goal"]),
    )

    # ===== 6. 排序 + 取 TOP 10 =====
    top10 = sort_top_k(scored, 10).rename(columns={"rank": "排名"})

    # ===== 7. 生成报告（控制台 + output/report.md）=====
    saved_path = generate_report(
        top10,
        requirements=requirements,
        print_to_console=True,
    )
    print(f"\n报告已保存至：{saved_path}")


def main():
    """主流程入口：默认启动前端推荐工作台。"""
    parser = argparse.ArgumentParser(description="AI KOL 达人匹配助手")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument(
        "--cli-export-md",
        action="store_true",
        help="开发备用：使用命令行交互并导出 Markdown 报告",
    )
    args = parser.parse_args()

    if args.cli_export_md:
        run_cli_export()
        return

    run_web_app(args.host, args.port)


if __name__ == "__main__":
    main()
