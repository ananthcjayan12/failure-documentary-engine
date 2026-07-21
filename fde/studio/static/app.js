const initialProject = new URLSearchParams(location.search).get("project");

const state = {
  bootstrap: null,
  projects: [],
  activeProjectId: initialProject || localStorage.getItem("fde.activeProject") || null,
  activeProject: null,
  assets: [],
  assetSummary: {},
  timeline: {entries: [], total_seconds: 0},
  view: location.hash.replace("#", "") || "dashboard",
  selectedStageId: null,
  assetMode: "image",
  assetSearch: "",
  assetStatus: "all",
  assetCategory: "all",
  pollTimer: null,
  orchestratorTab: "routing",
  selectedRouteTask: null,
};

const icons = {
  home: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3.5 10.5 12 3l8.5 7.5v9a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M9 21v-7h6v7"/></svg>`,
  pipeline: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="7" height="6" rx="2"/><rect x="14" y="14" width="7" height="6" rx="2"/><path d="M10 7h4a3 3 0 0 1 3 3v4M14 17h-4a3 3 0 0 1-3-3v-4"/></svg>`,
  assets: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/><rect x="13" y="13" width="8" height="8" rx="2"/></svg>`,
  timeline: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h16M4 12h11M4 18h16"/><circle cx="7" cy="6" r="2" fill="currentColor" stroke="none"/><circle cx="17" cy="18" r="2" fill="currentColor" stroke="none"/></svg>`,
  runs: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5h16v14H4z"/><path d="M4 9h16M8 5v14"/></svg>`,
  brain: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9.5 4.5A3.5 3.5 0 0 0 6 8v.5A3.5 3.5 0 0 0 4.5 15 3.5 3.5 0 0 0 8 18.5h1.5V4.5Z"/><path d="M14.5 4.5A3.5 3.5 0 0 1 18 8v.5a3.5 3.5 0 0 1 1.5 6.5 3.5 3.5 0 0 1-3.5 3.5h-1.5V4.5Z"/><path d="M9.5 8H7.8M14.5 8h1.7M9.5 13H7.5M14.5 13h2M12 4v16"/></svg>`,
  settings: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/></svg>`,
  refresh: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>`,
  plus: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>`,
  file: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 2.8h8l4 4V21H6z"/><path d="M14 3v5h5"/></svg>`,
  play: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/></svg>`,
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 4 4L19 6"/></svg>`,
  upload: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M4 15v5h16v-5"/></svg>`,
  download: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4v12m0 0 5-5m-5 5-5-5"/><path d="M4 19h16"/></svg>`,
  image: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8" cy="9" r="2"/><path d="m4 17 5-5 4 4 3-3 4 4"/></svg>`,
  video: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 10 4-2v8l-4-2z"/></svg>`,
  clock: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/></svg>`,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const formatNumber = value => Number(value || 0).toLocaleString();
const formatDuration = seconds => { const s = Math.round(Number(seconds || 0)); return s >= 60 ? `${Math.floor(s/60)}m ${String(s%60).padStart(2,"0")}s` : `${s}s`; };
const formatBytes = value => { const n = Number(value || 0); if (n < 1024) return `${n} B`; if (n < 1048576) return `${(n/1024).toFixed(1)} KB`; return `${(n/1048576).toFixed(1)} MB`; };
const formatDate = value => { if (!value) return "—"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}); };

async function request(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (!(options.body instanceof FormData) && options.body != null && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers});
  let payload = null;
  const contentType = response.headers.get("content-type") || "";
  try { payload = contentType.includes("application/json") ? await response.json() : await response.text(); } catch { payload = null; }
  if (!response.ok) throw new Error(payload?.detail || payload?.error || payload || response.statusText || "Request failed");
  return payload;
}

function initializeIcons() { $$('[data-icon]').forEach(node => { node.innerHTML = icons[node.dataset.icon] || icons.file; }); }
function toast(message, error = false) { const node = document.createElement("div"); node.className = `toast${error ? " is-error" : ""}`; node.textContent = message; $("#toast-stack").append(node); setTimeout(() => node.remove(), 4500); }
function showError(error) { const message = error?.message || String(error); $("#global-alert").textContent = message; $("#global-alert").classList.remove("is-hidden"); toast(message, true); }
function clearError() { $("#global-alert").classList.add("is-hidden"); }
function setBusy(button, busy, label = "Working…") { if (!button) return; if (busy) { button.dataset.original = button.innerHTML; button.innerHTML = label; button.disabled = true; } else { button.innerHTML = button.dataset.original || button.innerHTML; button.disabled = false; } }

async function loadBootstrap({preserveProject = true} = {}) {
  clearError();
  const payload = await request("/api/bootstrap");
  state.bootstrap = payload;
  state.projects = payload.projects || [];
  if (!preserveProject || !state.activeProjectId || !state.projects.some(p => p.project_id === state.activeProjectId)) state.activeProjectId = state.projects[0]?.project_id || null;
  if (state.activeProjectId) localStorage.setItem("fde.activeProject", state.activeProjectId);
  await loadActiveProject(false);
  renderShell();
  renderCurrentView();
}

async function loadActiveProject(render = true) {
  if (!state.activeProjectId) { state.activeProject = null; state.assets = []; state.timeline = {entries:[], total_seconds:0}; if (render) renderCurrentView(); return; }
  const [project, assetPayload, timeline] = await Promise.all([
    request(`/api/projects/${encodeURIComponent(state.activeProjectId)}`),
    request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/assets`),
    request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/timeline`),
  ]);
  state.activeProject = project;
  state.assets = assetPayload.assets || [];
  state.assetSummary = assetPayload.summary || {};
  state.timeline = timeline || {entries:[], total_seconds:0};
  if (!state.selectedStageId) state.selectedStageId = project.stages.find(stage => ["active","review"].includes(stage.status))?.id || project.stages.at(-1)?.id;
  managePolling();
  if (render) { renderShell(); renderCurrentView(); }
}

function renderShell() {
  const bootstrap = state.bootstrap || {projects:[],config:{capabilities:{}}};
  $("#project-nav-count").textContent = bootstrap.projects?.length || 0;
  $("#asset-nav-count").textContent = state.activeProject?.metrics?.assets || 0;
  const select = $("#project-switcher");
  select.innerHTML = state.projects.length ? state.projects.map(item => `<option value="${escapeHtml(item.project_id)}" ${item.project_id === state.activeProjectId ? "selected" : ""}>${escapeHtml(item.title)}</option>`).join("") : `<option value="">No projects</option>`;
  const capabilities = bootstrap.config?.capabilities || {};
  $("#capability-list").innerHTML = Object.entries(capabilities).map(([name,ready]) => `<span class="capability-chip${ready ? " is-ready" : ""}">${escapeHtml(name)}</span>`).join("");
  $("#engine-status").textContent = capabilities.ffmpeg ? "Ready for local rendering" : "Planning mode · FFmpeg missing";
  $$(".nav-item[data-nav]").forEach(button => button.classList.toggle("is-active", button.dataset.nav === state.view));
  const titles = {
    dashboard:["Production control room","Overview"], production:["Resumable documentary pipeline","Production"],
    assets:["Images and video masters","Asset review"], timeline:["Narration-driven edit","Timeline"],
    runs:["All local productions","Projects"], orchestrator:["Task routing and prompt intelligence","AI Orchestrator"], settings:["Local engine configuration","Settings"],
  };
  const [eyebrow,title] = titles[state.view] || titles.dashboard;
  $("#page-eyebrow").textContent = eyebrow; $("#page-title").textContent = title;
}

function navigate(view) {
  state.view = view;
  location.hash = view;
  $$(".page-view").forEach(node => node.classList.remove("is-active"));
  $(`#view-${view}`)?.classList.add("is-active");
  renderShell();
  renderCurrentView();
}

function renderCurrentView() {
  $$(".page-view").forEach(node => node.classList.toggle("is-active", node.id === `view-${state.view}`));
  ({dashboard:renderDashboard, production:renderProduction, assets:renderAssets, timeline:renderTimeline, runs:renderRuns, orchestrator:renderOrchestrator, settings:renderSettings}[state.view] || renderDashboard)();
  initializeIcons();
}

function statCard(label, value, note, accent = false) { return `<article class="stat-card${accent ? " accent" : ""}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`; }
function statusClass(stateValue = "") { if (stateValue === "PICTURE_LOCKED" || stateValue.includes("APPROVED")) return "is-complete"; if (stateValue.includes("REVIEW")) return "is-review"; if (stateValue.includes("GENERATION") || stateValue.includes("READY")) return "is-running"; return ""; }
function statusPill(project) { return `<span class="status-pill ${statusClass(project.state)}">${escapeHtml(project.state_label || project.state)}</span>`; }
function projectThumbnail(item) { return `<span class="project-thumb">${item.preview_url ? `<img src="${escapeHtml(item.preview_url)}" alt="">` : escapeHtml(item.project_id.slice(0,4).toUpperCase())}</span>`; }

