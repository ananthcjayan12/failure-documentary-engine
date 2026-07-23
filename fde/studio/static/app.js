const initialProject = new URLSearchParams(location.search).get("project");

const state = {
  bootstrap: null,
  projects: [],
  activeProjectId: initialProject || localStorage.getItem("fde.activeProject") || null,
  activeProject: null,
  assets: [],
  assetSummary: {},
  timeline: {entries: [], total_seconds: 0},
  jobLog: "",
  view: location.hash.replace("#", "") || "dashboard",
  selectedStageId: null,
  assetMode: "image",
  pollTimer: null,
  orchestratorTab: "routing",
  selectedRouteTask: null,
};

const icons = {
  home:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3.5 10.5 12 3l8.5 7.5v9a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M9 21v-7h6v7"/></svg>`,
  pipeline:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="7" height="6" rx="2"/><rect x="14" y="14" width="7" height="6" rx="2"/><path d="M10 7h4a3 3 0 0 1 3 3v4M14 17h-4a3 3 0 0 1-3-3v-4"/></svg>`,
  assets:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/><rect x="13" y="13" width="8" height="8" rx="2"/></svg>`,
  timeline:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h16M4 12h11M4 18h16"/><circle cx="7" cy="6" r="2" fill="currentColor"/><circle cx="17" cy="18" r="2" fill="currentColor"/></svg>`,
  runs:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5h16v14H4z"/><path d="M4 9h16M8 5v14"/></svg>`,
  brain:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9.5 4.5A3.5 3.5 0 0 0 6 8v.5A3.5 3.5 0 0 0 4.5 15 3.5 3.5 0 0 0 8 18.5h1.5V4.5Z"/><path d="M14.5 4.5A3.5 3.5 0 0 1 18 8v.5a3.5 3.5 0 0 1 1.5 6.5 3.5 3.5 0 0 1-3.5 3.5h-1.5V4.5Z"/><path d="M12 4v16"/></svg>`,
  settings:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z"/></svg>`,
  refresh:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>`,
  plus:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>`,
  file:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 2.8h8l4 4V21H6z"/><path d="M14 3v5h5"/></svg>`,
  play:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/></svg>`,
  check:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 4 4L19 6"/></svg>`,
  upload:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M4 15v5h16v-5"/></svg>`,
  image:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8" cy="9" r="2"/><path d="m4 17 5-5 4 4 3-3 4 4"/></svg>`,
  video:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 10 4-2v8l-4-2z"/></svg>`,
};

const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => Array.from(root.querySelectorAll(selector));
const escapeHtml = (value="") => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const formatDuration = value => { const s=Math.round(Number(value||0)); return s>=60?`${Math.floor(s/60)}m ${String(s%60).padStart(2,"0")}s`:`${s}s`; };
const formatDate = value => value ? new Date(value).toLocaleString() : "—";
const formatBytes = value => Number(value||0)>1048576?`${(Number(value)/1048576).toFixed(1)} MB`:`${(Number(value||0)/1024).toFixed(1)} KB`;

async function request(path, options={}) {
  const headers={...(options.headers||{})};
  if (!(options.body instanceof FormData) && options.body!=null && !headers["Content-Type"]) headers["Content-Type"]="application/json";
  const response=await fetch(path,{...options,headers});
  const type=response.headers.get("content-type")||"";
  let payload=null;
  try { payload=type.includes("application/json")?await response.json():await response.text(); } catch {}
  if (!response.ok) throw new Error(payload?.detail||payload?.error||payload||response.statusText);
  return payload;
}

function initializeIcons(){ $$('[data-icon]').forEach(node=>node.innerHTML=icons[node.dataset.icon]||icons.file); }
function toast(message,error=false){ const node=document.createElement("div"); node.className=`toast${error?" is-error":""}`; node.textContent=message; $("#toast-stack").append(node); setTimeout(()=>node.remove(),4500); }
function showError(error){ const message=error?.message||String(error); $("#global-alert").textContent=message; $("#global-alert").classList.remove("is-hidden"); toast(message,true); }
function clearError(){ $("#global-alert").classList.add("is-hidden"); }
function setBusy(button,busy,label="Working…"){ if(!button)return; if(busy){button.dataset.original=button.innerHTML;button.innerHTML=label;button.disabled=true;}else{button.innerHTML=button.dataset.original||button.innerHTML;button.disabled=false;} }

