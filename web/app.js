"use strict";

const DEFAULT_PROFILE = {
  authMode: "trusted_headers",
  tenantId: "hospital-a",
  actorId: "zureealLV",
  apiKey: "",
};

const state = {
  profile: loadProfile(),
  knowledgeBases: [],
  documents: [],
  activeKbId: null,
  activity: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function loadProfile() {
  try {
    return {
      ...DEFAULT_PROFILE,
      ...JSON.parse(localStorage.getItem("medops-profile") || "{}"),
      apiKey: sessionStorage.getItem("medops-api-key") || "",
    };
  } catch {
    return { ...DEFAULT_PROFILE };
  }
}

function headers(extra = {}) {
  const value = { ...extra };
  if (state.profile.authMode === "api_key") {
    if (state.profile.apiKey) value.Authorization = `Bearer ${state.profile.apiKey}`;
  } else {
    value["X-Tenant-ID"] = state.profile.tenantId;
    value["X-Actor-ID"] = state.profile.actorId;
  }
  return value;
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: headers(options.headers || {}) });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload?.error?.message || payload?.detail || payload?.message || detail;
    } catch { /* response was not JSON */ }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message, kind = "") {
  const item = document.createElement("div");
  item.className = `toast ${kind}`.trim();
  item.textContent = message;
  $("#toast-region").append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function logActivity(action, outcome = "OK") {
  state.activity.unshift({ action, outcome, time: new Date().toLocaleTimeString("zh-CN", { hour12: false }) });
  state.activity = state.activity.slice(0, 8);
  renderActivity();
}

function renderActivity() {
  const root = $("#activity-log");
  if (!root) return;
  root.innerHTML = state.activity.length
    ? state.activity.map((entry) => `<div class="activity-row"><b>${escapeHtml(entry.action)}</b><span>${escapeHtml(entry.outcome)} · ${escapeHtml(entry.time)}</span></div>`).join("")
    : '<div class="activity-row"><b>尚无操作</b><span>WAITING</span></div>';
}

function navigate(view) {
  const titles = { overview: "系统总览", answer: "证据问答", documents: "知识文档", operations: "运行状态" };
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach((item) => item.classList.toggle("active", item.id === `view-${view}`));
  $("#page-title").textContent = titles[view] || titles.overview;
  history.replaceState(null, "", `#${view}`);
  if (view === "operations") loadMetrics();
}

function setHealth(status, label) {
  const pill = $("#health-pill");
  pill.classList.remove("online", "offline");
  if (status) pill.classList.add(status);
  $("b", pill).textContent = label;
}

async function loadHealth() {
  try {
    const health = await api("/health");
    setHealth("online", "服务正常");
    $("#stat-version").textContent = health.version;
    logActivity("服务连接", `V${health.version}`);
  } catch (error) {
    setHealth("offline", "连接失败");
    logActivity("服务连接", "FAILED");
    throw error;
  }
}

function kbOption(kb) {
  return `<option value="${Number(kb.id)}">${escapeHtml(kb.name)}</option>`;
}

async function loadKnowledgeBases() {
  const kbs = await api("/knowledge-bases");
  state.knowledgeBases = Array.isArray(kbs) ? kbs : [];
  if (!state.knowledgeBases.some((kb) => kb.id === state.activeKbId)) {
    const preferred = state.knowledgeBases.find((kb) => /华佗中文医学/.test(kb.name))
      ?? state.knowledgeBases.find((kb) => /MedlinePlus/.test(kb.name))
      ?? state.knowledgeBases.find((kb) => /器械/.test(kb.name))
      ?? state.knowledgeBases.find((kb) => /医疗|医学/.test(kb.name));
    state.activeKbId = preferred?.id ?? state.knowledgeBases[0]?.id ?? null;
  }
  $("#stat-kbs").textContent = String(state.knowledgeBases.length);
  $("#kb-count").textContent = String(state.knowledgeBases.length);
  $("#answer-kb").innerHTML = state.knowledgeBases.length
    ? state.knowledgeBases.map(kbOption).join("")
    : '<option value="">请先创建知识库</option>';
  if (state.activeKbId) $("#answer-kb").value = String(state.activeKbId);
  renderKbOverview();
  renderKbList();
  await loadDocuments();
}

function renderKbOverview() {
  const root = $("#kb-overview");
  root.classList.remove("skeleton-box");
  root.innerHTML = state.knowledgeBases.length
    ? state.knowledgeBases.slice(0, 4).map((kb) => `<div class="list-item"><span><b>${escapeHtml(kb.name)}</b><small>${escapeHtml(kb.description || "未填写说明")}</small></span><i>KB-${String(kb.id).padStart(2, "0")}</i></div>`).join("")
    : '<div class="list-item"><span><b>还没有知识库</b><small>前往知识文档创建第一个空间</small></span><i>EMPTY</i></div>';
}

function renderKbList() {
  const root = $("#kb-list");
  root.innerHTML = state.knowledgeBases.length
    ? state.knowledgeBases.map((kb) => `<button class="kb-card ${kb.id === state.activeKbId ? "active" : ""}" data-kb-id="${Number(kb.id)}"><b>${escapeHtml(kb.name)}</b><span>${escapeHtml(kb.description || `Tenant: ${kb.tenant_id}`)}</span></button>`).join("")
    : '<p class="hint">暂无知识库，请点击右上角创建。</p>';
  $$("[data-kb-id]", root).forEach((button) => button.addEventListener("click", async () => {
    state.activeKbId = Number(button.dataset.kbId);
    $("#answer-kb").value = String(state.activeKbId);
    renderKbList();
    await safeRun(loadDocuments, "读取文档失败");
  }));
}

async function loadDocuments() {
  const active = state.knowledgeBases.find((kb) => kb.id === state.activeKbId);
  $("#active-kb-name").textContent = active?.name || "请选择知识库";
  $("#active-kb-label").textContent = active ? `KB-${String(active.id).padStart(2, "0")} / ${active.tenant_id}` : "SELECTED SPACE";
  if (!active) {
    state.documents = [];
    renderDocuments();
    return;
  }
  state.documents = await api(`/knowledge-bases/${active.id}/documents`);
  renderDocuments();
}

function renderDocuments() {
  $("#stat-docs").textContent = String(state.documents.length);
  const body = $("#documents-body");
  body.innerHTML = state.documents.length
    ? state.documents.map((doc) => `<tr><td>${escapeHtml(doc.title)}<br><small>${escapeHtml(doc.mime_type)}</small></td><td>${escapeHtml(doc.source)}</td><td>${Number(doc.chunk_count)} chunks<br><small>${Number(doc.artifact_count)} artifacts</small></td><td>${escapeHtml(doc.ingest_status)} · ${escapeHtml(doc.parser)}</td></tr>`).join("")
    : '<tr class="empty-row"><td colspan="4">这个知识库还是空的，把医学或医疗器械资料拖进来吧。</td></tr>';
}

async function askQuestion() {
  const question = $("#question").value.trim();
  const kbId = Number($("#answer-kb").value);
  if (question.length < 2) return toast("问题至少需要 2 个字符。", "error");
  if (!kbId) return toast("先创建并选择一个知识库。", "error");
  const button = $("#ask-button");
  const result = $("#answer-result");
  button.disabled = true;
  $(".button-label", button).textContent = "正在检索证据…";
  result.classList.add("loading");
  result.innerHTML = '<div class="empty-state"><div class="empty-glyph">⌬</div><h3>检索与校验中</h3><p>正在执行租户过滤、证据排序和回答门禁。</p></div>';
  try {
    const answer = await api("/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        knowledge_base_id: kbId,
        top_k: 5,
        text_strategy: $("#text-strategy").value,
        retrieval_profile: $("#retrieval-profile").value,
        orchestration: $("#orchestration").value,
      }),
    });
    renderAnswer(answer);
    logActivity("证据问答", answer.abstained ? "ABSTAINED" : "CITED");
  } catch (error) {
    result.innerHTML = `<div class="empty-state"><div class="empty-glyph">×</div><h3>回答失败</h3><p>${escapeHtml(error.message)}</p></div>`;
    toast(`回答失败：${error.message}`, "error");
    logActivity("证据问答", "FAILED");
  } finally {
    result.classList.remove("loading");
    button.disabled = false;
    $(".button-label", button).textContent = "生成带引用回答";
  }
}