function renderDashboard() {
  const root = $("#view-dashboard");
  const totals = state.bootstrap?.totals || {};
  const current = state.activeProject;
  root.innerHTML = `
    <section class="welcome-hero">
      <div class="hero-copy"><p class="eyebrow">Failure Documentary Engine</p><h2>From a story idea to a picture-locked investigation.</h2><p>Plan, review and resume every stage from one local control room. Generate only the reusable assets you need, preserve approved work, and repair individual failures without restarting the documentary.</p><div class="button-row"><button class="primary-button" data-open-project="${escapeHtml(current?.project_id || "")}">${icons.play}${current ? "Continue active project" : "Create first project"}</button><button class="secondary-button" id="dashboard-new-project">${icons.plus}New production</button></div></div>
      <div class="hero-orbit"><span class="orbit-core"></span><span class="orbit-dot"></span></div>
    </section>
    <div class="stat-grid" style="margin-top:15px">
      ${statCard("Local projects", formatNumber(totals.projects), "Stored inside this repository")}
      ${statCard("Awaiting review", formatNumber(totals.in_review), "Human approval gates", true)}
      ${statCard("Picture locked", formatNumber(totals.picture_locked), "Ready for audio finishing")}
      ${statCard("Master assets", formatNumber(totals.assets), "Across all investigations")}
    </div>
    <div class="dashboard-grid">
      <section class="panel"><header class="panel-heading"><div><p class="eyebrow">Resume instantly</p><h2>Recent projects</h2></div><button class="secondary-button" data-nav-jump="runs">View all</button></header><div class="project-card-list">${state.projects.length ? state.projects.slice(0,6).map(projectCard).join("") : emptyInline("No projects yet", "Create a project from a story idea to start the eight-stage workflow.")}</div></section>
      <section class="panel"><header class="panel-heading"><div><p class="eyebrow">Operator focus</p><h2>What needs attention</h2></div></header><div class="activity-list">${attentionItems().join("") || emptyInline("Nothing blocked", "Your projects have no immediate review gate.")}</div></section>
    </div>`;
}

function projectCard(item) {
  return `<button class="project-card" data-open-project="${escapeHtml(item.project_id)}">${projectThumbnail(item)}<span class="project-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.topic)}</small><span class="project-meta">${statusPill(item)}</span></span><span class="project-progress"><b>${item.progress}%</b><span class="progress-track"><i style="width:${item.progress}%"></i></span></span></button>`;
}
function attentionItems() {
  return state.projects.filter(item => item.next_action || item.state.includes("REVIEW")).slice(0,6).map(item => `<button class="activity-row ghost-button" data-open-project="${escapeHtml(item.project_id)}" style="width:100%;text-align:left"><span class="activity-icon">${icons.clock}</span><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.next_action?.label || item.state_label)}</small></span></button>`);
}
function emptyInline(title, message) { return `<div class="empty-state"><div><span class="empty-state-icon">${icons.file}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(message)}</p></div></div>`; }

function renderProduction() {
  const root = $("#view-production");
  const project = state.activeProject;
  if (!project) { root.innerHTML = emptyInline("No active project", "Create or select a project to open the production workspace."); return; }
  const selected = project.stages.find(stage => stage.id === state.selectedStageId) || project.stages[0];
  const action = project.next_action;
  const job = project.job || {status:"idle"};
  root.innerHTML = `
    <section class="project-hero"><div><p class="eyebrow">${escapeHtml(project.project_id)} · ${escapeHtml(project.state_label)}</p><h2>${escapeHtml(project.title)}</h2><p>${escapeHtml(project.topic)}</p><div class="button-row" style="margin-top:16px">${statusPill(project)}<span class="status-pill">${formatDuration(project.duration_seconds)}</span><span class="status-pill">max ${project.max_assets} assets</span></div></div><div class="hero-progress-card"><strong>${project.progress}%</strong><span>Production completion</span><div class="progress-track"><i style="width:${project.progress}%"></i></div></div></section>
    <div class="stat-grid" style="margin-top:15px">
      ${statCard("Chapters", formatNumber(project.metrics.chapters), "Story sections")}
      ${statCard("Narration", formatNumber(project.metrics.script_words), "Estimated words")}
      ${statCard("Shot divisions", formatNumber(project.metrics.shots), "Narration visual beats")}
      ${statCard("Master assets", `${formatNumber(project.metrics.assets)}/${project.max_assets}`, "Reusable generated footage", true)}
    </div>
    <div class="production-layout">
      <div class="production-main">
        <section class="panel"><header class="panel-heading"><div><p class="eyebrow">Eight-stage workflow</p><h2>Production pipeline</h2></div><button class="secondary-button" data-refresh-project>${icons.refresh}Refresh state</button></header><div class="stage-grid">${project.stages.map(stageCard).join("")}</div></section>
        <section class="panel"><div class="stage-detail">${stageDetail(selected)}</div></section>
        ${manualRequestMarkup(project)}
        ${imageFactoryMarkup(project)}
        ${videoFactoryMarkup(project)}
      </div>
      <aside class="production-aside">
        ${nextActionMarkup(action, job)}
        ${jobPanelMarkup(job)}
        ${contactSheetMarkup(project)}
      </aside>
    </div>`;
  if (job.status === "running") refreshLogs();
}

function stageCard(stage) { return `<button class="stage-card is-${stage.status}" data-stage-id="${escapeHtml(stage.id)}"><span class="stage-number">${String(stage.number).padStart(2,"0")}</span><span class="stage-status"></span><h3>${escapeHtml(stage.short_title)}</h3><p>${escapeHtml(stage.description)}</p></button>`; }
function stageDetail(stage) {
  if (!stage) return "";
  return `<div class="stage-detail-head"><div><p class="eyebrow">Stage ${stage.number} · ${stage.status}</p><h3>${escapeHtml(stage.title)}</h3><p>${escapeHtml(stage.description)}</p></div>${stage.action ? actionButtonMarkup(stage.action) : ""}</div><div class="artifact-list">${stage.artifacts?.length ? stage.artifacts.map(artifactCard).join("") : `<div style="color:var(--faint);font-size:9px;margin-top:12px">Artifacts will appear here after this stage runs.</div>`}</div>`;
}
function artifactCard(item) { return `<article class="artifact-card"><span class="artifact-kind">${item.kind === "image" ? icons.image : icons.file}</span><span><strong>${escapeHtml(item.name)}</strong><small>${formatBytes(item.size)}</small></span><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">OPEN ↗</a></article>`; }
function nextActionMarkup(action, job) {
  if (!action) return `<section class="next-action-card"><p class="eyebrow">Production complete</p><h3>Picture-locked base ready</h3><p>The documentary base is complete and can move to cinematic music and sound design.</p></section>`;
  const disabled = job.status === "running";
  return `<section class="next-action-card"><p class="eyebrow">Recommended next</p><h3>${escapeHtml(action.label)}</h3><p>${actionHelp(action.id)}</p>${actionButtonMarkup(action, disabled, true)}</section>`;
}
function actionButtonMarkup(action, disabled = false, full = false) {
  const attr = action.kind === "navigate" ? `data-navigate-action="${escapeHtml(action.id)}"` : `data-action="${escapeHtml(action.id)}"`;
  return `<button class="primary-button" ${attr} ${disabled ? "disabled" : ""} ${full ? 'style="width:100%"' : ""}>${icons.play}${escapeHtml(action.label)}</button>`;
}
function actionHelp(id) { return ({
  research:"Create the evidence dossier and claim ledger before shaping the story.",
  structure:"Turn verified evidence into a suspenseful chapter architecture.",
  approve_structure:"Review the chapter order and approve it before script generation.",
  script:"Generate the complete narration from the approved structure.",
  approve_script:"Lock the narration before generating visual divisions.",
  shots:"Break narration into visual beats with clear purpose and motion.",
  optimize_assets:"Compress all shot needs into no more than the configured master assets.",
  generate_image_prompts:"Create continuity-aware prompts and a resumable media manifest.",
  generate_images:"Generate every pending master still using the configured image provider, retries and fallback route.",
  export_image_factory:"Export a manual production packet for ChatGPT or another subscription UI.",
  validate_assets:"Approve the imported images, then lock the asset manifest.",
  video_jobs:"Create one controlled image-to-video job for each approved image.",
  generate_videos:"Generate pending animation masters with the configured video provider and approved image references.",
  upload_videos:"Upload externally generated clips together and review only exceptions.",
  review_images:"Approve continuity-safe images and flag only the assets that require regeneration.",
  review_videos:"Approve usable animation masters and flag only failed clips.",
  import_narration:"Upload the narration master and optional timing JSON.",
  validate_videos:"Approve the usable clips and preserve only exceptions for regeneration.",
  create_variants:"Create local crops, slow versions and background plates from each clip.",
  build_timeline:"Map all narration beats to approved footage variants.",
  render_final:"Render the picture-locked base using the configured deterministic renderer."
}[id] || "Continue the next pipeline stage."); }