async function loadBootstrap(){
  clearError();
  state.bootstrap=await request("/api/bootstrap");
  state.projects=state.bootstrap.projects||[];
  if(!state.activeProjectId||!state.projects.some(item=>item.project_id===state.activeProjectId)) state.activeProjectId=state.projects[0]?.project_id||null;
  if(state.activeProjectId)localStorage.setItem("fde.activeProject",state.activeProjectId);
  await loadActiveProject(false);
  renderShell(); renderCurrentView();
}

async function loadActiveProject(render=true){
  if(!state.activeProjectId){state.activeProject=null;state.assets=[];state.timeline={entries:[],total_seconds:0};if(render)renderCurrentView();return;}
  const [project,assetPayload,timeline,logPayload]=await Promise.all([
    request(`/api/projects/${encodeURIComponent(state.activeProjectId)}`),
    request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/assets`),
    request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/timeline`),
    request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/logs?lines=240`),
  ]);
  state.activeProject=project; state.assets=assetPayload.assets||[]; state.assetSummary=assetPayload.summary||{}; state.timeline=timeline||{entries:[],total_seconds:0}; state.jobLog=logPayload?.log||"";
  if(!state.selectedStageId||!project.stages.some(item=>item.id===state.selectedStageId)) state.selectedStageId=project.stages.find(item=>["active","review"].includes(item.status))?.id||project.stages.at(-1)?.id;
  managePolling(); if(render){renderShell();renderCurrentView();}
}

function renderShell(){
  const config=state.bootstrap?.config||{capabilities:{}};
  $("#project-nav-count").textContent=state.projects.length;
  $("#asset-nav-count").textContent=state.activeProject?.metrics?.assets||0;
  $("#project-switcher").innerHTML=state.projects.length?state.projects.map(item=>`<option value="${escapeHtml(item.project_id)}" ${item.project_id===state.activeProjectId?"selected":""}>${escapeHtml(item.title)}</option>`).join(""):`<option value="">No projects</option>`;
  $("#capability-list").innerHTML=Object.entries(config.capabilities||{}).map(([name,ready])=>`<span class="capability-chip${ready?" is-ready":""}">${escapeHtml(name)}</span>`).join("");
  $("#engine-status").textContent=config.capabilities?.ffmpeg?"Ready for local rendering":"FFmpeg is required for previews";
  $$(".nav-item[data-nav]").forEach(node=>node.classList.toggle("is-active",node.dataset.nav===state.view));
  const titles={dashboard:["Production control room","Overview"],production:["Restartable audio-first workflow","Production"],assets:["Shot media review","Assets"],timeline:["Exact voice-led edit","Timeline"],runs:["All productions","Projects"],orchestrator:["Verified provider and model routing","AI Orchestrator"],settings:["Local engine configuration","Settings"]};
  const [eyebrow,title]=titles[state.view]||titles.dashboard; $("#page-eyebrow").textContent=eyebrow; $("#page-title").textContent=title;
}

function navigate(view){ state.view=view;location.hash=view;renderShell();renderCurrentView(); }
function renderCurrentView(){ $$(".page-view").forEach(node=>node.classList.toggle("is-active",node.id===`view-${state.view}`)); ({dashboard:renderDashboard,production:renderProduction,assets:renderAssets,timeline:renderTimeline,runs:renderRuns,orchestrator:renderOrchestrator,settings:renderSettings}[state.view]||renderDashboard)();initializeIcons(); }
function empty(title,text){return `<section class="empty-state"><span data-icon="file"></span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(text)}</p><button class="primary-button" id="dashboard-new-project">Create project</button></section>`;}
function statCard(label,value,note){return `<article class="stat-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`;}

function renderDashboard(){
  const root=$("#view-dashboard"); if(!state.projects.length){root.innerHTML=empty("Start the first investigation","Create a project, route its models, and run the narration-first production flow.");return;}
  const p=state.activeProject;
  root.innerHTML=`<section class="hero-grid"><article class="hero-card"><p class="eyebrow">Active investigation</p><h2>${escapeHtml(p.title)}</h2><p>${escapeHtml(p.topic)}</p><div class="progress-track"><i style="width:${p.progress}%"></i></div><div class="button-row"><button class="primary-button" data-nav-jump="production">Open production</button><button class="secondary-button" data-nav-jump="orchestrator">Review routing</button></div></article><div class="stats-grid">${statCard("Progress",`${p.progress}%`,p.state_label)}${statCard("Voice target",formatDuration(p.duration_seconds),"Audio owns timing")}${statCard("Shots",String(p.metrics?.shots||0),"Exact word-led divisions")}${statCard("Approved media",`${p.metrics?.images_approved||0}/${p.metrics?.videos_approved||0}`,"Images / videos")}</div></section>`;
}

function actionButton(action,disabled=false){return `<button class="primary-button" data-action="${escapeHtml(action.id)}" ${disabled?"disabled":""}><span data-icon="play"></span>${escapeHtml(action.label)}</button>`;}
function restartControls(stage,disabled){
  if(stage.status==="locked")return "";
  return `<div class="button-row" style="margin-top:14px"><button class="secondary-button" data-stage-restart="${escapeHtml(stage.id)}" ${disabled?"disabled":""}>Restart from here</button><button class="secondary-button" data-stage-rerun="${escapeHtml(stage.id)}" ${disabled?"disabled":""}>Run this step again</button></div><small style="display:block;margin-top:8px">Existing outputs are archived under <code>_history/</code>; they are not deleted.</small>`;
}

function renderProduction(){
  const root=$("#view-production"); const p=state.activeProject; if(!p){root.innerHTML=empty("No active project","Create a project to open the production pipeline.");return;}
  const selected=p.stages.find(item=>item.id===state.selectedStageId)||p.stages[0]; const running=p.job?.status==="running";
  root.innerHTML=`<section class="production-layout"><aside class="stage-rail">${p.stages.map(stage=>`<button class="stage-step ${stage.status} ${stage.id===selected.id?"is-selected":""}" data-stage-id="${stage.id}"><span>${stage.number}</span><div><strong>${escapeHtml(stage.short_title)}</strong><small>${escapeHtml(stage.status)}</small></div></button>`).join("")}</aside><div class="production-main"><section class="panel"><header class="panel-heading"><div><p class="eyebrow">Stage ${selected.number}</p><h2>${escapeHtml(selected.title)}</h2><p>${escapeHtml(selected.description)}</p></div><span class="status-pill ${selected.status}">${escapeHtml(selected.status)}</span></header>${selected.action?`<div class="next-action-card"><h3>${escapeHtml(selected.action.label)}</h3>${actionButton(selected.action,running)}</div>`:""}${restartControls(selected,running)}${selected.artifacts?.length?`<div class="artifact-grid" style="margin-top:18px">${selected.artifacts.map(item=>`<article class="artifact-card"><span data-icon="${item.kind==="image"?"image":item.kind==="video"?"video":"file"}"></span><span><strong>${escapeHtml(item.name)}</strong><small>${formatBytes(item.size)}</small></span><a href="${escapeHtml(item.url)}" target="_blank">Open ↗</a></article>`).join("")}</div>`:`<p class="muted-copy">No artifacts yet for this stage.</p>`}</section>${jobPanel(p.job,state.jobLog)}</div></section>`;
}

function jobPanel(job={status:"idle"},log=""){const working=job.status==="running";const showLog=working||job.status==="failed";const emptyLog=working?"Waiting for process output…":"No process output was captured.";return `<section class="panel job-panel"><div class="job-summary"><div><strong>${escapeHtml(job.label||"Process log")}</strong><small>${job.started_at?formatDate(job.started_at):"No active process"}</small></div><span class="status-indicator ${job.status}">${escapeHtml(job.status||"idle")}</span></div>${job.routing?`<div class="route-summary"><strong>${escapeHtml(job.routing.provider_label||job.routing.provider)} · ${escapeHtml(job.routing.model||"")}</strong><small>${[job.routing.resolution,job.routing.quality,job.routing.voice].filter(Boolean).join(" · ")}</small></div>`:""}${showLog?`<pre class="log-console" aria-live="polite">${escapeHtml(log||emptyLog)}</pre>`:""}${working?`<button class="danger-button" data-stop-job>Stop after current process</button>`:""}</section>`;}

function renderAssets(){
  const root=$("#view-assets"); if(!state.activeProject){root.innerHTML=empty("No active project","Open a project first.");return;}
  const target=state.assetMode;
  root.innerHTML=`<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Shot media</p><h2>${target==="image"?"Images":"Videos"}</h2><p>Approve only usable results. Rejected videos automatically retain the approved still in the final preview.</p></div><div class="segmented-control"><button data-asset-mode="image" class="${target==="image"?"is-active":""}">Images</button><button data-asset-mode="video" class="${target==="video"?"is-active":""}">Videos</button></div></header><div class="button-row"><label class="secondary-button"><span data-icon="upload"></span>Upload replacements<input id="asset-upload-input" type="file" multiple hidden></label><button class="primary-button" data-bulk-approve>Approve available ${target}s</button></div><div class="asset-grid">${state.assets.length?state.assets.map(asset=>assetCard(asset,target)).join(""):`<p>No shot media jobs yet.</p>`}</div></section>`;
}
function assetCard(asset,target){const url=target==="image"?asset.image_url:asset.video_url;const status=target==="image"?asset.image_review?.status:asset.video_review?.status;return `<article class="asset-card"><div class="asset-preview">${url?(target==="image"?`<img src="${url}" alt="">`:`<video src="${url}" controls muted></video>`):`<span data-icon="${target}"></span>`}</div><div class="asset-card-copy"><span class="status-pill ${status}">${escapeHtml(status||"pending")}</span><h3>${escapeHtml(asset.asset_id)}</h3><p>${escapeHtml(asset.title||"")}</p><div class="button-row">${url?`<button class="primary-button" data-review-asset="${asset.asset_id}" data-review-target="${target}" data-review-status="approved">Approve</button>`:""}<button class="secondary-button" data-review-asset="${asset.asset_id}" data-review-target="${target}" data-review-status="rejected">Reject</button></div></div></article>`;}

function renderTimeline(){
  const root=$("#view-timeline"); if(!state.activeProject){root.innerHTML=empty("No active project","Open a project first.");return;}
  root.innerHTML=`<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Voice timing authority</p><h2>${formatDuration(state.timeline.total_seconds)}</h2><p>Every entry follows the current approved voiceover and word-aligned shot plan.</p></div></header><div class="timeline-list">${(state.timeline.entries||[]).map(item=>`<article class="timeline-row"><time>${Number(item.start).toFixed(2)}–${Number(item.end).toFixed(2)}</time><strong>${escapeHtml(item.shot_id)}</strong><span>${escapeHtml(item.media_kind)}</span></article>`).join("")||"<p>No exact shots yet.</p>"}</div></section>`;
}
function renderRuns(){const root=$("#view-runs");root.innerHTML=`<section class="runs-grid">${state.projects.map(item=>`<article class="project-card"><p class="eyebrow">${escapeHtml(item.state_label)}</p><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.topic)}</p><div class="progress-track"><i style="width:${item.progress}%"></i></div><button class="primary-button" data-open-project="${item.project_id}">Open</button></article>`).join("")||empty("No projects","Create your first project.")}</section>`;}