function renderAnswer(answer) {
  const chunks = answer.retrieved_chunks || [];
  const textEvidence = (answer.citations || []).map((citation, index) => {
    const item = chunks.find((chunk) => chunk.document_id === citation.document_id && chunk.chunk_id === citation.chunk_id);
    const excerpt = item?.matched_text || item?.text || "该来源已用于回答，暂无可展示摘要。";
    return `<article class="citation"><header><span>[来源${index + 1}] ${escapeHtml(citation.source)}</span><span>文本证据</span></header><p>${escapeHtml(excerpt)}</p></article>`;
  }).join("");
  const visualEvidence = (answer.visual_citations || []).map((item, index) => `<article class="citation"><header><span>[图像${index + 1}] ${escapeHtml(item.source)}</span><span>${item.page_number ? `第 ${escapeHtml(item.page_number)} 页` : "原始图像"}</span></header><div class="visual-slot" data-visual-url="${escapeHtml(item.content_url)}"><p>正在载入原始视觉证据…</p></div></article>`).join("");
  const agentTrace = (answer.agent_steps || []).map((step) => {
    const detail = step.detail ? ` (${escapeHtml(step.detail)})` : "";
    return `${escapeHtml(step.node)} ${Number(step.duration_ms || 0).toFixed(2)}ms${detail}`;
  }).join(" → ");
  const tokenTrace = Number(answer.token_usage || 0) > 0
    ? `Token ${Number(answer.token_usage || 0).toLocaleString()} · 输入 ${Number(answer.prompt_tokens || 0).toLocaleString()} · 输出 ${Number(answer.completion_tokens || 0).toLocaleString()} · 缓存 ${Number(answer.cached_prompt_tokens || 0).toLocaleString()}`
    : "Token 0（策略直接处理）";
  $("#answer-result").innerHTML = `
    <div class="result-status"><span class="badge ${answer.abstained ? "abstained" : ""}">${answer.abstained ? "证据不足，已拒答" : "已依据来源回答"}</span><span class="timing">${escapeHtml(answer.orchestration || "classic")} / ${escapeHtml(answer.provider)} · ${Number(answer.retrieval_ms + answer.model_ms).toFixed(1)} ms</span></div>
    <div class="answer-copy">${escapeHtml(answer.answer)}</div>
    ${answer.reason ? `<div class="reason">门禁说明：${escapeHtml(answer.reason)}</div>` : ""}
    ${agentTrace ? `<div class="reason">Agent 路径：${agentTrace}</div>` : ""}
    <div class="reason">模型遥测：${tokenTrace}</div>
    <div class="citation-grid">${textEvidence}${visualEvidence || (!textEvidence ? '<div class="citation"><p>没有可展示的证据片段。</p></div>' : "")}</div>`;
  hydrateVisualEvidence();
}

