const state = {
  options: null,
  recommendations: [],
  selectedId: null,
  lastPayload: null,
  lastResult: null,
  customCsv: null,
  formTouched: {
    singleBudget: false,
    promotionGoal: false,
    riskPreference: false,
  },
};

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

const els = {
  form: document.querySelector("#requirementsForm"),
  platformOptions: document.querySelector("#platformOptions"),
  fieldOptions: document.querySelector("#fieldOptions"),
  resultsBody: document.querySelector("#resultsBody"),
  detailContent: document.querySelector("#detailContent"),
  summaryMessage: document.querySelector("#summaryMessage"),
  candidateCount: document.querySelector("#candidateCount"),
  averageScore: document.querySelector("#averageScore"),
  plannedSpend: document.querySelector("#plannedSpend"),
  singleBudget: document.querySelector("input[name='singleBudget']"),
  singleBudgetValue: document.querySelector("#singleBudgetValue"),
  exportHtmlButton: document.querySelector("#exportHtmlButton"),
  kolCsvInput: document.querySelector("#kolCsvInput"),
  kolCsvStatus: document.querySelector("#kolCsvStatus"),
  clearKolCsvButton: document.querySelector("#clearKolCsvButton"),
};

async function init() {
  bindForm();
  await loadOptions();
  updateBudgetLabel();
}

function bindForm() {
  els.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await runRecommendation();
  });
  els.singleBudget.addEventListener("input", () => {
    state.formTouched.singleBudget = true;
    updateBudgetLabel();
  });
  els.form.querySelectorAll("input[name='promotionGoal']").forEach((input) => {
    input.addEventListener("change", () => {
      state.formTouched.promotionGoal = true;
    });
  });
  els.form.querySelectorAll("input[name='riskPreference']").forEach((input) => {
    input.addEventListener("change", () => {
      state.formTouched.riskPreference = true;
    });
  });
  els.kolCsvInput.addEventListener("change", handleCsvUpload);
  els.clearKolCsvButton.addEventListener("click", clearCustomCsv);
  els.exportHtmlButton.addEventListener("click", exportHtmlReport);
}

async function loadOptions() {
  const response = await fetch("/api/options");
  state.options = await response.json();
  renderCheckboxes(els.platformOptions, state.options.platforms, []);
  renderCheckboxes(els.fieldOptions, state.options.fields, []);
}

function renderCheckboxes(container, values, defaults) {
  container.innerHTML = values
    .map((value) => {
      const checked = defaults.includes(value) ? "checked" : "";
      return `<label><input type="checkbox" value="${escapeHtml(value)}" ${checked}>${escapeHtml(value)}</label>`;
    })
    .join("");
}

function updateBudgetLabel() {
  els.singleBudgetValue.textContent = currency.format(Number(els.singleBudget.value || 0));
}

async function handleCsvUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  if (!file.name.toLowerCase().endsWith(".csv")) {
    setCsvError("请上传 CSV 文件。");
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    setCsvError("CSV 不能超过 5MB。");
    return;
  }

  try {
    const text = await file.text();
    const preview = summarizeCsv(text);
    state.customCsv = {
      name: file.name,
      text,
      rowCount: preview.rowCount,
      platforms: preview.platforms,
      fields: preview.fields,
      error: "",
    };
    els.kolCsvStatus.textContent = `已选择 ${file.name}，共 ${preview.rowCount} 位达人。`;
    els.kolCsvStatus.className = "upload-status";
    els.clearKolCsvButton.disabled = false;
    if (preview.platforms.length) renderCheckboxes(els.platformOptions, preview.platforms, []);
    if (preview.fields.length) renderCheckboxes(els.fieldOptions, preview.fields, []);
  } catch (error) {
    setCsvError(error.message || "CSV 读取失败。");
  }
}

function clearCustomCsv() {
  state.customCsv = null;
  els.kolCsvInput.value = "";
  els.kolCsvStatus.textContent = "未上传时使用默认达人库。";
  els.kolCsvStatus.className = "";
  els.clearKolCsvButton.disabled = true;
  renderCheckboxes(els.platformOptions, state.options?.platforms || [], []);
  renderCheckboxes(els.fieldOptions, state.options?.fields || [], []);
}

function setCsvError(message) {
  state.customCsv = { error: message };
  els.kolCsvInput.value = "";
  els.kolCsvStatus.textContent = message;
  els.kolCsvStatus.className = "upload-error";
  els.clearKolCsvButton.disabled = false;
}