function orchestrator(){return state.bootstrap?.orchestrator||{};}
function providerById(id){return (orchestrator().provider_catalog||[]).find(item=>item.id===id);}
function taskById(id){return (orchestrator().tasks||[]).find(item=>item.id===id);}
function modelsFor(provider,capability){return provider?.models_by_capability?.[capability]||[];}
function optionsFor(provider,capability,model){const options=provider?.options?.[capability]||{};return {resolutions:options.resolutions_by_model?.[model]||options.resolutions||[],quality:options.quality||[],ratios:options.aspect_ratio||[],durations:options.duration_by_model?.[model]||options.duration_seconds||[],voices:options.voices||[]};}

function renderOrchestrator(){
  const root=$("#view-orchestrator"); const data=orchestrator(); if(!data.tasks){root.innerHTML="<p>Loading routing…</p>";return;}
  const tabs=[["routing","Pipeline routing"],["providers","Providers"],["profiles","Profiles"],["prompts","Prompt packs"]];
  root.innerHTML=`<section class="orchestrator-shell"><header class="orchestrator-header"><div><p class="eyebrow">V1 model matrix · verified ${escapeHtml(data.docs_checked_at||"")}</p><h2>Audio-first provider routing</h2><p>Each task only offers providers and models verified for its capability. Media settings are provider-specific.</p></div></header><div class="orchestrator-tabs">${tabs.map(([id,label])=>`<button data-orchestrator-tab="${id}" class="${state.orchestratorTab===id?"is-active":""}">${label}</button>`).join("")}</div>${state.orchestratorTab==="routing"?routingMarkup(data):state.orchestratorTab==="providers"?providersMarkup(data):state.orchestratorTab==="profiles"?profilesMarkup(data):promptMarkup(data)}</section>`;
}
function routingMarkup(data){
  const stages=["story_setup","narration","voice","shots","images","animatic","videos","final_preview"];
  const labels={story_setup:"1 · Story setup",narration:"2 · Narration",voice:"3 · Voice and timing",shots:"4 · Shots",images:"5 · Images",animatic:"6 · Animatic",videos:"7 · Videos",final_preview:"8 · Final preview"};
  return `<div class="routing-groups">${stages.map(stage=>{const tasks=data.tasks.filter(item=>item.pipeline_stage===stage);return `<section class="routing-group"><header><h3>${labels[stage]}</h3><span>${tasks.length} tasks</span></header><div class="route-list">${tasks.map(task=>`<article class="route-card"><div><span class="capability-chip is-ready">${escapeHtml(task.capability)}</span><h4>${escapeHtml(task.label)}</h4><p>${escapeHtml(task.description)}</p></div><div class="route-provider"><strong>${escapeHtml(task.provider_label)}</strong><span>${escapeHtml(task.model)}</span><small>${[task.resolution,task.quality,task.voice].filter(Boolean).join(" · ")}</small></div><button class="secondary-button" data-edit-route="${task.id}">Configure</button></article>`).join("")}</div></section>`;}).join("")}</div>`;
}
function providersMarkup(data){return `<div class="provider-grid">${data.provider_catalog.map(item=>`<article class="provider-card"><header><div><h3>${escapeHtml(item.label)}</h3><p>${escapeHtml(item.description)}</p></div><span class="status-pill ${item.health?.healthy?"complete":"locked"}">${escapeHtml(item.health?.status||"unknown")}</span></header><div class="capability-list">${item.capabilities.map(cap=>`<span class="capability-chip is-ready">${cap}</span>`).join("")}</div>${Object.entries(item.models_by_capability||{}).map(([cap,models])=>`<div class="provider-models"><strong>${escapeHtml(cap)}</strong><small>${models.map(escapeHtml).join(" · ")}</small></div>`).join("")}<p class="muted-copy">${escapeHtml(item.integration_notes||"")}</p><div class="button-row"><a class="secondary-button" href="${escapeHtml(item.docs_url)}" target="_blank">Official docs ↗</a><button class="secondary-button" data-test-provider="${item.id}">Test</button></div></article>`).join("")}</div>`;}
function profilesMarkup(data){return `<div class="profile-grid">${data.profiles.map(item=>`<article class="profile-card ${data.active_profile===item.id?"is-active":""}"><p class="eyebrow">${data.active_profile===item.id?"Active":"Profile"}</p><h3>${escapeHtml(item.label)}</h3><p>${escapeHtml(item.description)}</p><button class="primary-button" data-apply-profile="${item.id}">Apply profile</button></article>`).join("")}</div>`;}
function promptMarkup(data){return `<div class="prompt-pack-grid">${Object.values(data.prompt_packs||{}).map(item=>`<article class="prompt-pack-card"><p class="eyebrow">${data.active_prompt_pack===item.id?"Active":"Prompt pack"}</p><h3>${escapeHtml(item.label)}</h3><p>${escapeHtml(item.description)}</p><button class="secondary-button" data-activate-pack="${item.id}">Activate</button></article>`).join("")}</div>`;}