async function hydrateVisualEvidence() {
  for (const slot of $$(".visual-slot")) {
    try {
      const rawPath = slot.dataset.visualUrl;
      const url = new URL(rawPath, window.location.origin);
      if (url.origin !== window.location.origin) throw new Error("跨域证据已阻止");
      const response = await fetch(url, { headers: headers() });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const objectUrl = URL.createObjectURL(await response.blob());
      const image = document.createElement("img");
      image.className = "visual-citation";
      image.alt = "检索到的原始视觉证据";
      image.src = objectUrl;
      image.addEventListener("load", () => URL.revokeObjectURL(objectUrl), { once: true });
      slot.replaceChildren(image);
    } catch (error) {
      slot.textContent = `视觉证据载入失败：${error.message}`;
    }
  }
}

async function uploadFiles(files) {
  if (!state.activeKbId) return toast("先选择一个知识库。", "error");
  const accepted = [...files];
  if (!accepted.length) return;
  $("#drop-zone").classList.add("loading");
  let uploaded = 0;
  try {
    for (const file of accepted) {
      const form = new FormData();
      form.append("file", file);
      await api(`/knowledge-bases/${state.activeKbId}/documents/upload`, { method: "POST", body: form });
      uploaded += 1;
    }
    await loadDocuments();
    toast(`已处理 ${uploaded} 个文件。`, "success");
    logActivity("同步文档摄取", `${uploaded} FILES`);
  } catch (error) {
    toast(`上传在第 ${uploaded + 1} 个文件失败：${error.message}`, "error");
    logActivity("同步文档摄取", "FAILED");
  } finally {
    $("#drop-zone").classList.remove("loading");
    $("#file-input").value = "";
  }
}

async function createKnowledgeBase(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") return $("#kb-dialog").close();
  const name = $("#new-kb-name").value.trim();
  if (!name) return;
  try {
    const created = await api("/knowledge-bases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: $("#new-kb-description").value.trim() || null }),
    });
    state.activeKbId = created.id;
    $("#kb-dialog").close();
    $("#kb-form").reset();
    await loadKnowledgeBases();
    toast(`知识库“${created.name}”已创建。`, "success");
    logActivity("创建知识库", `KB-${created.id}`);
  } catch (error) {
    toast(`创建失败：${error.message}`, "error");
  }
}