function summarizeCsv(text) {
  const rows = parseCsvRows(text);
  if (rows.length < 2) {
    throw new Error("CSV 至少需要表头和 1 行达人数据。");
  }

  const headers = rows[0].map((header) => normalizeHeader(header));
  const platformIndex = findHeaderIndex(headers, ["platform", "所属平台", "平台"]);
  const fieldIndex = findHeaderIndex(headers, ["field", "内容领域", "领域", "类目", "垂类"]);
  const dataRows = rows.slice(1).filter((row) => row.some((cell) => String(cell || "").trim()));
  if (!dataRows.length) {
    throw new Error("CSV 没有有效的达人记录。");
  }

  return {
    rowCount: dataRows.length,
    platforms: platformIndex >= 0 ? uniqueValues(dataRows.map((row) => row[platformIndex])) : [],
    fields: fieldIndex >= 0 ? splitFieldValues(dataRows.map((row) => row[fieldIndex])) : [],
  };
}

function parseCsvRows(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"' && inQuotes && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((items) => items.some((item) => String(item || "").trim()));
}

function findHeaderIndex(headers, aliases) {
  const normalizedAliases = aliases.map((alias) => normalizeHeader(alias));
  return headers.findIndex((header) => normalizedAliases.includes(header));
}

function normalizeHeader(value) {
  return String(value || "")
    .trim()
    .replace(/^\uFEFF/, "")
    .replace(/[\s_（）()%()]+/g, "")
    .toLowerCase();
}

function splitFieldValues(values) {
  const result = [];
  values.forEach((value) => {
    String(value || "")
      .split(/[、,，/]/)
      .map((item) => item.trim())
      .filter(Boolean)
      .forEach((item) => result.push(item));
  });
  return uniqueValues(result);
}

function uniqueValues(values) {
  return Array.from(new Set(values.map((value) => String(value || "").trim()).filter(Boolean))).slice(0, 40);
}

async function runRecommendation() {
  const submitButton = els.form.querySelector("button[type='submit']");
  const validationError = validatePayload();
  if (validationError) {
    els.summaryMessage.textContent = validationError;
    els.resultsBody.innerHTML = `<tr><td colspan="9" class="empty-state">请先补全必填需求。</td></tr>`;
    els.detailContent.className = "detail-empty";
    els.detailContent.textContent = "暂无详情。";
    els.exportHtmlButton.disabled = true;
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "正在生成推荐";
  try {
    const payload = collectPayload();
    const response = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "推荐生成失败");
    }
    state.lastPayload = payload;
    state.lastResult = data;
    state.recommendations = data.recommendations || [];
    state.selectedId = state.recommendations[0]?.kolId || null;
    els.exportHtmlButton.disabled = !state.recommendations.length;
    renderSummary(data.summary);
    renderResults();
    renderDetail(getSelected());
  } catch (error) {
    state.lastResult = null;
    els.exportHtmlButton.disabled = true;
    els.summaryMessage.textContent = error.message;
    els.resultsBody.innerHTML = `<tr><td colspan="9" class="empty-state">推荐生成失败，请检查本地服务。</td></tr>`;
    els.detailContent.className = "detail-empty";
    els.detailContent.textContent = "暂无详情。";
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "生成 TOP10 推荐";
  }
}

function collectPayload() {
  const data = new FormData(els.form);
  return {
    query: data.get("query"),
    product: data.get("product"),
    targetAudience: data.get("targetAudience"),
    platforms: checkedValues(els.platformOptions),
    singleBudget: state.formTouched.singleBudget ? Number(data.get("singleBudget")) : null,
    totalBudget: Number(data.get("totalBudget")),
    fields: checkedValues(els.fieldOptions),
    promotionGoal: state.formTouched.promotionGoal ? data.get("promotionGoal") : "",
    riskPreference: state.formTouched.riskPreference ? data.get("riskPreference") : "",
    customKolCsv: state.customCsv?.text || "",
    customKolCsvName: state.customCsv?.name || "",
    formTouched: { ...state.formTouched },
    optional: {
      followersMin: nullableNumber(data.get("followersMin")),
      followersMax: nullableNumber(data.get("followersMax")),
      engagementMin: nullableNumber(data.get("engagementMin")),
      conversionMin: nullableNumber(data.get("conversionMin")),
      cooperationMin: nullableNumber(data.get("cooperationMin")),
    },
  };
}