function jobPanelMarkup(job) { const cls = job.status === "running" ? "is-running" : job.status === "completed" ? "is-completed" : job.status === "failed" ? "is-failed" : ""; return `<section class="panel job-panel"><div class="job-summary"><div class="job-status-copy"><strong>${escapeHtml(job.label || "Process log")}</strong><small>${job.started_at ? `Started ${formatDate(job.started_at)}` : "No active local process"}</small></div><span class="status-indicator ${cls}"><i></i>${escapeHtml(job.status || "idle")}</span></div><pre class="log-console" id="live-log">${escapeHtml(job.status === "idle" ? "Stage output and errors will appear here." : "Loading log…")}</pre>${job.status === "running" ? `<div style="padding:10px;border-top:1px solid var(--line)"><button class="danger-button" data-stop-job style="width:100%">Stop process</button></div>` : ""}</section>`; }
function manualRequestMarkup(project) {
  const pending = (project.manual_requests || []).filter(item => !item.response_exists);
  if (!pending.length || project.job?.status === "running") return "";
  const requestItem = pending.at(-1);
  if (!project.state.endsWith("READY") && !["PROJECT_CREATED","RESEARCH_READY","STRUCTURE_APPROVED","SCRIPT_APPROVED"].includes(project.state)) return "";
  return `<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Manual agent bridge</p><h2>${escapeHtml(requestItem.stage)} response required</h2><p>Open the generated prompt in ChatGPT or another LLM, then paste the strict JSON response here. The Studio resumes from this exact stage.</p></div><a class="secondary-button" href="${escapeHtml(requestItem.prompt_url)}" target="_blank">Open prompt ↗</a></header><div class="settings-form"><label class="full-span"><span>Structured JSON response</span><textarea id="manual-response-json" rows="12" placeholder='{"project_id":"..."}'></textarea></label><div class="full-span button-row"><button class="primary-button" data-submit-manual="${escapeHtml(requestItem.stage)}">Save and resume stage</button></div></div></section>`;
}
function projectTaskRoute(project, taskId) { return project?.task_routes?.[taskId] || {}; }
function generationSummary(report) {
  if (!report) return {generated:0, skipped:0, failed:0, manual:0};
  return {
    generated:(report.generated || []).length,
    skipped:(report.skipped || []).length,
    failed:(report.failed || []).length,
    manual:(report.manual_required || []).length
  };
}
function routeIdentity(route) {
  return `<div class="native-route-identity"><span class="provider-capability">${escapeHtml(route.capability || "media")}</span><div><strong>${escapeHtml(route.provider_label || route.provider || "Not configured")}</strong><small>${escapeHtml(route.model || "Default model")}</small></div></div>`;
}
function generationStats(report) {
  const summary=generationSummary(report);
  return `<div class="generation-stat-grid"><article><strong>${summary.generated}</strong><span>Generated</span></article><article><strong>${summary.skipped}</strong><span>Resumed</span></article><article class="${summary.failed ? "has-error" : ""}"><strong>${summary.failed}</strong><span>Failed</span></article><article class="${summary.manual ? "has-warning" : ""}"><strong>${summary.manual}</strong><span>Manual fallback</span></article></div>`;
}
function imageFactoryMarkup(project) {
  if (!["IMAGE_GENERATION","IMAGE_REVIEW"].includes(project.state)) return "";
  const route=projectTaskRoute(project,"image_generator");
  const manual=route.provider_mode === "manual";
  if (!manual) return `<section class="panel media-factory-panel"><header class="panel-heading"><div><p class="eyebrow">Native media factory</p><h2>Automated master-image generation</h2><p>The selected provider runs each pending asset independently, preserves completed versions, and resumes after interruption.</p></div>${routeIdentity(route)}</header><div class="native-factory-grid"><div class="native-factory-copy"><span class="native-factory-orbit">${icons.image}</span><h3>No browser handoff required</h3><p>Prompts, exact filenames, continuity references, retries and fallback behavior are read directly from the project manifest.</p><div class="factory-feature-list"><span>${icons.check}Asset-level resumability</span><span>${icons.check}Approved images are immutable</span><span>${icons.check}Raw provider output is retained</span><span>${icons.check}Selective regeneration only</span></div><div class="button-row"><button class="primary-button" data-action="generate_images">${icons.play}Generate pending images</button><button class="secondary-button" data-action="export_image_factory">Manual packet fallback</button></div></div><div class="native-factory-report"><p class="eyebrow">Latest generation run</p>${generationStats(project.image_generation_report)}<small>${project.image_generation_report ? "The generation ledger is persisted inside 08_generated_images." : "No automated image run has started yet."}</small></div></div><details class="manual-fallback-details"><summary>Import images created by another tool</summary><label class="upload-zone compact-upload"><strong>Import image ZIP</strong><small>Asset IDs such as A01 and A02 are mapped automatically.</small><span class="secondary-button">${icons.upload}Choose ZIP</span><input id="image-batch-input" type="file" accept=".zip"></label></details></section>`;
  return `<section class="panel media-factory-panel"><header class="panel-heading"><div><p class="eyebrow">Manual subscription bridge</p><h2>Documentary Image Factory</h2><p>The current image route uses a subscription UI. Export once and return one validated ZIP.</p></div>${routeIdentity(route)}</header><div class="factory-card"><div class="factory-steps"><div class="factory-step"><span>1</span><div><strong>Upload the production packet</strong><small>The manifest carries all prompts, continuity rules, filenames and QC requirements.</small></div></div><div class="factory-step"><span>2</span><div><strong>Run the selected image UI</strong><small>Generate continuity anchors first, then complete each visual family.</small></div></div><div class="factory-step"><span>3</span><div><strong>Return one ZIP</strong><small>The Studio normalizes and maps every file using the A01–A28 IDs.</small></div></div></div><div class="factory-actions">${project.image_factory_packet_ready && project.image_factory_zip_url ? `<a class="secondary-button" href="${escapeHtml(project.image_factory_zip_url)}">${icons.download}Download packet</a>` : `<button class="primary-button" data-action="export_image_factory">Export packet</button>`}<label class="upload-zone compact-upload"><strong>Import generated ZIP</strong><small>Move directly into image review.</small><span class="secondary-button">${icons.upload}Choose ZIP</span><input id="image-batch-input" type="file" accept=".zip"></label></div></div></section>`;
}
function videoFactoryMarkup(project) {
  if (!["VIDEO_GENERATION","VIDEO_REVIEW"].includes(project.state)) return "";
  const route=projectTaskRoute(project,"video_generator");
  const manual=route.provider_mode === "manual";
  return `<section class="panel media-factory-panel"><header class="panel-heading"><div><p class="eyebrow">${manual ? "Manual video handoff" : "Native video factory"}</p><h2>${manual ? "Import animation masters" : "Automated image-to-video generation"}</h2><p>${manual ? "Generate the prepared jobs in the selected subscription UI, then upload the clips." : "Every approved still is passed as an exact reference to the selected video provider."}</p></div>${routeIdentity(route)}</header>${manual ? `<div class="factory-card"><p class="factory-plain-copy">Open the generated animation briefs, preserve aircraft and scene identity, then upload all clips from the Assets page.</p><button class="primary-button" data-navigate-action="upload_videos">Open video assets</button></div>` : `<div class="native-factory-grid"><div class="native-factory-copy"><span class="native-factory-orbit">${icons.video}</span><h3>Reference-safe animation</h3><p>The generator uses the approved image as the source, records every provider attempt, and keeps successful clips across retries.</p><div class="button-row"><button class="primary-button" data-action="generate_videos">${icons.play}Generate pending videos</button><button class="secondary-button" data-navigate-action="upload_videos">Upload external clips</button></div></div><div class="native-factory-report"><p class="eyebrow">Latest generation run</p>${generationStats(project.video_generation_report)}<small>${project.video_generation_report ? "The generation ledger is persisted inside 10_generated_videos." : "No automated video run has started yet."}</small></div></div>`}</section>`;
}