function queueSummary(name, data = {}) {
  const states = data.states || {};
  const description = Object.keys(states).length
    ? Object.entries(states).map(([key, value]) => `${key}:${value}`).join(" · ")
    : "没有任务";
  return `<div class="queue-row"><b>${escapeHtml(name)}</b><span>${escapeHtml(description)}<br>oldest ${Number(data.oldest_queued_age_seconds || 0).toFixed(1)}s</span></div>`;
}

async function loadMetrics() {
  try {
    const metrics = await api("/system/metrics");
    const requests = metrics.requests || {};
    $("#stat-requests").textContent = String(requests.count ?? 0);
    $("#stat-errors").textContent = `${requests.error_count ?? 0} errors / 24h`;
    $("#metric-requests").textContent = String(requests.count ?? 0);
    $("#metric-p95").textContent = `${Number(requests.latency_ms?.p95 || 0).toFixed(1)}`;
    $("#metric-abstained").textContent = String(requests.abstained_count ?? 0);
    $("#metric-fallback").textContent = String(requests.fallback_count ?? 0);
    $("#queue-state").innerHTML = queueSummary("摄取队列", metrics.queues?.ingestion) + queueSummary("摘要队列", metrics.queues?.summary);
  } catch (error) {
    $("#queue-state").innerHTML = `<div class="queue-row"><b>指标不可用</b><span>${escapeHtml(error.message)}</span></div>`;
    toast(`指标读取失败：${error.message}`, "error");
  }
}

function openSettings() {
  $("#auth-mode").value = state.profile.authMode;
  $("#tenant-id").value = state.profile.tenantId;
  $("#actor-id").value = state.profile.actorId;
  $("#api-key").value = state.profile.apiKey;
  toggleAuthFields();
  $("#settings-dialog").showModal();
}

function toggleAuthFields() {
  const keyMode = $("#auth-mode").value === "api_key";
  $("#trusted-fields").classList.toggle("hidden", keyMode);
  $("#api-key-field").classList.toggle("hidden", !keyMode);
}

async function saveSettings(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") return $("#settings-dialog").close();
  state.profile = {
    authMode: $("#auth-mode").value,
    tenantId: $("#tenant-id").value.trim() || DEFAULT_PROFILE.tenantId,
    actorId: $("#actor-id").value.trim() || DEFAULT_PROFILE.actorId,
    apiKey: $("#api-key").value.trim(),
  };
  const { apiKey, ...persistentProfile } = state.profile;
  localStorage.setItem("medops-profile", JSON.stringify(persistentProfile));
  if (apiKey) sessionStorage.setItem("medops-api-key", apiKey);
  else sessionStorage.removeItem("medops-api-key");
  $("#settings-dialog").close();
  await connect();
}

async function safeRun(task, failure) {
  try { return await task(); }
  catch (error) { toast(`${failure}：${error.message}`, "error"); return null; }
}

async function connect() {
  setHealth("", "正在连接");
  try {
    await loadHealth();
    await loadKnowledgeBases();
    await loadMetrics();
  } catch (error) {
    setHealth("offline", "连接失败");
    toast(`连接失败：${error.message}。可在右上角检查认证设置。`, "error");
  }
}

function bind() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
  $$('[data-go]').forEach((button) => button.addEventListener("click", () => navigate(button.dataset.go)));
  $("#ask-button").addEventListener("click", askQuestion);
  $("#question").addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); askQuestion(); }
  });
  $("#answer-kb").addEventListener("change", (event) => {
    state.activeKbId = Number(event.target.value) || null;
    renderKbList();
    safeRun(loadDocuments, "读取文档失败");
  });
  $("#file-input").addEventListener("change", (event) => uploadFiles(event.target.files));
  const drop = $("#drop-zone");
  ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove("dragging"); }));
  drop.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));
  $("#new-kb-button").addEventListener("click", () => $("#kb-dialog").showModal());
  $("#kb-form").addEventListener("submit", createKnowledgeBase);
  $("#settings-button").addEventListener("click", openSettings);
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#auth-mode").addEventListener("change", toggleAuthFields);
  $("#refresh-metrics").addEventListener("click", () => safeRun(loadMetrics, "刷新失败"));
}

document.addEventListener("DOMContentLoaded", () => {
  bind();
  renderActivity();
  const initial = location.hash.slice(1);
  navigate(["overview", "answer", "documents", "operations"].includes(initial) ? initial : "overview");
  connect();
});