function validatePayload() {
  const data = new FormData(els.form);
  const query = String(data.get("query") || "").trim();
  const targetAudience = String(data.get("targetAudience") || "").trim();
  const singleBudget = Number(data.get("singleBudget"));

  if (!query && !targetAudience) {
    return "请填写自然语言需求或目标人群。";
  }
  if (state.customCsv?.error) {
    return state.customCsv.error;
  }
  if (state.formTouched.singleBudget && (!Number.isFinite(singleBudget) || singleBudget < 500 || singleBudget > 50000)) {
    return "请填写 500-50000 元之间的单个达人预算。";
  }
  return "";
}

function exportHtmlReport() {
  if (!state.lastResult || !state.recommendations.length) return;

  const html = buildExportHtml(state.lastPayload, state.lastResult);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `KOL达人推荐-${formatDateForFile(new Date())}.html`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function buildExportHtml(payload, result) {
  const requirements = result.requirements || payload || {};
  const summary = result.summary || {};
  const advice = result.placementAdvice || {};
  const rows = (result.recommendations || [])
    .map(
      (item) => `
        <tr>
          <td>#${item.rank}</td>
          <td><strong>${escapeHtml(item.name)}</strong><br><span>${escapeHtml(item.field)}</span></td>
          <td>${escapeHtml(item.platform)}</td>
          <td>${escapeHtml(item.followersLabel)}</td>
          <td>${escapeHtml(item.priceLabel)}</td>
          <td>${escapeHtml(String(item.score))}</td>
          <td>${escapeHtml(item.roi)}</td>
          <td>${escapeHtml(item.riskNote)}</td>
          <td>${escapeHtml(item.recommendation)}</td>
        </tr>
      `
    )
    .join("");

  const detailSections = (result.recommendations || [])
    .map(
      (item) => `
        <section class="kol-detail">
          <h3>#${item.rank} ${escapeHtml(item.name)}</h3>
          <p>${escapeHtml(item.platform)} · ${escapeHtml(item.field)} · ${escapeHtml(item.audience)}</p>
          <div class="metric-grid">
            ${exportMetric("综合分", item.score)}
            ${exportMetric("语义相似度", `${item.semanticScore ?? item.scoreBreakdown?.semantic ?? 0}`)}
            ${exportMetric("业务表现", `${item.businessScore ?? item.scoreBreakdown?.business ?? 0}`)}
            ${exportMetric("风险分", `${item.scoreBreakdown?.risk ?? item.metrics.riskScore ?? 0}`)}
            ${exportMetric("预估 ROI", item.roi)}
            ${exportMetric("互动率", `${item.metrics.engagementRate}%`)}
            ${exportMetric("转化率", `${item.metrics.conversionRate}%`)}
            ${exportMetric("预计曝光", item.metrics.estimatedExposure.toLocaleString("zh-CN"))}
          </div>
          <ul>
            <li><strong>推荐逻辑：</strong>${escapeHtml(item.details.why)}</li>
            <li><strong>语义命中：</strong>${escapeHtml(item.details.semanticFit)}</li>
            <li><strong>受众匹配：</strong>${escapeHtml(item.details.audienceFit)}</li>
            <li><strong>性价比：</strong>${escapeHtml(item.details.costValue)}</li>
            <li><strong>投放建议：</strong>${escapeHtml(item.details.priority)}；${escapeHtml(item.details.contentForm)}</li>
          </ul>
        </section>
      `
    )
    .join("");

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KOL 达人推荐结果</title>
  <style>
    body { margin: 0; background: #f6f7f8; color: #182026; font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif; letter-spacing: 0; }
    .page { max-width: 1180px; margin: 0 auto; padding: 30px 20px 48px; }
    header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; border-bottom: 2px solid #182026; padding-bottom: 18px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    h2 { margin: 28px 0 12px; font-size: 20px; }
    h3 { margin: 0 0 8px; font-size: 17px; }
    p { line-height: 1.65; }
    .meta { color: #64717c; font-size: 13px; text-align: right; }
    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 18px 0; }
    .summary div, .requirements div, .metric { border: 1px solid #dce2e7; background: #fff; border-radius: 8px; padding: 12px; }
    .summary span, .requirements span, .metric span { display: block; color: #64717c; font-size: 12px; font-weight: 700; margin-bottom: 5px; }
    .summary strong, .metric strong { font-size: 18px; }
    .requirements { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
    table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dce2e7; font-size: 13px; }
    th, td { border-bottom: 1px solid #dce2e7; padding: 11px 10px; text-align: left; vertical-align: top; }
    th { background: #eef3f4; color: #35444f; }
    td span { color: #64717c; }
    .advice { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .advice article, .kol-detail { border: 1px solid #dce2e7; background: #fff; border-radius: 8px; padding: 14px; }
    .kol-detail { margin-bottom: 12px; break-inside: avoid; }
    .kol-detail p { margin: 0 0 12px; color: #64717c; }
    .metric-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin: 12px 0; }
    li { margin: 8px 0; line-height: 1.6; }
    .notice { margin-top: 22px; color: #64717c; font-size: 13px; }
    @media (max-width: 820px) { header, .summary, .requirements, .advice, .metric-grid { grid-template-columns: 1fr; display: grid; } .meta { text-align: left; } }
    @media print { body { background: #fff; } .page { padding: 0; } }
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>KOL 达人推荐结果</h1>
        <p>${escapeHtml(summary.message || "已生成推荐结果。")}</p>
      </div>
      <div class="meta">导出时间<br>${escapeHtml(new Date().toLocaleString("zh-CN"))}</div>
    </header>

    <section class="summary">
      <div><span>候选达人</span><strong>${escapeHtml(String(summary.candidateCount || 0))}</strong></div>
      <div><span>TOP10 均分</span><strong>${escapeHtml(String(summary.averageScore || 0))}</strong></div>
      <div><span>计划投入</span><strong>${currency.format(summary.plannedSpend || 0)}</strong></div>
    </section>

    <h2>投放需求</h2>
    <section class="requirements">
      ${requirementItem("产品/行业", requirements.product)}
      ${requirementItem("自然语言需求", requirements.raw_query || requirements.query)}
      ${requirementItem("目标受众", requirements.target_audience || requirements.targetAudience)}
      ${requirementItem("投放平台", (requirements.platforms || []).join("、"))}
      ${requirementItem("内容领域", (requirements.fields || []).join("、"))}
      ${requirementItem("单个预算", formatBudget(requirements))}
      ${requirementItem("总预算", currency.format(requirements.total_budget || requirements.totalBudget || 0))}
      ${requirementItem("推广目标", requirements.promotion_goal || requirements.promotionGoal)}
      ${requirementItem("风险偏好", requirements.risk_preference || requirements.riskPreference)}
      ${requirementItem("达人库", summary.dataSource || "默认达人库")}
    </section>

    <h2>TOP10 推荐列表</h2>
    <table>
      <thead>
        <tr>
          <th>排名</th><th>达人名称</th><th>平台</th><th>粉丝数</th><th>报价</th><th>综合分</th><th>ROI</th><th>风险提示</th><th>推荐理由</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>

    <h2>投放建议</h2>
    <section class="advice">
      <article><h3>预算分配</h3><p>${escapeHtml(advice.budget || "建议优先测试高匹配达人。")}</p></article>
      <article><h3>平台组合</h3><p>${escapeHtml(advice.platform || "建议围绕高分平台先做小规模验证。")}</p></article>
      <article><h3>风险复核</h3><p>${escapeHtml(advice.risk || "最终投放决策需人工复核。")}</p></article>
    </section>

    <h2>达人详情</h2>
    ${detailSections}

    <p class="notice">说明：LLM 只做需求结构化抽取，embedding 只计算语义相似度；TOP10 排名由语义、性价比、粉丝、互动、转化、风险和 ROI 等综合分生成。最终投放决策仍需人工复核。</p>
  </main>
</body>
</html>`;
}

function requirementItem(label, value) {
  return `<div><span>${escapeHtml(label)}</span>${escapeHtml(value || "未填写")}</div>`;
}

function exportMetric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function formatBudget(requirements) {
  if (requirements.budget_min != null && requirements.budget_max != null) {
    return `${currency.format(requirements.budget_min)} - ${currency.format(requirements.budget_max)}`;
  }
  const singleBudget = requirements.single_budget || requirements.singleBudget;
  return singleBudget ? `${currency.format(singleBudget)}以内` : "未填写";
}

function formatDateForFile(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`;
}

function checkedValues(container) {
  return Array.from(container.querySelectorAll("input:checked")).map((input) => input.value);
}

function nullableNumber(value) {
  return value === "" || value == null ? null : Number(value);
}

function renderSummary(summary = {}) {
  els.candidateCount.textContent = `候选 ${summary.candidateCount || 0}`;
  els.averageScore.textContent = `均分 ${summary.averageScore || 0}`;
  els.plannedSpend.textContent = `计划 ${currency.format(summary.plannedSpend || 0)}`;
  els.summaryMessage.textContent = summary.message || "已生成推荐。";
}

function renderResults() {
  if (!state.recommendations.length) {
    els.resultsBody.innerHTML = `<tr><td colspan="9" class="empty-state">没有符合条件的达人。</td></tr>`;
    return;
  }

  els.resultsBody.innerHTML = state.recommendations
    .map((item) => {
      const selected = item.kolId === state.selectedId ? "selected" : "";
      return `
        <tr class="${selected}" data-id="${escapeHtml(item.kolId)}">
          <td><span class="rank">#${item.rank}</span></td>
          <td class="name-cell"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.field)}</span></td>
          <td>${escapeHtml(item.platform)}</td>
          <td>${escapeHtml(item.followersLabel)}</td>
          <td>${escapeHtml(item.priceLabel)}</td>
          <td><span class="score">${item.score}</span></td>
          <td>${escapeHtml(item.roi)}</td>
          <td><span class="risk-badge ${riskClass(item.risk)}">${escapeHtml(item.risk)}</span></td>
          <td class="reason-cell">${escapeHtml(item.recommendation)}</td>
        </tr>
      `;
    })
    .join("");

  els.resultsBody.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedId = row.dataset.id;
      renderResults();
      renderDetail(getSelected());
    });
  });
}

function renderDetail(item) {
  if (!item) {
    els.detailContent.className = "detail-empty";
    els.detailContent.textContent = "点击推荐结果中的达人查看详情。";
    return;
  }

  els.detailContent.className = "detail-card";
  els.detailContent.innerHTML = `
    <div class="detail-title">
      <h3>${escapeHtml(item.name)}</h3>
      <p>${escapeHtml(item.platform)} · ${escapeHtml(item.field)} · ${escapeHtml(item.audience)}</p>
    </div>
    <div class="metric-grid">
      ${metric("综合分", item.score)}
      ${metric("语义相似度", `${item.semanticScore}分`)}
      ${metric("业务表现", `${item.businessScore}分`)}
      ${metric("风险分", `${item.scoreBreakdown?.risk ?? item.metrics.riskScore}分`)}
      ${metric("预估 ROI", item.roi)}
      ${metric("互动率", `${item.metrics.engagementRate}%`)}
      ${metric("转化率", `${item.metrics.conversionRate}%`)}
      ${metric("预计曝光", item.metrics.estimatedExposure.toLocaleString("zh-CN"))}
      ${metric("历史合作", `${item.metrics.cooperationCount}次`)}
    </div>
    <div class="analysis-list">
      ${analysis("为什么推荐", item.details.why)}
      ${analysis("语义相似度", `${item.details.semanticFit} 来源：${sourceLabel(item.semanticSource)}。`)}
      ${analysis("受众是否匹配", item.details.audienceFit)}
      ${analysis("业务表现", breakdownText(item))}
      ${analysis("性价比如何", item.details.costValue)}
      ${analysis("风险在哪里", item.details.risk)}
      ${analysis("适合内容形式", item.details.contentForm)}
      ${analysis("是否优先投放", item.details.priority)}
    </div>
  `;
}

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function analysis(title, text) {
  return `<div class="analysis-item"><h4>${escapeHtml(title)}</h4><p>${escapeHtml(text)}</p></div>`;
}

function sourceLabel(source) {
  return source === "embedding" ? "embedding 语义相似度" : "规则语义兜底";
}

function breakdownText(item) {
  const b = item.scoreBreakdown || {};
  return `业务表现分 ${item.businessScore}；性价比 ${b.cost ?? 0}，粉丝 ${b.followers ?? 0}，互动 ${b.engagement ?? 0}，转化 ${b.conversion ?? 0}，ROI ${b.roi ?? item.roiValue ?? 0}。`;
}

function getSelected() {
  return state.recommendations.find((item) => item.kolId === state.selectedId);
}

function riskClass(risk) {
  if (risk === "低") return "risk-low";
  if (risk === "高" || risk === "中高") return "risk-high";
  return "risk-mid";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