function contactSheetMarkup(project) { return `<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Visual overview</p><h3>Contact sheet</h3></div>${project.contact_sheet_url ? `<a href="${escapeHtml(project.contact_sheet_url)}" target="_blank" class="ghost-button">OPEN ↗</a>` : ""}</header>${project.contact_sheet_url ? `<img class="contact-sheet-preview" src="${escapeHtml(project.contact_sheet_url)}" alt="Contact sheet">` : emptyInline("Not generated yet", "The contact sheet appears after master assets and images are available.")}</section>`; }

function renderAssets() {
  const root = $("#view-assets");
  if (!state.activeProject) { root.innerHTML = emptyInline("No active project", "Select a project to review its images and videos."); return; }
  const filtered = filteredAssets();
  const targetField = state.assetMode === "image" ? "image_review" : "video_review";
  const available = state.assets.filter(item => state.assetMode === "image" ? item.approved_image : item.approved_video).length;
  const approved = state.assets.filter(item => item[targetField]?.status === "approved").length;
  root.innerHTML = `
    <div class="stat-grid">
      ${statCard("Planned assets", formatNumber(state.assets.length), `Maximum ${state.activeProject.max_assets}`)}
      ${statCard(state.assetMode === "image" ? "Images imported" : "Videos imported", formatNumber(available), "Available for review")}
      ${statCard("Approved", formatNumber(approved), `Approved ${state.assetMode}s`, true)}
      ${statCard("Exceptions", formatNumber(state.assets.filter(item => ["change_requested","rejected"].includes(item[targetField]?.status)).length), "Need regeneration")}
    </div>
    <div class="assets-toolbar" style="margin-top:15px"><div class="toolbar-group"><div class="segmented"><button data-asset-mode="image" class="${state.assetMode === "image" ? "is-active" : ""}">Images</button><button data-asset-mode="video" class="${state.assetMode === "video" ? "is-active" : ""}">Videos</button></div><input class="compact-input" id="asset-search" value="${escapeHtml(state.assetSearch)}" placeholder="Search asset ID or title"><select class="compact-select" id="asset-status-filter"><option value="all">All statuses</option>${["pending","approved","change_requested","rejected"].map(value => `<option value="${value}" ${state.assetStatus===value?"selected":""}>${value.replaceAll("_"," ")}</option>`).join("")}</select><select class="compact-select" id="asset-category-filter"><option value="all">All categories</option>${["hero","atmosphere","investigation","story_specific"].map(value => `<option value="${value}" ${state.assetCategory===value?"selected":""}>${value.replaceAll("_"," ")}</option>`).join("")}</select></div><div class="toolbar-group"><label class="secondary-button">${icons.upload}Upload ${state.assetMode}s<input id="asset-upload-input" type="file" ${state.assetMode === "image" ? "accept='image/*'" : "accept='video/*'"} multiple hidden></label><button class="secondary-button" data-bulk-approve>${icons.check}Approve available</button></div></div>
    ${filtered.length ? `<div class="asset-grid">${filtered.map(assetCard).join("")}</div>` : emptyInline("No matching assets", "Change the filters or upload the generated files for this project.")}`;
}
function filteredAssets() { const search = state.assetSearch.toLowerCase(); return state.assets.filter(item => { const review = state.assetMode === "image" ? item.image_review : item.video_review; return (!search || `${item.asset_id} ${item.title}`.toLowerCase().includes(search)) && (state.assetStatus === "all" || review?.status === state.assetStatus) && (state.assetCategory === "all" || item.category === state.assetCategory); }); }
function assetCard(item) { const review = state.assetMode === "image" ? item.image_review : item.video_review; const media = state.assetMode === "image" ? (item.image_url ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}">` : `<div class="asset-media-placeholder">IMAGE PENDING</div>`) : (item.video_url ? `<video src="${escapeHtml(item.video_url)}" muted preload="metadata"></video>` : `<div class="asset-media-placeholder">VIDEO PENDING</div>`); return `<article class="asset-card"><div class="asset-media">${media}<span class="asset-id-badge">${escapeHtml(item.asset_id)}</span><span class="review-badge ${escapeHtml(review?.status || "pending")}">${escapeHtml((review?.status || "pending").replaceAll("_"," "))}</span></div><div class="asset-card-body"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.primary_use)}</p><div class="asset-card-meta"><span>${escapeHtml(item.category.replaceAll("_"," "))}</span><span>${item.required_reuse_count} uses · ${item.linked_shots.length} shots</span></div><div class="asset-card-actions"><button class="secondary-button" data-open-asset="${escapeHtml(item.asset_id)}">Details</button><button class="primary-button" data-quick-approve="${escapeHtml(item.asset_id)}" ${state.assetMode === "image" ? (!item.approved_image ? "disabled" : "") : (!item.approved_video ? "disabled" : "")}>Approve</button></div></div></article>`; }

function openAssetDrawer(assetId) {
  const item = state.assets.find(asset => asset.asset_id === assetId); if (!item) return;
  const review = state.assetMode === "image" ? item.image_review : item.video_review;
  const media = state.assetMode === "image" ? (item.image_url ? `<img class="drawer-media" src="${escapeHtml(item.image_url)}" alt="">` : "") : (item.video_url ? `<video class="drawer-media" src="${escapeHtml(item.video_url)}" controls></video>` : "");
  $("#drawer-kicker").textContent = `${item.asset_id} · ${item.category.replaceAll("_"," ")}`;
  $("#drawer-title").textContent = item.title;
  $("#drawer-body").innerHTML = `${media}<section class="drawer-section"><h3>Production role</h3><p>${escapeHtml(item.primary_use)}\n\nLinked shots: ${escapeHtml(item.linked_shots.join(", "))}\nReuse target: ${item.required_reuse_count}</p></section><section class="drawer-section"><h3>${state.assetMode === "image" ? "Image prompt" : "Animation prompt"}</h3><p>${escapeHtml(state.assetMode === "image" ? item.image_prompt : item.video_prompt)}</p></section><section class="drawer-section"><h3>Review decision</h3><textarea id="asset-review-instruction" placeholder="Describe only what must change. Unmentioned properties will be preserved.">${escapeHtml(review?.instruction || "")}</textarea><div class="button-row"><button class="primary-button" data-drawer-review="approved" data-asset-id="${escapeHtml(item.asset_id)}">Approve</button><button class="secondary-button" data-drawer-review="change_requested" data-asset-id="${escapeHtml(item.asset_id)}">Request change</button><button class="danger-button" data-drawer-review="rejected" data-asset-id="${escapeHtml(item.asset_id)}">Reject</button></div></section>`;
  $("#asset-drawer").classList.remove("is-hidden"); $("#asset-drawer").setAttribute("aria-hidden","false");
}
function closeAssetDrawer() { $("#asset-drawer").classList.add("is-hidden"); $("#asset-drawer").setAttribute("aria-hidden","true"); }

function renderTimeline() {
  const root = $("#view-timeline");
  const project = state.activeProject;
  if (!project) { root.innerHTML = emptyInline("No active project", "Select a project to open its timeline."); return; }
  const entries = state.timeline.entries || [];
  root.innerHTML = `<div class="stat-grid">${statCard("Timeline entries", formatNumber(entries.length), "Narration visual beats")}${statCard("Runtime", formatDuration(state.timeline.total_seconds), "Current assembled duration", true)}${statCard("Videos approved", `${project.metrics.videos_approved}/${project.metrics.assets}`, "Master clips")}${statCard("Narration", project.state === "NARRATION_READY" || project.progress > 85 ? "Ready" : "Pending", "Master voice track")}</div><div class="timeline-layout" style="margin-top:15px"><section class="panel"><header class="panel-heading"><div><p class="eyebrow">Picture edit</p><h2>Documentary timeline</h2></div>${entries.length ? `<button class="secondary-button" data-action="render_preview">Render preview</button>` : ""}</header>${project.preview_video_url ? `<video class="preview-player" src="${escapeHtml(project.preview_video_url)}" controls></video>` : ""}<div class="timeline-list">${entries.length ? entries.map((entry,index) => timelineRow(entry,index)).join("") : emptyInline("Timeline not built", "Approve videos, create variants, upload narration, and build the timeline.")}</div></section><aside class="panel"><header class="panel-heading"><div><p class="eyebrow">Narration source</p><h3>Import voice track</h3></div></header><form class="narration-form" id="narration-upload-form"><label class="file-field"><span>Audio file</span><input name="audio" type="file" accept="audio/*" required></label><label class="file-field"><span>Optional timestamps JSON</span><input name="timestamps" type="file" accept="application/json,.json"></label><button class="primary-button" type="submit">${icons.upload}Import narration</button>${project.state === "NARRATION_READY" ? `<button class="secondary-button" type="button" data-action="build_timeline">Build timeline</button>` : ""}</form></aside></div>`;
}
function timelineRow(entry,index) { return `<article class="timeline-row"><span class="timeline-index">${String(index+1).padStart(3,"0")}</span><span class="timeline-time">${Number(entry.start).toFixed(1)}–${Number(entry.end).toFixed(1)}s</span><span class="timeline-copy"><strong>${escapeHtml(entry.shot_id)}</strong><small>${escapeHtml((entry.narration_ids || []).join(", "))} · ${escapeHtml(entry.variant || "master")}</small></span><span class="timeline-asset">${escapeHtml(entry.master_asset)}</span></article>`; }

function renderRuns() {
  const root = $("#view-runs");
  root.innerHTML = `<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Local production registry</p><h2>All projects</h2><p>Every project is resumable from its last persisted state.</p></div><button class="primary-button" id="runs-new-project">${icons.plus}New project</button></header><div class="runs-table"><div class="runs-row header"><span>Project</span><span>Status</span><span>Progress</span><span>Assets</span><span></span></div>${state.projects.map(runRow).join("") || emptyInline("No projects", "Create your first documentary production.")}</div></section>`;
}
function runRow(item) { return `<article class="runs-row"><span class="run-name"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.project_id)} · updated ${formatDate(item.updated_at)}</small></span><span class="run-cell">${statusPill(item)}</span><span class="run-cell"><span class="progress-track"><i style="width:${item.progress}%"></i></span><small style="display:block;margin-top:5px;color:var(--faint)">${item.progress}%</small></span><span class="run-cell">${item.metrics.assets}/${item.max_assets}</span><span class="run-actions"><button class="secondary-button" data-open-project="${escapeHtml(item.project_id)}">Open</button></span></article>`; }


function orchestratorData() { return state.bootstrap?.orchestrator || {tasks:[],profiles:[],provider_catalog:[],prompt_packs:{},rules:[]}; }
function providerById(id) { return orchestratorData().provider_catalog?.find(item => item.id === id) || null; }
function taskById(id) { return orchestratorData().tasks?.find(item => item.id === id) || null; }
function healthBadge(health = {}) { const ready = health.healthy; return `<span class="health-badge ${ready ? "is-ready" : health.status === "disabled" ? "is-disabled" : "is-missing"}"><i></i>${escapeHtml(ready ? "Ready" : health.status || "Unknown")}</span>`; }
function renderOrchestrator() {
  const root = $("#view-orchestrator");
  const data = orchestratorData();
  const tasks = data.tasks || [];
  const healthy = (data.provider_catalog || []).filter(item => item.health?.healthy).length;
  const manual = tasks.filter(item => item.provider_mode === "manual").length;
  const fallback = tasks.filter(item => item.fallback_provider).length;
  const activePack = data.prompt_packs?.[data.active_prompt_pack] || {};
  root.innerHTML = `
    <section class="orchestrator-hero">
      <div><p class="eyebrow">Provider-agnostic production brain</p><h2>One pipeline. A different specialist for every task.</h2><p>Profiles establish a complete routing strategy. Every task can then override its provider, model, reasoning, retry, fallback and prompt-pack behavior without changing pipeline code.</p></div>
      <div class="orchestrator-active"><span>Active configuration</span><strong>${escapeHtml(profileLabel(data.active_profile))}</strong><small>${escapeHtml(activePack.label || data.active_prompt_pack || "No prompt pack")}</small></div>
    </section>
    <div class="stat-grid" style="margin-top:15px">
      ${statCard("Routed tasks", formatNumber(tasks.length), "Persisted workspace mapping", true)}
      ${statCard("Healthy providers", `${healthy}/${(data.provider_catalog || []).length}`, "Local and manual adapters")}
      ${statCard("Manual handoffs", formatNumber(manual), "Subscription UI workflows")}
      ${statCard("Fallback coverage", `${fallback}/${tasks.length}`, "Automatic recovery routes")}
    </div>
    <nav class="orchestrator-tabs" aria-label="Orchestrator sections">
      ${[["routing","Task routing"],["profiles","Profiles"],["prompts","Prompt packs"],["providers","Providers"]].map(([id,label]) => `<button class="${state.orchestratorTab===id ? "is-active" : ""}" data-orchestrator-tab="${id}">${label}</button>`).join("")}
    </nav>
    <div class="orchestrator-content">${state.orchestratorTab === "profiles" ? profilesMarkup(data) : state.orchestratorTab === "prompts" ? promptPacksMarkup(data) : state.orchestratorTab === "providers" ? providersMarkup(data) : routingMarkup(data)}</div>`;
}
function profileLabel(id) { return orchestratorData().profiles?.find(item => item.id === id)?.label || (id === "custom" ? "Custom mapping" : id || "Custom mapping"); }
function routingMarkup(data) {
  const groups = [...new Set((data.tasks || []).map(item => item.group))];
  return `<div class="orchestrator-layout"><div class="orchestrator-main">
    <section class="panel route-overview-panel"><header class="panel-heading"><div><p class="eyebrow">Current workspace map</p><h2>Task-to-model routing</h2><p>Click any agent card to change its model or recovery behavior.</p></div><button class="secondary-button" data-orchestrator-tab-jump="profiles">Switch profile</button></header>
    <div class="route-groups">${groups.map(group => `<section class="route-group"><header><span>${escapeHtml(group)}</span><small>${(data.tasks || []).filter(item => item.group===group).length} tasks</small></header><div class="route-card-grid">${(data.tasks || []).filter(item => item.group===group).map(routeCard).join("")}</div></section>`).join("")}</div></section>
    <section class="panel pipeline-map-panel"><header class="panel-heading"><div><p class="eyebrow">Execution visibility</p><h2>Pipeline model map</h2><p>See exactly where every output is produced and where manual subscription handoffs occur.</p></div></header>${pipelineMapMarkup(data.tasks || [])}</section>
  </div><aside class="orchestrator-aside">
    <section class="panel compact-panel"><header class="panel-heading"><div><p class="eyebrow">Prompt intelligence</p><h3>${escapeHtml(data.prompt_packs?.[data.active_prompt_pack]?.label || "Prompt pack")}</h3></div></header><div class="compact-panel-body"><p>${escapeHtml(data.prompt_packs?.[data.active_prompt_pack]?.description || "")}</p><button class="secondary-button full-button" data-orchestrator-tab-jump="prompts">Manage prompt packs</button></div></section>
    <section class="panel compact-panel"><header class="panel-heading"><div><p class="eyebrow">Conditional routing</p><h3>Active rules</h3></div><span class="count-chip">${(data.rules || []).filter(item=>item.enabled).length}</span></header><div class="rule-list">${(data.rules || []).map(ruleMarkup).join("") || `<p class="orchestrator-empty-copy">No routing rules configured.</p>`}</div></section>
  </aside></div>`;
}
function routeCard(item) {
  const provider = providerById(item.provider) || {};
  return `<button class="route-card" data-edit-route="${escapeHtml(item.id)}"><span class="route-stage">STEP ${item.stage}</span><span class="route-health">${healthBadge(item.health)}</span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.description)}</small><div class="route-capability-row"><span class="provider-capability">${escapeHtml(item.capability || "structured")}</span><span>${escapeHtml(item.provider_mode || "adapter")}</span></div><div class="route-model"><b>${escapeHtml(provider.label || item.provider)}</b><span>${escapeHtml(item.model)}</span></div><footer><span>${escapeHtml(item.reasoning_effort)} mode</span><span>→ ${escapeHtml(providerById(item.fallback_provider)?.label || item.fallback_provider || "No fallback")}</span></footer></button>`;
}
function pipelineMapMarkup(tasks) {
  const visible = tasks.filter(item => ["research","structure","script","shot_planner","asset_optimizer","image_prompt_writer","image_generator","animation_prompt_writer","video_generator","timeline_builder","composition_renderer","final_qc"].includes(item.id));
  return `<div class="pipeline-map-scroll"><div class="pipeline-map">${visible.map((item,index) => `<div class="pipeline-node ${item.provider_mode === "manual" ? "is-manual" : ""}"><span>${String(index+1).padStart(2,"0")}</span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.provider_label)}</small><b>${escapeHtml(item.model)}</b><em>${escapeHtml(item.capability || "structured")}</em></div>${index < visible.length-1 ? `<i class="pipeline-arrow">→</i>` : ""}`).join("")}</div></div>`;
}
function ruleMarkup(rule) { return `<article class="rule-row"><span class="rule-toggle ${rule.enabled ? "is-on" : ""}"></span><div><strong>${escapeHtml(rule.label || rule.id)}</strong><small>IF ${escapeHtml(rule.field)} ${escapeHtml(rule.operator)} ${escapeHtml(rule.value)} · ${escapeHtml(rule.task_id)} → ${escapeHtml(rule.model)}</small></div></article>`; }
function profilesMarkup(data) {
  return `<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Reusable routing strategies</p><h2>Production profiles</h2><p>Applying a profile replaces the complete task map. You can then customize individual tasks.</p></div><span class="status-pill is-complete">Active · ${escapeHtml(profileLabel(data.active_profile))}</span></header><div class="profile-grid">${(data.profiles || []).map(profile => `<article class="profile-card ${profile.id===data.active_profile ? "is-active" : ""}"><div class="profile-icon">${icons.brain}</div><span class="profile-state">${profile.id===data.active_profile ? "CURRENT" : "AVAILABLE"}</span><h3>${escapeHtml(profile.label)}</h3><p>${escapeHtml(profile.description)}</p><div class="profile-meta"><span>${profile.task_count} tasks</span><span>${profile.id === "offline" ? "No paid calls" : "Fallback enabled"}</span></div><button class="${profile.id===data.active_profile ? "secondary-button" : "primary-button"} full-button" data-apply-profile="${escapeHtml(profile.id)}" ${profile.id===data.active_profile ? "disabled" : ""}>${profile.id===data.active_profile ? "Profile active" : "Apply profile"}</button></article>`).join("")}</div></section>`;
}
function promptPacksMarkup(data) {
  const packs = Object.values(data.prompt_packs || {});
  const active = data.prompt_packs?.[data.active_prompt_pack] || packs[0] || {};
  return `<div class="prompt-pack-layout"><section class="panel"><header class="panel-heading"><div><p class="eyebrow">Domain intelligence</p><h2>Prompt packs</h2><p>A pack adds permanent domain rules to every routed agent prompt.</p></div></header><div class="prompt-pack-grid">${packs.map(pack => `<button class="prompt-pack-card ${pack.id===data.active_prompt_pack ? "is-active" : ""}" data-activate-pack="${escapeHtml(pack.id)}"><span>${pack.id===data.active_prompt_pack ? "ACTIVE" : "PROMPT PACK"}</span><strong>${escapeHtml(pack.label)}</strong><small>${escapeHtml(pack.description)}</small></button>`).join("")}</div></section><section class="panel prompt-editor-panel"><header class="panel-heading"><div><p class="eyebrow">Active instructions</p><h3>${escapeHtml(active.label || "Prompt pack")}</h3></div></header><form id="prompt-pack-form" class="prompt-editor"><input type="hidden" name="pack_id" value="${escapeHtml(active.id || "")}"><label><span>Pack description</span><input name="description" value="${escapeHtml(active.description || "")}"></label><label><span>Universal instructions</span><textarea name="instructions" rows="15">${escapeHtml(active.instructions || "")}</textarea></label><button class="primary-button" type="submit">Save prompt pack</button><p>These instructions are prepended to real command-agent prompts when a stage runs.</p></form></section></div>`;
}
function providerModeNote(provider) {
  if (provider.mode === "manual") return "Files and prompts are exported for a subscription UI handoff.";
  if (provider.mode === "mock") return "Runs entirely on the local machine without external calls.";
  if (provider.mode === "native_cli") return "Native adapter handles structured JSON and Grok Imagine media without shell-template parsing.";
  if (provider.mode === "local") return "Deterministic local runtime controlled by the pipeline.";
  if (provider.mode === "disabled") return "Adapter reserved for future configuration.";
  return "Command adapter executes the configured template with bounded inputs and outputs.";
}
function providersMarkup(data) {
  return `<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Reasoning, media and rendering adapters</p><h2>Provider connections</h2><p>Tasks can select any provider that advertises the required capability. Connection tests are dry readiness checks.</p></div><button class="primary-button" type="submit" form="providers-form">Save provider configuration</button></header><form id="providers-form" class="provider-grid">${(data.provider_catalog || []).map(provider => `<article class="provider-card"><header><div class="provider-logo">${provider.capabilities?.includes("image") || provider.capabilities?.includes("video") ? icons.image : provider.capabilities?.includes("render") ? icons.video : icons.brain}</div>${healthBadge(provider.health)}</header><h3>${escapeHtml(provider.label)}</h3><p>${escapeHtml(provider.description)}</p><div class="provider-detail"><span>Adapter</span><strong>${escapeHtml(provider.mode)}</strong></div><div class="provider-capabilities">${(provider.capabilities || []).map(capability => `<span class="provider-capability">${escapeHtml(capability)}</span>`).join("")}</div><div class="provider-models">${(provider.models || []).slice(0,4).map(model => `<span>${escapeHtml(model)}</span>`).join("")}</div>${provider.mode === "command" ? `<label><span>Structured command template</span><textarea name="provider_${escapeHtml(provider.id)}" rows="4" placeholder="Use {model}, {prompt} and {output}">${escapeHtml(data.providers?.[provider.id]?.command_template || provider.command_template || "")}</textarea></label>${provider.id === "custom_cli" ? `<label><span>Media command template</span><textarea name="provider_media_${escapeHtml(provider.id)}" rows="4" placeholder="Use {model}, {prompt}, {output}, {reference}, {media_type}">${escapeHtml(data.providers?.[provider.id]?.media_command_template || provider.media_command_template || "")}</textarea></label>` : ""}` : `<div class="manual-provider-note">${escapeHtml(providerModeNote(provider))}</div>`}<button class="secondary-button full-button" type="button" data-test-provider="${escapeHtml(provider.id)}">Run connection test</button></article>`).join("")}</form></section>`;
}

