# report.py
# 报告生成模块
# 推荐理由与投放建议通过 Qwen LLM 生成；LLM 不参与评分排序
# LLM 失败时降级为规则模板
# 输出：控制台 + output/report.md

from pathlib import Path
from typing import Optional
import pandas as pd

from utils import OUTPUT_DIR, call_qwen


# ------------------------------------------------------------------ #
#  模板降级函数（无 LLM 时使用）                                        #
# ------------------------------------------------------------------ #

def _template_reason(row: pd.Series) -> str:
    """规则模板推荐理由，作为 LLM 调用失败时的兜底。"""
    audience_score = row.get("audience_score", 0)
    cost_score     = row.get("cost_score", 0)
    risk_score     = row.get("risk_score_val", 100)
    engagement     = row.get("engagement_rate", 0)
    conversion     = row.get("conversion_rate", 0)
    risk_note      = str(row.get("risk_note", "无风险")).strip()
    tags           = row.get("semantic_match_tags") or row.get("match_tags") or []
    semantic_score = float(row.get("semantic_score", audience_score) or 0)
    semantic_source = "embedding" if row.get("semantic_source") == "embedding" else "规则兜底"

    if audience_score >= 80:
        aud = "受众匹配度高"
    elif audience_score >= 50:
        aud = "受众部分匹配"
    else:
        aud = "受众覆盖一般"

    if cost_score >= 70:
        cost = f"性价比优秀（互动率 {engagement:.1f}%、转化率 {conversion:.1f}%）"
    elif cost_score >= 40:
        cost = f"性价比中等（互动率 {engagement:.1f}%、转化率 {conversion:.1f}%）"
    else:
        cost = f"性价比偏低（互动率 {engagement:.1f}%）"

    if risk_score >= 90:
        risk = f"风险等级低（{risk_note}）"
    elif risk_score >= 60:
        risk = f"存在中等风险（{risk_note}），建议人工核查"
    else:
        risk = f"风险较高（{risk_note}），需谨慎合作"

    tag_text = f"，标签命中{'、'.join(list(tags)[:3])}" if tags else ""
    return (
        f"该达人{aud}{tag_text}，语义匹配由{semantic_source}给出{semantic_score:.1f}分，"
        f"{cost}，{risk}，综合业务分决定其推荐位置。"
    )


# ------------------------------------------------------------------ #
#  LLM 推荐理由生成                                                     #
# ------------------------------------------------------------------ #

def generate_recommend_reason(row: pd.Series) -> str:
    """用 Qwen 生成推荐理由（50-100 字），失败时降级为模板。"""
    prompt = (
        "你是 KOL 投放顾问，请根据以下达人数据，写一段 50-100 字的投放推荐理由，"
        "要求：客观引用数据、中文、不加标题、不换行。"
        "注意：排名和分数已经由规则评分器确定，你只负责解释原因，不得调整排名或虚构数据。\n\n"
        f"达人：{row.get('kol_name', '')}\n"
        f"平台：{row.get('platform', '')}\n"
        f"粉丝数：{int(row.get('followers', 0)):,}\n"
        f"内容领域：{row.get('field', '')}\n"
        f"受众画像：{row.get('audience', '')}\n"
        f"互动率：{row.get('engagement_rate', 0):.1f}%\n"
        f"转化率：{row.get('conversion_rate', 0):.1f}%\n"
        f"报价：{int(row.get('price', 0))} 元\n"
        f"历史合作次数：{int(row.get('cooperation_count', 0))}\n"
        f"受众匹配分：{row.get('audience_score', 0):.1f}/100\n"
        f"语义相似度：{row.get('semantic_score', row.get('audience_score', 0)):.1f}/100\n"
        f"语义来源：{row.get('semantic_source', 'rule_fallback')}\n"
        f"业务表现分：{row.get('business_score', 0):.1f}/100\n"
        f"性价比分：{row.get('cost_score', 0):.1f}/100\n"
        f"风险备注：{row.get('risk_note', '无风险')}\n"
        f"达人标签：{'、'.join(row.get('match_tags', []) or [])}\n"
        f"语义命中标签：{'、'.join(row.get('semantic_match_tags', []) or [])}\n"
        f"综合得分：{row.get('final_score_val', 0):.1f}/100"
    )
    result = call_qwen(prompt, max_tokens=200)
    # LLM 无输出则降级
    return result if result else _template_reason(row)