function selectOptions(values,current){return values.map(value=>`<option value="${escapeHtml(value)}" ${String(value)===String(current)?"selected":""}>${escapeHtml(value)}</option>`).join("");}
function openRouteModal(taskId){state.selectedRouteTask=taskId;const task=taskById(taskId);const providers=(orchestrator().provider_catalog||[]).filter(item=>item.capabilities.includes(task.capability));const provider=providerById(task.provider);const fallback=providerById(task.fallback_provider)||providers[0];$("#route-modal-title").textContent=task.label;$("#route-modal-kicker").textContent=`${task.group} · ${task.capability}`;$("#route-form").innerHTML=`<input type="hidden" name="task_id" value="${task.id}"><input type="hidden" name="capability" value="${task.capability}"><label><span>Provider</span><select name="provider" id="route-provider">${providers.map(item=>`<option value="${item.id}" ${item.id===task.provider?"selected":""}>${escapeHtml(item.label)}</option>`).join("")}</select></label><label><span>Model</span><select name="model" id="route-model">${selectOptions(modelsFor(provider,task.capability),task.model)}</select></label><div id="route-media-fields" class="full-span form-grid"></div><label><span>Reasoning effort</span><select name="reasoning_effort">${selectOptions(["none","low","medium","high","xhigh","max","standard"],task.reasoning_effort)}</select></label><label><span>Timeout seconds</span><input name="timeout_seconds" type="number" value="${Number(task.timeout_seconds||900)}"></label><label><span>Retries</span><input name="retry_count" type="number" min="0" max="5" value="${Number(task.retry_count||0)}"></label><label><span>Fallback provider</span><select name="fallback_provider" id="route-fallback-provider">${providers.map(item=>`<option value="${item.id}" ${item.id===task.fallback_provider?"selected":""}>${escapeHtml(item.label)}</option>`).join("")}</select></label><label><span>Fallback model</span><select name="fallback_model" id="route-fallback-model">${selectOptions(modelsFor(fallback,task.capability),task.fallback_model)}</select></label><div id="route-docs" class="full-span"></div><footer class="modal-footer full-span"><button type="button" class="secondary-button route-modal-close">Cancel</button><button type="submit" class="primary-button">Save route</button></footer>`;refreshRouteFields(task);$("#route-modal").classList.remove("is-hidden");$("#route-modal").setAttribute("aria-hidden","false");}
function refreshRouteFields(task){const provider=providerById($("#route-provider")?.value);const modelSelect=$("#route-model");const current=modelSelect?.value||task.model;if(modelSelect){const models=modelsFor(provider,task.capability);modelSelect.innerHTML=selectOptions(models,models.includes(current)?current:models[0]);}const model=modelSelect?.value;const opts=optionsFor(provider,task.capability,model);const fields=[];if(opts.resolutions.length)fields.push(`<label><span>Resolution / output size</span><select name="resolution">${selectOptions(opts.resolutions,task.resolution)}</select></label>`);if(opts.quality.length)fields.push(`<label><span>Quality</span><select name="quality">${selectOptions(opts.quality,task.quality)}</select></label>`);if(opts.ratios.length)fields.push(`<label><span>Aspect ratio</span><select name="aspect_ratio">${selectOptions(opts.ratios,task.aspect_ratio||"16:9")}</select></label>`);if(opts.durations.length)fields.push(`<label><span>Provider generation duration</span><select name="duration_seconds">${selectOptions(opts.durations,task.duration_seconds)}</select></label>`);if(opts.voices.length)fields.push(`<label><span>Voice</span><select name="voice">${selectOptions(opts.voices,task.voice||"Kore")}</select></label>`);$("#route-media-fields").innerHTML=fields.join("")||`<p class="muted-copy">This task has no media-quality parameters.</p>`;$("#route-docs").innerHTML=`<div class="next-action-card"><strong>${escapeHtml(provider?.label||"")}</strong><p>${escapeHtml(provider?.integration_notes||provider?.description||"")}</p><a href="${escapeHtml(provider?.docs_url||"#")}" target="_blank">Official documentation · checked ${escapeHtml(provider?.docs_checked_at||"")} ↗</a></div>`;refreshFallback(task);}
function refreshFallback(task){const provider=providerById($("#route-fallback-provider")?.value);const select=$("#route-fallback-model");if(select){const models=modelsFor(provider,task.capability);const current=select.value||task.fallback_model;select.innerHTML=selectOptions(models,models.includes(current)?current:models[0]);}}
function closeRouteModal(){$("#route-modal").classList.add("is-hidden");$("#route-modal").setAttribute("aria-hidden","true");}