function openRouteModal(taskId) {
  const item = taskById(taskId); if (!item) return;
  state.selectedRouteTask = taskId;
  const allProviders = orchestratorData().provider_catalog || [];
  const providers = allProviders.filter(provider => provider.mode !== "disabled" && (provider.capabilities || []).includes(item.capability));
  const models = [...new Set(providers.flatMap(provider => provider.models || []))];
  $("#route-modal-kicker").textContent = `Stage ${item.stage} · ${item.group} · ${item.capability}`;
  $("#route-modal-title").textContent = item.label;
  $("#route-form").innerHTML = `<input type="hidden" name="task_id" value="${escapeHtml(item.id)}"><div class="route-form-copy"><p>${escapeHtml(item.description)}</p><span>Only providers supporting <b>${escapeHtml(item.capability)}</b> are shown. Changes apply to the next execution; existing artifacts keep their original route.</span></div><div class="route-form-grid"><label><span>Primary provider</span><select name="provider">${providers.map(provider=>`<option value="${escapeHtml(provider.id)}" ${provider.id===item.provider ? "selected" : ""}>${escapeHtml(provider.label)} · ${escapeHtml(provider.mode)}</option>`).join("")}</select></label><label><span>Model</span><input name="model" value="${escapeHtml(item.model)}" list="route-model-list"></label><datalist id="route-model-list">${models.map(model=>`<option value="${escapeHtml(model)}"></option>`).join("")}</datalist><label><span>Execution / reasoning mode</span><select name="reasoning_effort">${["low","medium","high","standard"].map(value=>`<option value="${value}" ${value===item.reasoning_effort ? "selected" : ""}>${value}</option>`).join("")}</select></label><label><span>Temperature</span><input name="temperature" type="number" min="0" max="1.5" step="0.05" value="${Number(item.temperature ?? .2)}"></label><label><span>Timeout</span><input name="timeout_seconds" type="number" min="0" max="14400" value="${Number(item.timeout_seconds || 0)}"></label><label><span>Retry count</span><input name="retry_count" type="number" min="0" max="5" value="${Number(item.retry_count || 0)}"></label><label><span>Fallback provider</span><select name="fallback_provider">${providers.map(provider=>`<option value="${escapeHtml(provider.id)}" ${provider.id===item.fallback_provider ? "selected" : ""}>${escapeHtml(provider.label)}</option>`).join("")}</select></label><label><span>Fallback model</span><input name="fallback_model" value="${escapeHtml(item.fallback_model || "")}" list="route-model-list"></label></div><div class="capability-callout"><span class="provider-capability">${escapeHtml(item.capability)}</span><p>${item.capability === "image" ? "Image providers receive one asset prompt and must return a still file." : item.capability === "video" ? "Video providers receive an approved reference image and motion brief." : item.capability === "render" ? "Render providers consume the deterministic timeline and local media only." : item.capability === "audio" ? "Audio providers create or import the narration master." : "Structured providers must return contract-valid JSON."}</p></div><footer class="modal-footer"><label class="route-enabled"><input name="enabled" type="checkbox" ${item.enabled!==false ? "checked" : ""}><span>Task enabled</span></label><div class="button-row"><button type="button" class="secondary-button route-modal-close">Cancel</button><button type="submit" class="primary-button">Save task route</button></div></footer>`;
  $("#route-modal").classList.remove("is-hidden"); $("#route-modal").setAttribute("aria-hidden","false");
}