def generate_api_reason(row: pd.Series, requirements: Optional[dict] = None) -> str:
    """为 JSON 接口生成单条达人推荐理由。

    API 默认使用稳定的规则模板，避免一次前端请求触发多次 LLM 调用导致
    Demo 变慢；Markdown 报告仍可通过 generate_report 使用 Qwen。
    """
    goal = (requirements or {}).get("promotion_goal", "种草")
    audience_score = float(row.get("audience_score", 0))
    semantic_score = float(row.get("semantic_score", audience_score) or 0)
    source = "embedding" if row.get("semantic_source") == "embedding" else "规则兜底"
    if audience_score >= 80:
        audience = "受众高度匹配"
    elif audience_score >= 50:
        audience = "受众部分匹配"
    else:
        audience = "受众有一定重合"

    return (
        f"{audience}，语义相似度{semantic_score:.1f}分（{source}），报价{int(row.get('price', 0))}元，"
        f"互动率{float(row.get('engagement_rate', 0)):.1f}%，"
        f"转化率{float(row.get('conversion_rate', 0)):.1f}%，"
        f"预估ROI {row.get('roi_label', '-')}，综合业务分决定其进入{goal}型投放推荐。"
    )


def generate_api_advice(recommendations: list[dict], requirements: Optional[dict] = None) -> dict[str, str]:
    """为 JSON 接口生成总体投放建议。"""
    if not recommendations:
        return {
            "budget": "暂无候选达人，建议先放宽平台、预算或内容领域条件。",
            "platform": "暂无平台组合建议。",
            "risk": "最终投放决策仍需人工复核。",
        }

    total_budget = int((requirements or {}).get("total_budget", 0) or 0)
    top_names = "、".join(item["name"] for item in recommendations[:3])
    platforms = "、".join(sorted({item["platform"] for item in recommendations}))
    risky = [item["name"] for item in recommendations if item.get("risk") in ("中", "中高", "高")]
    risky_text = "、".join(risky[:3]) if risky else "暂无明显高风险达人"

    return {
        "budget": f"建议优先测试前3名达人（{top_names}），总预算{total_budget}元内可按60%主投、40%测试分配。",
        "platform": f"当前候选集中在{platforms}，建议先围绕得分最高的平台打样，再根据转化数据扩展。",
        "risk": f"需重点复核：{risky_text}。最终投放决策需人工确认档期、内容调性和数据真实性。",
    }


# ------------------------------------------------------------------ #
#  LLM 投放建议生成（原子任务 10）                                       #
# ------------------------------------------------------------------ #

def generate_placement_advice(top10: pd.DataFrame, requirements: Optional[dict] = None) -> str:
    """用 Qwen 生成总体投放建议（200-300 字），失败时返回通用建议。"""
    # 将 TOP10 的关键字段压缩成简短列表交给 LLM
    kol_summary = "\n".join(
        f"  #{int(row['排名'])} {row['kol_name']}（{row['platform']}）"
        f" 粉丝:{int(row['followers']):,} 报价:{int(row['price'])}元"
        f" 得分:{row['final_score_val']:.1f} ROI:{row.get('roi_label', '-')}"
        f" 风险:{row.get('risk_note', '无风险')}"
        for _, row in top10.iterrows()
    )

    req_text = ""
    if requirements:
        req_text = "\n".join(f"  {k}：{v}" for k, v in requirements.items())
        req_text = f"\n投放需求：\n{req_text}"

    prompt = (
        "你是 KOL 投放顾问，请根据以下 TOP10 达人名单，给出 200-300 字的投放建议，"
        "包含：预算分配、平台组合、注意事项三部分，最后附一句人工复核提示。"
        "要求：分点列举、具体可执行、中文。"
        "注意：TOP10 顺序已经由规则评分器确定，你只能基于该顺序提出组合和投放建议，不得重排名次或虚构数据。\n"
        f"{req_text}\n\n"
        f"TOP10 达人：\n{kol_summary}"
    )
    result = call_qwen(prompt, max_tokens=500)
    if result:
        return result

    # 降级：通用建议
    return (
        "**预算分配**：建议优先投入排名前 3 的高匹配达人（占总预算 60%），"
        "其余 40% 均摊测试达人。\n\n"
        "**平台组合**：集中在所选平台深耕，避免多平台分散。\n\n"
        "**注意事项**：广告比例较高的达人需要求原创内容；首次合作须签合作协议。\n\n"
        "> 最终投放决策需人工复核。"
    )


# ------------------------------------------------------------------ #
#  Markdown 表格                                                        #
# ------------------------------------------------------------------ #

def _fmt_followers(n: float) -> str:
    """5万 / 12万 格式化。"""
    n = int(n)
    if n >= 10_000:
        val = n / 10_000
        # 整万去掉小数，否则保留一位
        return f"{val:.0f}万" if val == int(val) else f"{val:.1f}万"
    return str(n)