function renderSettings(){const root=$("#view-settings");const c=state.bootstrap?.config||{};root.innerHTML=`<section class="panel"><header class="panel-heading"><div><p class="eyebrow">Studio defaults</p><h2>Local settings</h2></div></header><form id="settings-form" class="form-grid"><label><span>Agent mode</span><select name="agent_mode">${selectOptions(["manual","command","mock"],c.agent_mode)}</select></label><label><span>Auto refresh seconds</span><input name="auto_refresh_seconds" type="number" value="${c.auto_refresh_seconds||2}"></label><label class="full-span"><span>Default command template</span><input name="command_template" value="${escapeHtml(c.command_template||"")}"></label><footer class="modal-footer full-span"><button class="primary-button" type="submit">Save settings</button></footer></form></section>`;}

async function executeAction(action,button){setBusy(button,true);try{await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/actions/${encodeURIComponent(action)}`,{method:"POST",body:"{}"});toast("Action started");await loadActiveProject();}catch(error){showError(error);}finally{setBusy(button,false);}}
async function restartOrRerun(stageId,runAgain,button){const wording=runAgain?"archive this stage and all downstream output, then run it again":"archive this stage and all downstream output, then stop at its starting point";if(!confirm(`This will ${wording}. Upstream approved work is preserved. Continue?`))return;setBusy(button,true,"Restarting…");try{await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/actions/${runAgain?"rerun_":"restart_"}${stageId}`,{method:"POST",body:"{}"});toast(runAgain?"Stage archived and started again":"Stage archived and reset");state.selectedStageId=stageId;await loadActiveProject();}catch(error){showError(error);}finally{setBusy(button,false);}}
async function reviewAsset(assetId,target,status){try{await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/assets/${encodeURIComponent(assetId)}/review`,{method:"POST",body:JSON.stringify({target,status})});toast(`${assetId} ${status}`);await loadActiveProject();}catch(error){showError(error);}}
async function uploadAssets(files){if(!files?.length)return;const form=new FormData();Array.from(files).forEach(file=>form.append("files",file));try{await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/upload/${state.assetMode}s`,{method:"POST",body:form});toast("Replacement media uploaded");await loadActiveProject();}catch(error){showError(error);}}