function closeRouteModal() { $("#route-modal").classList.add("is-hidden"); $("#route-modal").setAttribute("aria-hidden","true"); state.selectedRouteTask=null; }
async function reloadOrchestrator() { const value = await request("/api/orchestrator"); state.bootstrap.orchestrator = value; renderOrchestrator(); initializeIcons(); }

function renderSettings() {
  const root = $("#view-settings"); const config = state.bootstrap?.config || {}; const capabilities = config.capabilities || {};
  root.innerHTML = `<div class="settings-grid"><section class="panel"><header class="panel-heading"><div><p class="eyebrow">Agent and project defaults</p><h2>Studio configuration</h2><p>Settings are stored locally in the workspace. API keys are never displayed in the browser.</p></div></header><form class="settings-form" id="settings-form"><label><span>Default agent mode</span><select name="agent_mode"><option value="manual" ${config.agent_mode==="manual"?"selected":""}>Manual response bridge</option><option value="command" ${config.agent_mode==="command"?"selected":""}>Codex / command agent</option><option value="mock" ${config.agent_mode==="mock"?"selected":""}>Offline mock</option></select></label><label><span>Auto refresh</span><select name="auto_refresh_seconds">${[1,2,3,5,10].map(v => `<option value="${v}" ${Number(config.auto_refresh_seconds)===v?"selected":""}>${v} seconds</option>`).join("")}</select></label><label class="full-span"><span>Command template</span><textarea name="command_template" rows="4">${escapeHtml(config.command_template || "")}</textarea></label><label><span>Default duration</span><select name="default_duration">${[300,480,600,720].map(v => `<option value="${v}" ${Number(config.default_duration)===v?"selected":""}>${v/60} minutes</option>`).join("")}</select></label><label><span>Default max assets</span><input name="default_max_assets" type="number" min="8" max="60" value="${Number(config.default_max_assets || 28)}"></label><div class="full-span button-row"><button class="primary-button" type="submit">Save settings</button></div></form></section><aside class="panel"><header class="panel-heading"><div><p class="eyebrow">System readiness</p><h3>Local capabilities</h3></div></header><div class="tool-check-list">${Object.entries(capabilities).map(([name,ready]) => `<article class="tool-check"><div><strong>${escapeHtml(name)}</strong><small>${toolDescription(name)}</small></div><b class="${ready ? "is-ready" : ""}">${ready ? "READY" : "MISSING"}</b></article>`).join("")}</div></aside></div>`;
}
function toolDescription(name) { return ({
  ffmpeg:"Media normalization, variants, muxing and fallback rendering",
  ffprobe:"Video metadata and technical validation",
  codex:"ChatGPT-authenticated structured reasoning agent",
  grok:"Grok Build reasoning plus native Imagine image and video generation",
  npx:"Pinned local HyperFrames runtime launcher",
  hyperframes:"Frame-accurate HTML/CSS/GSAP composition renderer"
}[name] || "Local dependency"); }