def build_top10_table(top10: pd.DataFrame) -> str:
    """渲染 TOP10 Markdown 表格。"""
    header = "| 排名 | 达人名 | 平台 | 粉丝数 | 报价（元） | 总分 | 预估 ROI | 风险提示 |"
    sep    = "|:----:|--------|:----:|-------:|----------:|-----:|----------|----------|"
    lines  = [header, sep]
    for _, row in top10.iterrows():
        lines.append(
            f"| {int(row['排名'])} "
            f"| {row['kol_name']} "
            f"| {row['platform']} "
            f"| {_fmt_followers(row['followers'])} "
            f"| {int(row['price'])} "
            f"| {row['final_score_val']:.1f} "
            f"| {row.get('roi_label', '-')} "
            f"| {row.get('risk_note', '无风险')} |"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ #
#  报告装配                                                             #
# ------------------------------------------------------------------ #

def build_report(
    top10: pd.DataFrame,
    requirements: Optional[dict] = None,
    reasons: Optional[dict] = None,
    advice: str = "",
) -> str:
    """组装完整 Markdown 报告。

    参数:
        top10: 已排序的 TOP10 DataFrame
        requirements: 用户需求字典（可选）
        reasons: {kol_name: 推荐理由文本} 字典（可选，缺失则用模板）
        advice: 投放建议文本
    """
    parts: list[str] = ["# AI KOL 达人匹配推荐报告\n"]

    if requirements:
        parts.append("## 投放需求\n")
        for k, v in requirements.items():
            parts.append(f"- **{k}**：{v}")
        parts.append("")

    parts.append("## TOP 10 达人推荐\n")
    parts.append(build_top10_table(top10))
    parts.append("")

    parts.append("## 评分与 AI 使用说明\n")
    parts.append(
        "- 排名由综合评分模块根据语义匹配、报价性价比、粉丝、互动率、转化率、风险和 ROI 等数据计算得出。\n"
        "- LLM 只用于把自然语言需求抽取成结构化字段；embedding 只用于计算语义相似度，不直接决定 TOP10。\n"
        "- 当 LLM 或 embedding 不可用时，系统会降级到规则语义匹配，业务评分仍继续生效。\n"
        "- 最终投放决策仍需结合品牌调性、达人档期和内容质量人工复核。"
    )
    parts.append("")

    parts.append("## 匹配逻辑升级\n")
    parts.append(
        "1. **标签化**：系统会从达人名称、内容领域、受众画像、风险备注和核心指标中抽取标签，"
        "例如校园、职场、美妆、真实感、种草型、转化型、曝光型、学生党、女性用户、高互动、低风险。\n"
        "2. **权重匹配**：不同推广目标使用不同权重；拉新更看重受众匹配、性价比和转化效率，"
        "曝光更看重粉丝规模、平台影响力和内容传播力。\n"
        "3. **语义匹配**：用户描述不必完全命中标准关键词。系统优先用 embedding 计算用户需求与达人画像的"
        "语义相似度；若接口不可用，则用规则标签兜底，再与业务表现、风险和 ROI 一起参与综合排序。"
    )
    parts.append("")

    parts.append("## 推荐理由\n")
    for _, row in top10.iterrows():
        reason = (reasons or {}).get(row["kol_name"]) or _template_reason(row)
        parts.append(f"**#{int(row['排名'])}  {row['kol_name']}**：{reason}\n")

    parts.append("## 投放建议\n")
    parts.append(advice or "（投放建议生成失败，请人工制定。）")
    parts.append("")

    parts.append("## 人工复核提示\n")
    parts.append(
        "- 最终投放决策需人工复核。\n"
        "- 广告比例较高的达人建议要求原创内容并签订合作协议。\n"
        "- 首次合作的达人建议核实数据真实性与档期。"
    )
    return "\n".join(parts)


# ------------------------------------------------------------------ #
#  输出                                                                 #
# ------------------------------------------------------------------ #

def save_report(report_text: str, output_path: Optional[Path] = None) -> Path:
    """写入 Markdown 文件，默认 output/report.md。"""
    path = output_path or (OUTPUT_DIR / "report.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8")
    return path


def generate_report(
    top10: pd.DataFrame,
    requirements: Optional[dict] = None,
    output_path: Optional[Path] = None,
    print_to_console: bool = True,
) -> Path:
    """报告生成主入口：LLM 生成内容 → 装配 → 控制台 → 文件。

    逐条调用 Qwen 生成推荐理由（带进度提示），再生成整体投放建议。
    """
    # 1) 逐条生成推荐理由
    print("正在生成推荐理由（Qwen）...")
    reasons: dict[str, str] = {}
    for _, row in top10.iterrows():
        name   = row["kol_name"]
        rank   = int(row["排名"])
        print(f"  [{rank:02d}/10] {name} ...", end=" ", flush=True)
        reason = generate_recommend_reason(row)
        reasons[name] = reason
        print("完成")

    # 2) 生成整体投放建议
    print("正在生成投放建议（Qwen）...", end=" ", flush=True)
    advice = generate_placement_advice(top10, requirements)
    print("完成")

    # 3) 装配报告
    report_text = build_report(top10, requirements, reasons, advice)

    # 4) 输出
    if print_to_console:
        print("\n" + "=" * 60)
        print(report_text)
        print("=" * 60)

    path = save_report(report_text, output_path)
    return path