function managePolling(){clearInterval(state.pollTimer);if(state.activeProject?.job?.status==="running")state.pollTimer=setInterval(()=>loadActiveProject(),2000);}
function openNewProjectModal(){$("#new-project-modal").classList.remove("is-hidden");}
function closeNewProjectModal(){$("#new-project-modal").classList.add("is-hidden");}

function bindEvents(){
  document.addEventListener("click",async event=>{
    const nav=event.target.closest("[data-nav]");if(nav){event.preventDefault();navigate(nav.dataset.nav);return;}
    const jump=event.target.closest("[data-nav-jump]");if(jump){navigate(jump.dataset.navJump);return;}
    if(event.target.closest("#new-project-button,#dashboard-new-project,#runs-new-project")){openNewProjectModal();return;}
    if(event.target.closest(".modal-close")){closeNewProjectModal();return;}
    if(event.target.closest(".route-modal-close")||event.target.id==="route-modal"){closeRouteModal();return;}
    const open=event.target.closest("[data-open-project]");if(open){state.activeProjectId=open.dataset.openProject;localStorage.setItem("fde.activeProject",state.activeProjectId);await loadActiveProject();navigate("production");return;}
    const stage=event.target.closest("[data-stage-id]");if(stage){state.selectedStageId=stage.dataset.stageId;renderProduction();initializeIcons();return;}
    const action=event.target.closest("[data-action]");if(action){await executeAction(action.dataset.action,action);return;}
    const restart=event.target.closest("[data-stage-restart]");if(restart){await restartOrRerun(restart.dataset.stageRestart,false,restart);return;}
    const rerun=event.target.closest("[data-stage-rerun]");if(rerun){await restartOrRerun(rerun.dataset.stageRerun,true,rerun);return;}
    if(event.target.closest("[data-stop-job]")){await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/stop`,{method:"POST"});toast("Stop requested");await loadActiveProject();return;}
    const mode=event.target.closest("[data-asset-mode]");if(mode){state.assetMode=mode.dataset.assetMode;renderAssets();initializeIcons();return;}
    const review=event.target.closest("[data-review-asset]");if(review){await reviewAsset(review.dataset.reviewAsset,review.dataset.reviewTarget,review.dataset.reviewStatus);return;}
    if(event.target.closest("[data-bulk-approve]")){const ids=state.assets.filter(item=>state.assetMode==="image"?item.image_url:item.video_url).map(item=>item.asset_id);await request(`/api/projects/${encodeURIComponent(state.activeProjectId)}/assets/bulk-review`,{method:"POST",body:JSON.stringify({target:state.assetMode,status:"approved",asset_ids:ids})});toast(`Approved ${ids.length} items`);await loadActiveProject();return;}
    const tab=event.target.closest("[data-orchestrator-tab]");if(tab){state.orchestratorTab=tab.dataset.orchestratorTab;renderOrchestrator();initializeIcons();return;}
    const edit=event.target.closest("[data-edit-route]");if(edit){openRouteModal(edit.dataset.editRoute);return;}
    const test=event.target.closest("[data-test-provider]");if(test){setBusy(test,true,"Testing…");try{const result=await request(`/api/orchestrator/providers/${test.dataset.testProvider}/test`,{method:"POST"});toast(result.detail);await loadBootstrap();}catch(error){showError(error);}finally{setBusy(test,false);}return;}
    const profile=event.target.closest("[data-apply-profile]");if(profile){state.bootstrap.orchestrator=await request(`/api/orchestrator/profiles/${profile.dataset.applyProfile}/apply`,{method:"POST"});toast("Profile applied");renderOrchestrator();initializeIcons();return;}
    const pack=event.target.closest("[data-activate-pack]");if(pack){state.bootstrap.orchestrator=await request("/api/orchestrator",{method:"PATCH",body:JSON.stringify({active_prompt_pack:pack.dataset.activatePack})});toast("Prompt pack activated");renderOrchestrator();initializeIcons();return;}
  });
  document.addEventListener("change",async event=>{
    if(event.target.id==="project-switcher"){state.activeProjectId=event.target.value;await loadActiveProject();return;}
    if(event.target.id==="asset-upload-input"){await uploadAssets(event.target.files);return;}
    if(event.target.id==="route-provider"){refreshRouteFields(taskById(state.selectedRouteTask));return;}
    if(event.target.id==="route-model"){refreshRouteFields(taskById(state.selectedRouteTask));return;}
    if(event.target.id==="route-fallback-provider"){refreshFallback(taskById(state.selectedRouteTask));return;}
  });
  document.addEventListener("submit",async event=>{
    if(event.target.id==="new-project-form"){event.preventDefault();const button=event.submitter;setBusy(button,true);const values=Object.fromEntries(new FormData(event.target).entries());values.target_duration_seconds=Number(values.target_duration_seconds);values.maximum_master_assets=Number(values.maximum_master_assets);values.master_video_duration_seconds=Number(values.master_video_duration_seconds);try{const project=await request("/api/projects",{method:"POST",body:JSON.stringify(values)});state.activeProjectId=project.project_id;closeNewProjectModal();event.target.reset();await loadBootstrap();navigate("production");}catch(error){showError(error);}finally{setBusy(button,false);}return;}
    if(event.target.id==="route-form"){event.preventDefault();const button=event.submitter;setBusy(button,true);const form=new FormData(event.target);const taskId=String(form.get("task_id"));const payload={provider:form.get("provider"),model:form.get("model"),reasoning_effort:form.get("reasoning_effort"),timeout_seconds:Number(form.get("timeout_seconds")),retry_count:Number(form.get("retry_count")),fallback_provider:form.get("fallback_provider"),fallback_model:form.get("fallback_model"),quality:form.get("quality")||"",resolution:form.get("resolution")||"",aspect_ratio:form.get("aspect_ratio")||"",duration_seconds:Number(form.get("duration_seconds")||0),voice:form.get("voice")||"",enabled:true};try{state.bootstrap.orchestrator=await request("/api/orchestrator",{method:"PATCH",body:JSON.stringify({tasks:{[taskId]:payload}})});closeRouteModal();renderOrchestrator();initializeIcons();toast("Route saved");}catch(error){showError(error);}finally{setBusy(button,false);}return;}
    if(event.target.id==="settings-form"){event.preventDefault();const button=event.submitter;setBusy(button,true);const data=Object.fromEntries(new FormData(event.target).entries());data.auto_refresh_seconds=Number(data.auto_refresh_seconds);try{await request("/api/config",{method:"PATCH",body:JSON.stringify(data)});await loadBootstrap();toast("Settings saved");}catch(error){showError(error);}finally{setBusy(button,false);}return;}
  });
  $("#refresh-button").addEventListener("click",()=>loadBootstrap());
  window.addEventListener("hashchange",()=>{const view=location.hash.replace("#","")||"dashboard";if(["dashboard","production","assets","timeline","runs","orchestrator","settings"].includes(view)){state.view=view;renderShell();renderCurrentView();}});
}

async function start(){initializeIcons();bindEvents();try{await loadBootstrap();navigate(state.view);}catch(error){showError(error);}}
start();