async function executeAction(action, button = null) {
  if (!state.activeProjectId) return;
  setBusy(button,true);
  try {
    const result = await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/actions/${encodeURIComponent(action)}`, {method:"POST",body:JSON.stringify({})});
    toast(result.status === "running" ? `${action.replaceAll("_"," ")} started` : `${action.replaceAll("_"," ")} completed`);
    await loadActiveProject();
  } catch (error) { showError(error); } finally { setBusy(button,false); }
}
async function reviewAsset(assetId,status,instruction="") { try { await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/assets/${encodeURIComponent(assetId)}/review`,{method:"POST",body:JSON.stringify({status,instruction,target:state.assetMode,preserve:[]})}); toast(`${assetId} ${status.replaceAll("_"," ")}`); closeAssetDrawer(); await loadActiveProject(); } catch(error) { showError(error); } }
async function refreshLogs() { if (!state.activeProjectId || state.view !== "production") return; try { const payload = await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/logs?lines=220`); const node = $("#live-log"); if (node) { node.textContent = payload.log || "Waiting for output…"; node.scrollTop = node.scrollHeight; } if (payload.job.status !== state.activeProject?.job?.status) await loadActiveProject(); } catch {} }
function managePolling() { clearInterval(state.pollTimer); if (state.activeProject?.job?.status === "running") { const seconds = Number(state.bootstrap?.config?.auto_refresh_seconds || 2); state.pollTimer = setInterval(async () => { await refreshLogs(); }, seconds * 1000); } }

function openNewProjectModal() { $("#new-project-modal").classList.remove("is-hidden"); $("#new-project-modal").setAttribute("aria-hidden","false"); }
function closeNewProjectModal() { $("#new-project-modal").classList.add("is-hidden"); $("#new-project-modal").setAttribute("aria-hidden","true"); }

async function handleImageBatch(file,input) { if (!file || !state.activeProjectId) return; const form = new FormData(); form.append("file",file); input.disabled = true; try { const result = await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/upload/image-batch`,{method:"POST",body:form}); toast(`Imported ${result.validation?.imported?.length || result.imported?.length || 0} images`); await loadActiveProject(); navigate("assets"); } catch(error) { showError(error); } finally { input.disabled=false; input.value=""; } }
async function handleAssetUploads(files,input) { if (!files.length || !state.activeProjectId) return; const form = new FormData(); [...files].forEach(file => form.append("files",file)); input.disabled=true; try { const endpoint = state.assetMode === "image" ? "images" : "videos"; const result = await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/upload/${endpoint}`,{method:"POST",body:form}); toast(`Imported ${result.imported?.length || 0} ${state.assetMode}s`); await loadActiveProject(); } catch(error) { showError(error); } finally { input.disabled=false; input.value=""; } }

function bindEvents() {
  document.addEventListener("click", async event => {
    const nav = event.target.closest("[data-nav]"); if (nav) { event.preventDefault(); navigate(nav.dataset.nav); return; }
    const jump = event.target.closest("[data-nav-jump]"); if (jump) { navigate(jump.dataset.navJump); return; }
    const orchestratorTab = event.target.closest("[data-orchestrator-tab]"); if (orchestratorTab) { state.orchestratorTab=orchestratorTab.dataset.orchestratorTab; renderOrchestrator(); initializeIcons(); return; }
    const orchestratorJump = event.target.closest("[data-orchestrator-tab-jump]"); if (orchestratorJump) { state.orchestratorTab=orchestratorJump.dataset.orchestratorTabJump; renderOrchestrator(); initializeIcons(); return; }
    const editRoute = event.target.closest("[data-edit-route]"); if (editRoute) { openRouteModal(editRoute.dataset.editRoute); return; }
    if (event.target.closest(".route-modal-close") || event.target.id === "route-modal") { closeRouteModal(); return; }
    const applyProfileButton = event.target.closest("[data-apply-profile]"); if (applyProfileButton) { setBusy(applyProfileButton,true); try { state.bootstrap.orchestrator=await request(`/api/orchestrator/profiles/${encodeURIComponent(applyProfileButton.dataset.applyProfile)}/apply`,{method:"POST"}); toast(`${profileLabel(applyProfileButton.dataset.applyProfile)} profile applied`); renderOrchestrator(); initializeIcons(); } catch(error) { showError(error); } finally { setBusy(applyProfileButton,false); } return; }
    const activatePack = event.target.closest("[data-activate-pack]"); if (activatePack) { try { state.bootstrap.orchestrator=await request("/api/orchestrator",{method:"PATCH",body:JSON.stringify({active_prompt_pack:activatePack.dataset.activatePack})}); toast("Prompt pack activated"); renderOrchestrator(); initializeIcons(); } catch(error) { showError(error); } return; }
    const testProvider = event.target.closest("[data-test-provider]"); if (testProvider) { setBusy(testProvider,true,"Testing…"); try { const result=await request(`/api/orchestrator/providers/${encodeURIComponent(testProvider.dataset.testProvider)}/test`,{method:"POST"}); toast(`${providerById(testProvider.dataset.testProvider)?.label || testProvider.dataset.testProvider}: ${result.detail}`); await reloadOrchestrator(); } catch(error) { showError(error); } finally { setBusy(testProvider,false); } return; }
    if (event.target.closest("#new-project-button,#dashboard-new-project,#runs-new-project")) { openNewProjectModal(); return; }
    if (event.target.closest(".modal-close")) { closeNewProjectModal(); return; }
    if (event.target.closest(".drawer-close") || event.target.id === "asset-drawer") { closeAssetDrawer(); return; }
    const openProject = event.target.closest("[data-open-project]"); if (openProject) { const id = openProject.dataset.openProject; if (!id) { openNewProjectModal(); return; } state.activeProjectId=id; localStorage.setItem("fde.activeProject",id); await loadActiveProject(); navigate("production"); return; }
    const stage = event.target.closest("[data-stage-id]"); if (stage) { state.selectedStageId=stage.dataset.stageId; renderProduction(); initializeIcons(); return; }
    const navigateAction = event.target.closest("[data-navigate-action]"); if (navigateAction) { const id=navigateAction.dataset.navigateAction; if (id === "review_images") { state.assetMode="image"; navigate("assets"); } else if (["review_videos","upload_videos"].includes(id)) { state.assetMode="video"; navigate("assets"); } else if (id === "import_narration") { navigate("timeline"); } return; }
    const action = event.target.closest("[data-action]"); if (action) { await executeAction(action.dataset.action,action); return; }
    if (event.target.closest("[data-refresh-project]")) { await loadActiveProject(); return; }
    if (event.target.closest("[data-stop-job]")) { try { await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/stop`,{method:"POST"}); toast("Stop requested"); await loadActiveProject(); } catch(error) { showError(error); } return; }
    const mode = event.target.closest("[data-asset-mode]"); if (mode) { state.assetMode=mode.dataset.assetMode; renderAssets(); initializeIcons(); return; }
    const openAsset = event.target.closest("[data-open-asset]"); if (openAsset) { openAssetDrawer(openAsset.dataset.openAsset); return; }
    const quick = event.target.closest("[data-quick-approve]"); if (quick) { await reviewAsset(quick.dataset.quickApprove,"approved"); return; }
    const drawerReview = event.target.closest("[data-drawer-review]"); if (drawerReview) { await reviewAsset(drawerReview.dataset.assetId,drawerReview.dataset.drawerReview,$("#asset-review-instruction")?.value || ""); return; }
    if (event.target.closest("[data-bulk-approve]")) { try { const assetIds=state.assets.filter(item => state.assetMode === "image" ? item.approved_image : item.approved_video).map(item=>item.asset_id); await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/assets/bulk-review`,{method:"POST",body:JSON.stringify({target:state.assetMode,status:"approved",asset_ids:assetIds})}); toast(`Approved ${assetIds.length} assets`); await loadActiveProject(); } catch(error) { showError(error); } return; }
    const manual = event.target.closest("[data-submit-manual]"); if (manual) { const raw=$("#manual-response-json")?.value || ""; try { JSON.parse(raw); setBusy(manual,true); await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/manual-response/${manual.dataset.submitManual}`,{method:"POST",body:JSON.stringify({response:raw,consume:true})}); toast("Response saved; stage resumed"); await loadActiveProject(); } catch(error) { showError(error); } finally { setBusy(manual,false); } return; }
  });

  document.addEventListener("change", async event => {
    if (event.target.id === "project-switcher") { state.activeProjectId=event.target.value || null; if (state.activeProjectId) localStorage.setItem("fde.activeProject",state.activeProjectId); await loadActiveProject(); return; }
    if (event.target.id === "image-batch-input") { await handleImageBatch(event.target.files[0],event.target); return; }
    if (event.target.id === "asset-upload-input") { await handleAssetUploads(event.target.files,event.target); return; }
    if (event.target.id === "asset-status-filter") { state.assetStatus=event.target.value; renderAssets(); initializeIcons(); return; }
    if (event.target.id === "asset-category-filter") { state.assetCategory=event.target.value; renderAssets(); initializeIcons(); return; }
  });
  document.addEventListener("input", event => { if (event.target.id === "asset-search") { state.assetSearch=event.target.value; renderAssets(); initializeIcons(); const input=$("#asset-search"); input?.focus(); input?.setSelectionRange(input.value.length,input.value.length); } });
  $("#refresh-button").addEventListener("click", async event => { setBusy(event.currentTarget,true); try { await loadBootstrap(); toast("Studio refreshed"); } catch(error) { showError(error); } finally { setBusy(event.currentTarget,false); } });
  $("#new-project-form").addEventListener("submit", async event => { event.preventDefault(); const button=event.submitter; setBusy(button,true); const values=Object.fromEntries(new FormData(event.currentTarget).entries()); values.target_duration_seconds=Number(values.target_duration_seconds); values.maximum_master_assets=Number(values.maximum_master_assets); values.master_video_duration_seconds=Number(values.master_video_duration_seconds); try { const project=await request("/api/projects",{method:"POST",body:JSON.stringify(values)}); state.activeProjectId=project.project_id; localStorage.setItem("fde.activeProject",project.project_id); closeNewProjectModal(); event.currentTarget.reset(); await loadBootstrap(); navigate("production"); toast("Project created"); } catch(error) { showError(error); } finally { setBusy(button,false); } });
  document.addEventListener("submit", async event => {
    if (event.target.id === "settings-form") { event.preventDefault(); const button=event.submitter; setBusy(button,true); const data=Object.fromEntries(new FormData(event.target).entries()); data.default_duration=Number(data.default_duration); data.default_max_assets=Number(data.default_max_assets); data.auto_refresh_seconds=Number(data.auto_refresh_seconds); try { await request("/api/config",{method:"PATCH",body:JSON.stringify(data)}); await loadBootstrap(); toast("Settings saved"); } catch(error) { showError(error); } finally { setBusy(button,false); } }
    if (event.target.id === "route-form") { event.preventDefault(); const button=event.submitter; setBusy(button,true); const form=new FormData(event.target); const taskId=String(form.get("task_id")); const payload={provider:form.get("provider"),model:form.get("model"),reasoning_effort:form.get("reasoning_effort"),temperature:Number(form.get("temperature")),timeout_seconds:Number(form.get("timeout_seconds")),retry_count:Number(form.get("retry_count")),fallback_provider:form.get("fallback_provider"),fallback_model:form.get("fallback_model"),enabled:form.get("enabled")==="on"}; try { state.bootstrap.orchestrator=await request("/api/orchestrator",{method:"PATCH",body:JSON.stringify({tasks:{[taskId]:payload}})}); closeRouteModal(); renderOrchestrator(); initializeIcons(); toast(`${taskById(taskId)?.label || taskId} route saved`); } catch(error) { showError(error); } finally { setBusy(button,false); } }
    if (event.target.id === "prompt-pack-form") { event.preventDefault(); const button=event.submitter; setBusy(button,true); const form=new FormData(event.target); const packId=String(form.get("pack_id")); try { state.bootstrap.orchestrator=await request("/api/orchestrator",{method:"PATCH",body:JSON.stringify({prompt_packs:{[packId]:{description:form.get("description"),instructions:form.get("instructions")}}})}); renderOrchestrator(); initializeIcons(); toast("Prompt pack saved"); } catch(error) { showError(error); } finally { setBusy(button,false); } }
    if (event.target.id === "providers-form") { event.preventDefault(); const button=event.submitter; setBusy(button,true); const form=new FormData(event.target); const providers={}; (orchestratorData().provider_catalog || []).forEach(item=>{ const command=form.get(`provider_${item.id}`); const mediaCommand=form.get(`provider_media_${item.id}`); if (command !== null || mediaCommand !== null) providers[item.id]={command_template:command || "",media_command_template:mediaCommand || "",enabled:true}; }); try { state.bootstrap.orchestrator=await request("/api/orchestrator",{method:"PATCH",body:JSON.stringify({providers})}); renderOrchestrator(); initializeIcons(); toast("Provider configuration saved"); } catch(error) { showError(error); } finally { setBusy(button,false); } }
    if (event.target.id === "narration-upload-form") { event.preventDefault(); const button=event.submitter; setBusy(button,true); try { const form=new FormData(event.target); await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/upload/narration`,{method:"POST",body:form}); toast("Narration imported"); await loadActiveProject(); } catch(error) { showError(error); } finally { setBusy(button,false); } }
  });
  window.addEventListener("hashchange", () => { const view=location.hash.replace("#","") || "dashboard"; if (["dashboard","production","assets","timeline","runs","orchestrator","settings"].includes(view)) navigate(view); });
}

async function start() {
  initializeIcons(); bindEvents();
  try { await loadBootstrap(); navigate(state.view); } catch(error) { showError(error); $("#view-dashboard").innerHTML=emptyInline("Studio could not load", error.message); }
}

start();
