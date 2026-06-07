const API_ROOT = "";
const THEME_STORAGE_KEY = "smol.ui.theme";
const ALLOWED_THEMES = ["dark", "light", "modern-tech"];
const DEFAULT_MODEL_BY_PROVIDER = {
  hf_inference: "Qwen/Qwen3-Next-80B-A3B-Thinking",
  litellm: "gpt-4o-mini",
  openai: "gpt-4o-mini",
  ollama: "llama3.1",
};

const SESSION_EVENT_LIMIT = 120;
const OLDER_EVENTS_LIMIT = 200;
const SESSION_REFRESH_MIN_INTERVAL_MS = 1500;
const MAX_RENDERED_CARDS = 350;
const SSE_BASE_RETRY_MS = 500;
const SSE_MAX_RETRY_MS = 10000;
const LONG_SECTION_CHAR_THRESHOLD = 420;
const LONG_SECTION_LINE_THRESHOLD = 10;
const DETAIL_SUMMARY_MAX_CHARS = 96;
const STATE_SECTION_COLLAPSE_THRESHOLD = 260;

const state = {
  sessions: [],
  activeSessionId: null,
  activeSession: null,
  lastEventSeq: 0,
  oldestEventSeq: null,
  hasOlderEvents: false,
  loadingOlderEvents: false,
  eventSource: null,
  reconnectTimer: null,
  reconnectAttempts: 0,
  loadingSessions: false,
  sessionsRefreshTimer: null,
  lastSessionsLoadMs: 0,
  runLocked: false,
  streamCardBody: null,
  renderedEventSeqs: new Set(),
};

const elements = {
  body: document.body,
  themeSelect: document.getElementById("theme-select"),
  mobileTabs: Array.from(document.querySelectorAll(".mobile-tab")),
  newSessionButton: document.getElementById("new-session-btn"),
  sessionList: document.getElementById("session-list"),
  sessionTitle: document.getElementById("session-title"),
  livePill: document.getElementById("live-pill"),
  chatFeed: document.getElementById("chat-feed"),
  chatCardTemplate: document.getElementById("chat-card-template"),
  runForm: document.getElementById("run-form"),
  runButton: document.getElementById("run-btn"),
  promptInput: document.getElementById("prompt-input"),
  providerSelect: document.getElementById("provider-select"),
  modelIdInput: document.getElementById("model-id-input"),
  apiBaseInput: document.getElementById("api-base-input"),
  apiKeyInput: document.getElementById("api-key-input"),
  hfProviderInput: document.getElementById("hf-provider-input"),
  maxStepsInput: document.getElementById("max-steps-input"),
  planningIntervalInput: document.getElementById("planning-interval-input"),
  importsInput: document.getElementById("imports-input"),
  refreshTreeButton: document.getElementById("refresh-tree-btn"),
  refreshStateButton: document.getElementById("refresh-state-btn"),
  workspaceTree: document.getElementById("workspace-tree"),
  recentFiles: document.getElementById("recent-files"),
  agentState: document.getElementById("agent-state"),
};

function normalizeTheme(candidate) {
  return ALLOWED_THEMES.includes(candidate) ? candidate : "dark";
}

function applyTheme(candidate) {
  const normalized = normalizeTheme(candidate);
  elements.body.dataset.theme = normalized;
  if (elements.themeSelect && elements.themeSelect.value !== normalized) {
    elements.themeSelect.value = normalized;
  }
  try {
    localStorage.setItem(THEME_STORAGE_KEY, normalized);
  } catch (_error) {
    // Ignore localStorage failures in restricted environments.
  }
  return normalized;
}

function loadThemeFromStorage() {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    applyTheme(stored);
  } catch (_error) {
    applyTheme("dark");
  }
}

function setMobilePanel(panelName) {
  elements.body.dataset.mobilePanel = panelName;
  for (const button of elements.mobileTabs) {
    button.classList.toggle("active", button.dataset.target === panelName);
  }
}

function formatTimestamp(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

function stringifyValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return String(value);
  }
}

function humanizeEventType(eventType) {
  const labels = {
    run_started: "run",
    assistant_delta: "stream",
    tool_call: "tool",
    tool_output: "output",
    action_step: "action",
    planning_step: "plan",
    final_answer_step: "final-step",
    run_completed: "completed",
    run_failed: "failed",
  };
  return labels[eventType] || "event";
}

function eventStatus(eventType, payload = {}) {
  if (eventType === "run_failed" || payload.error) {
    return "error";
  }
  if (eventType === "run_completed" || eventType === "final_answer_step" || payload.is_final_answer) {
    return "complete";
  }
  if (eventType === "run_started" || eventType === "assistant_delta" || eventType === "tool_call" || eventType === "action_step") {
    return "running";
  }
  return "idle";
}

function collapseLongText(text) {
  const lineCount = text.split(/\r?\n/).length;
  return lineCount > LONG_SECTION_LINE_THRESHOLD || text.length > LONG_SECTION_CHAR_THRESHOLD;
}

function detailSummary(text) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (compact.length <= DETAIL_SUMMARY_MAX_CHARS) {
    return compact || "details";
  }
  return `${compact.slice(0, DETAIL_SUMMARY_MAX_CHARS - 3)}...`;
}

async function apiGet(path) {
  const response = await fetch(`${API_ROOT}${path}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `GET ${path} failed with ${response.status}`);
  }
  return payload;
}

async function apiPost(path, body) {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `POST ${path} failed with ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function setLivePill(status) {
  const pill = elements.livePill;
  if (!pill) {
    return;
  }
  pill.textContent = status;
  pill.classList.toggle("running", status === "running");
}

function setRunLock(locked) {
  state.runLocked = Boolean(locked);
  if (elements.runButton) {
    elements.runButton.disabled = state.runLocked || !state.activeSessionId;
    elements.runButton.textContent = state.runLocked ? "Running..." : "Run Agent";
  }
}

function renderEmptyState(parentNode, title, detail = "") {
  if (!parentNode) {
    return;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "empty-state";

  const titleNode = document.createElement("p");
  titleNode.className = "empty-state-title";
  titleNode.textContent = title;
  wrapper.appendChild(titleNode);

  if (detail) {
    const detailNode = document.createElement("p");
    detailNode.className = "empty-state-detail";
    detailNode.textContent = detail;
    wrapper.appendChild(detailNode);
  }

  parentNode.appendChild(wrapper);
}

function appendBadge(node, text, className) {
  if (!node || !text) {
    return;
  }
  const badge = document.createElement("span");
  badge.className = className;
  badge.textContent = text;
  node.appendChild(badge);
}

function applyCardMetadata(card, { event = null, status = "", step = "" } = {}) {
  if (!card.badgesNode || !card.metaNode) {
    return;
  }

  card.badgesNode.replaceChildren();
  const payload = event && event.payload ? event.payload : {};
  const stepNumber = payload && Number.isFinite(Number(payload.step_number)) ? Number(payload.step_number) : null;
  const resolvedStep = step || (stepNumber !== null ? `step ${stepNumber}` : "");
  if (resolvedStep) {
    appendBadge(card.badgesNode, resolvedStep, "badge badge--step");
  }

  const type = event && event.type ? humanizeEventType(event.type) : "";
  if (type) {
    appendBadge(card.badgesNode, type, "badge badge--type");
  }

  const resolvedStatus = status || eventStatus(event?.type, event?.payload || {});
  if (resolvedStatus) {
    appendBadge(card.badgesNode, resolvedStatus, `badge badge--status badge--status-${resolvedStatus}`);
  }

  const metaParts = [];
  if (event && event.timestamp) {
    metaParts.push(formatTimestamp(event.timestamp));
  }
  const durationRaw = event?.payload?.duration_seconds;
  if (typeof durationRaw === "number" && Number.isFinite(durationRaw)) {
    metaParts.push(`${durationRaw.toFixed(3)}s`);
  }
  card.metaNode.textContent = metaParts.join(" - ");
}

function buildCard({ title, classes = [], event = null, status = "", step = "" }) {
  const template = elements.chatCardTemplate;
  const root = template && "content" in template
    ? template.content.firstElementChild.cloneNode(true)
    : document.createElement("article");
  root.classList.add(...classes);
  if (!root.classList.contains("chat-card")) {
    root.classList.add("chat-card");
  }
  const headerNode = root.querySelector(".chat-card-header") || document.createElement("header");
  const titleNode = root.querySelector(".chat-card-title") || document.createElement("div");
  const badgesNode = root.querySelector(".chat-card-badges") || document.createElement("div");
  const metaNode = root.querySelector(".chat-card-meta") || document.createElement("div");
  const bodyNode = root.querySelector(".chat-card-body") || document.createElement("div");
  headerNode.classList.add("chat-card-header");
  titleNode.classList.add("chat-card-title");
  badgesNode.classList.add("chat-card-badges");
  metaNode.classList.add("chat-card-meta");
  bodyNode.classList.add("chat-card-body");
  titleNode.textContent = title;

  if (!titleNode.parentNode) {
    headerNode.appendChild(titleNode);
  }
  if (!badgesNode.parentNode) {
    headerNode.appendChild(badgesNode);
  }
  if (!headerNode.parentNode) {
    root.appendChild(headerNode);
  }
  if (!metaNode.parentNode) {
    root.appendChild(metaNode);
  }
  if (!bodyNode.parentNode) {
    root.appendChild(bodyNode);
  }

  const card = { root, bodyNode, titleNode, metaNode, badgesNode };
  applyCardMetadata(card, { event, status, step });
  return card;
}

function appendTextSection(bodyNode, heading, value, className = "", options = {}) {
  if (value === null || value === undefined || value === "") {
    return;
  }

  const text = stringifyValue(value);
  const shouldCollapse = options.forceCollapse || (options.collapseLong !== false && collapseLongText(text));

  if (shouldCollapse) {
    const details = document.createElement("details");
    details.className = "detail-block";
    if (options.openByDefault) {
      details.open = true;
    }
    const summary = document.createElement("summary");
    summary.textContent = heading ? `${heading}: ${detailSummary(text)}` : detailSummary(text);

    const pre = document.createElement("pre");
    if (className) {
      pre.classList.add(className);
    }
    pre.textContent = text;

    details.appendChild(summary);
    details.appendChild(pre);
    bodyNode.appendChild(details);
    return;
  }

  const block = document.createElement("div");
  block.className = "detail-inline-block";
  if (heading) {
    const label = document.createElement("div");
    label.className = "detail-label";
    label.textContent = heading;
    block.appendChild(label);
  }
  const pre = document.createElement("pre");
  pre.classList.add("detail-inline");
  if (className) {
    pre.classList.add(className);
  }
  pre.textContent = text;
  block.appendChild(pre);
  bodyNode.appendChild(block);
}

function shouldCollapseStateValue(valueText) {
  return valueText.length > STATE_SECTION_COLLAPSE_THRESHOLD || valueText.includes("\n");
}

function buildStateSection(label, rawValue) {
  const section = document.createElement("section");
  section.className = "state-section";

  const heading = document.createElement("h3");
  heading.className = "state-section-title";
  heading.textContent = label;
  section.appendChild(heading);

  const valueText = stringifyValue(rawValue);
  if (!valueText) {
    const empty = document.createElement("p");
    empty.className = "state-empty";
    empty.textContent = "empty";
    section.appendChild(empty);
    return section;
  }

  if (shouldCollapseStateValue(valueText)) {
    const details = document.createElement("details");
    details.className = "state-details";
    const summary = document.createElement("summary");
    summary.textContent = detailSummary(valueText);
    const pre = document.createElement("pre");
    pre.textContent = valueText;
    details.appendChild(summary);
    details.appendChild(pre);
    section.appendChild(details);
    return section;
  }

  const pre = document.createElement("pre");
  pre.textContent = valueText;
  section.appendChild(pre);
  return section;
}

function renderAgentState(stateValue) {
  if (!elements.agentState) {
    return;
  }

  elements.agentState.replaceChildren();

  if (stateValue === null || stateValue === undefined) {
    renderEmptyState(elements.agentState, "Agent state will appear after a run");
    return;
  }

  if (typeof stateValue !== "object" || Array.isArray(stateValue)) {
    const section = buildStateSection("state", stateValue);
    elements.agentState.appendChild(section);
    return;
  }

  const entries = Object.entries(stateValue);
  if (entries.length === 0) {
    renderEmptyState(elements.agentState, "Agent state will appear after a run");
    return;
  }

  for (const [key, value] of entries) {
    elements.agentState.appendChild(buildStateSection(key, value));
  }
}

function insertCard(cardNode, mode = "append") {
  const feed = elements.chatFeed;
  if (!feed) {
    return;
  }

  if (mode === "prepend") {
    const firstCard = feed.querySelector(".chat-card");
    if (firstCard) {
      feed.insertBefore(cardNode, firstCard);
    } else {
      feed.appendChild(cardNode);
    }
  } else {
    feed.appendChild(cardNode);
  }

  enforceRenderedCardLimit(mode);
}

function enforceRenderedCardLimit(mode = "append") {
  const cards = elements.chatFeed ? Array.from(elements.chatFeed.querySelectorAll(".chat-card")) : [];
  if (cards.length <= MAX_RENDERED_CARDS) {
    return;
  }
  let overflow = cards.length - MAX_RENDERED_CARDS;
  while (overflow > 0) {
    const target = mode === "prepend" ? cards.pop() : cards.shift();
    if (!target) {
      break;
    }
    target.remove();
    overflow -= 1;
  }
}

function ensureHistoryControls() {
  if (!elements.chatFeed) {
    return;
  }
  let controls = elements.chatFeed.querySelector("#history-controls");
  if (!controls) {
    controls = document.createElement("div");
    controls.id = "history-controls";
    controls.className = "history-controls";

    const button = document.createElement("button");
    button.type = "button";
    button.id = "load-older-btn";
    button.textContent = "Load older events";
    button.addEventListener("click", () => {
      void loadOlderEvents();
    });

    controls.appendChild(button);
    elements.chatFeed.appendChild(controls);
  }
  updateHistoryButton();
}

function updateHistoryButton() {
  const button = document.getElementById("load-older-btn");
  if (!button) {
    return;
  }
  button.hidden = !state.hasOlderEvents;
  button.disabled = state.loadingOlderEvents;
  if (state.loadingOlderEvents) {
    button.textContent = "Loading...";
  } else {
    button.textContent = "Load older events";
  }
}

function clearChatFeed() {
  if (!elements.chatFeed) {
    return;
  }
  elements.chatFeed.replaceChildren();
  state.streamCardBody = null;
  state.renderedEventSeqs.clear();
  ensureHistoryControls();
}

function renderNoRunSelected() {
  if (!elements.chatFeed) {
    return;
  }
  elements.chatFeed.replaceChildren();
  state.streamCardBody = null;
  state.renderedEventSeqs.clear();
  renderEmptyState(elements.chatFeed, "No run selected", "Create or select a session to start an agent run.");
}

function setSessionTitle(text) {
  if (elements.sessionTitle) {
    elements.sessionTitle.textContent = text;
  }
}

function renderSessions() {
  if (!elements.sessionList) {
    return;
  }

  elements.sessionList.replaceChildren();
  if (state.sessions.length === 0) {
    renderEmptyState(elements.sessionList, "No sessions yet", "Create a session to start a run.");
    return;
  }

  for (const session of state.sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    button.dataset.sessionId = session.id;
    if (session.id === state.activeSessionId) {
      button.classList.add("active");
    }

    const title = document.createElement("span");
    title.className = "session-item-title";
    title.textContent = session.title || "Untitled Session";

    const meta = document.createElement("span");
    meta.className = "session-item-meta";
    const runState = session.is_running ? "running" : "idle";
    meta.textContent = `runs ${session.run_count || 0} - ${runState} - ${formatTimestamp(session.updated_at)}`;

    button.appendChild(title);
    button.appendChild(meta);
    button.addEventListener("click", () => {
      if (state.activeSessionId === session.id) {
        return;
      }
      void selectSession(session.id);
    });

    elements.sessionList.appendChild(button);
  }
}

async function loadSessions(force = false) {
  const now = Date.now();
  if (!force && now - state.lastSessionsLoadMs < SESSION_REFRESH_MIN_INTERVAL_MS) {
    scheduleLoadSessions();
    return;
  }
  if (state.loadingSessions) {
    return;
  }

  state.loadingSessions = true;
  try {
    const payload = await apiGet("/api/sessions");
    state.sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    state.lastSessionsLoadMs = Date.now();
    renderSessions();

    if (!state.activeSessionId && state.sessions.length > 0) {
      await selectSession(state.sessions[0].id);
      return;
    }

    if (!state.activeSessionId && state.sessions.length === 0) {
      state.activeSession = null;
      state.hasOlderEvents = false;
      state.oldestEventSeq = null;
      setSessionTitle("No run selected");
      renderNoRunSelected();
      renderAgentState({});
      setRunLock(false);
      setLivePill("idle");
      return;
    }

    if (state.activeSessionId) {
      const activeSummary = state.sessions.find((entry) => entry.id === state.activeSessionId) || null;
      if (!activeSummary && state.sessions.length > 0) {
        await selectSession(state.sessions[0].id);
        return;
      }
      if (!activeSummary && state.sessions.length === 0) {
        state.activeSessionId = null;
        state.activeSession = null;
        setSessionTitle("No run selected");
        renderNoRunSelected();
        renderAgentState({});
        setRunLock(false);
        setLivePill("idle");
        return;
      }
      if (activeSummary && !state.runLocked) {
        setRunLock(Boolean(activeSummary.is_running));
      }
    }
  } catch (error) {
    console.error(error);
  } finally {
    state.loadingSessions = false;
  }
}

function scheduleLoadSessions() {
  if (state.sessionsRefreshTimer) {
    return;
  }
  const elapsed = Date.now() - state.lastSessionsLoadMs;
  const delay = Math.max(0, SESSION_REFRESH_MIN_INTERVAL_MS - elapsed);
  state.sessionsRefreshTimer = window.setTimeout(() => {
    state.sessionsRefreshTimer = null;
    void loadSessions(false);
  }, delay);
}

function extractSeq(event) {
  const seq = Number(event && event.seq);
  return Number.isFinite(seq) ? seq : null;
}

function renderRunStarted(event, mode) {
  const payload = event.payload || {};
  const { root, bodyNode } = buildCard({
    title: "Prompt",
    classes: ["user"],
    event,
    status: "running",
  });
  appendTextSection(bodyNode, "prompt", payload.prompt || "", "", { collapseLong: false });
  appendTextSection(bodyNode, "config", payload.config || {}, "", { forceCollapse: true });
  insertCard(root, mode);
  state.streamCardBody = null;
  setRunLock(true);
  setLivePill("running");
}

function renderAssistantDelta(event) {
  const payload = event.payload || {};
  const text = payload.text;
  if (text === null || text === undefined || text === "") {
    return;
  }

  if (!state.streamCardBody) {
    const card = buildCard({
      title: "Streaming Output",
      classes: ["stream"],
      event,
      status: "running",
    });
    state.streamCardBody = card.bodyNode;
    state.streamCardBody.textContent = "";
    insertCard(card.root, "append");
  }

  state.streamCardBody.textContent += String(text);
  if (elements.chatFeed) {
    elements.chatFeed.scrollTop = elements.chatFeed.scrollHeight;
  }
}

function renderToolCall(event, mode) {
  const payload = event.payload || {};
  const title = payload.name ? `Tool Call - ${payload.name}` : "Tool Call";
  const { root, bodyNode } = buildCard({ title, classes: ["tool"], event, status: "running" });
  appendTextSection(bodyNode, "input summary", payload.arguments || "", "", { collapseLong: false });
  appendTextSection(bodyNode, "raw arguments", payload.arguments || {}, "", { forceCollapse: true });
  insertCard(root, mode);
}

function renderToolOutput(event, mode) {
  const payload = event.payload || {};
  const title = payload.name ? `Tool Output - ${payload.name}` : "Tool Output";
  const { root, bodyNode } = buildCard({ title, classes: ["tool"], event });
  appendTextSection(bodyNode, "observation", payload.observation || "", "", { collapseLong: true });
  appendTextSection(bodyNode, "output", payload.output || "", "output-block", { collapseLong: true });
  insertCard(root, mode);
}

function renderActionStep(event, mode) {
  const payload = event.payload || {};
  const stepNumber = payload.step_number ? `step ${payload.step_number}` : "";
  const { root, bodyNode } = buildCard({
    title: "Action Step",
    classes: ["reasoning", "verbose"],
    event,
    step: stepNumber,
  });
  appendTextSection(bodyNode, "model output", payload.model_output || "", "", { collapseLong: true });
  appendTextSection(bodyNode, "code", payload.code_action || "", "", { forceCollapse: true });
  appendTextSection(bodyNode, "observations", payload.observations || "", "", { collapseLong: true });
  appendTextSection(bodyNode, "result", payload.action_output || "", "output-block", { collapseLong: true });
  appendTextSection(bodyNode, "error", payload.error || "", "", { openByDefault: true, collapseLong: false });
  insertCard(root, mode);
}

function renderPlanningStep(event, mode) {
  const payload = event.payload || {};
  const { root, bodyNode } = buildCard({ title: "Planning Step", classes: ["reasoning", "verbose"], event });
  appendTextSection(bodyNode, "plan", payload.plan || "", "", { collapseLong: true });
  appendTextSection(bodyNode, "model output", payload.model_output || "", "", { collapseLong: true });
  insertCard(root, mode);
}

function renderFinalAnswerStep(event, mode) {
  const payload = event.payload || {};
  const { root, bodyNode } = buildCard({ title: "Final Answer Step", classes: ["final"], event, status: "complete" });
  appendTextSection(bodyNode, "output", payload.output || "", "output-block", { collapseLong: false });
  insertCard(root, mode);
}

function renderRunCompleted(event, mode) {
  if (state.streamCardBody && state.streamCardBody.parentElement) {
    state.streamCardBody.parentElement.classList.remove("stream");
  }
  state.streamCardBody = null;

  const payload = event.payload || {};
  if (payload.final_answer !== null && payload.final_answer !== undefined && payload.final_answer !== "") {
    const { root, bodyNode } = buildCard({ title: "Final Answer", classes: ["final"], event, status: "complete" });
    appendTextSection(bodyNode, "answer", payload.final_answer, "output-block", { collapseLong: false });
    insertCard(root, mode);
  }

  setRunLock(false);
  setLivePill("idle");
}

function renderRunFailed(event, mode) {
  if (state.streamCardBody && state.streamCardBody.parentElement) {
    state.streamCardBody.parentElement.classList.remove("stream");
  }
  state.streamCardBody = null;

  const payload = event.payload || {};
  const { root, bodyNode } = buildCard({ title: "Run Failed", classes: ["error"], event, status: "error" });
  appendTextSection(bodyNode, "error", payload.error || "Unknown error", "", { openByDefault: true, collapseLong: false });
  insertCard(root, mode);

  setRunLock(false);
  setLivePill("idle");
}

function renderGenericEvent(event, mode) {
  const { root, bodyNode } = buildCard({ title: event.type || "Event", classes: ["system"], event });
  appendTextSection(bodyNode, "payload", event.payload || {}, "", { forceCollapse: true });
  insertCard(root, mode);
}

function renderEvent(event, mode = "append") {
  const seq = extractSeq(event);
  if (seq !== null && state.renderedEventSeqs.has(seq)) {
    return;
  }

  switch (event.type) {
    case "run_started":
      renderRunStarted(event, mode);
      break;
    case "assistant_delta":
      renderAssistantDelta(event);
      break;
    case "tool_call":
      renderToolCall(event, mode);
      break;
    case "tool_output":
      renderToolOutput(event, mode);
      break;
    case "action_step":
      renderActionStep(event, mode);
      break;
    case "planning_step":
      renderPlanningStep(event, mode);
      break;
    case "final_answer_step":
      renderFinalAnswerStep(event, mode);
      break;
    case "run_completed":
      renderRunCompleted(event, mode);
      break;
    case "run_failed":
      renderRunFailed(event, mode);
      break;
    default:
      renderGenericEvent(event, mode);
      break;
  }

  if (seq !== null) {
    state.renderedEventSeqs.add(seq);
    state.lastEventSeq = Math.max(state.lastEventSeq, seq);
  }

  if (event.type === "run_started" || event.type === "run_completed" || event.type === "run_failed") {
    scheduleLoadSessions();
  }
}

function closeEventStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (state.reconnectTimer) {
    window.clearTimeout(state.reconnectTimer);
    state.reconnectTimer = null;
  }
}

function scheduleStreamReconnect() {
  if (!state.activeSessionId || state.reconnectTimer) {
    return;
  }

  state.reconnectAttempts += 1;
  const exponential = SSE_BASE_RETRY_MS * 2 ** Math.min(state.reconnectAttempts, 6);
  const jitter = Math.floor(Math.random() * 350);
  const delay = Math.min(SSE_MAX_RETRY_MS, exponential) + jitter;
  setLivePill("reconnecting");

  state.reconnectTimer = window.setTimeout(() => {
    state.reconnectTimer = null;
    connectEventStream(state.lastEventSeq);
  }, delay);
}

function connectEventStream(afterSeq = 0) {
  closeEventStream();
  if (!state.activeSessionId) {
    return;
  }

  const source = new EventSource(`/api/sessions/${state.activeSessionId}/stream?after=${afterSeq}`);
  state.eventSource = source;

  source.onopen = () => {
    state.reconnectAttempts = 0;
    setLivePill(state.runLocked ? "running" : "idle");
  };

  source.onerror = () => {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
    scheduleStreamReconnect();
  };

  source.onmessage = (event) => {
    if (!event || !event.data) {
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(event.data);
    } catch (_error) {
      return;
    }
    renderEvent(parsed, "append");
    scheduleLoadSessions();
  };
}

function renderWorkspaceNode(node) {
  const item = document.createElement("li");
  const label = document.createElement("span");
  label.className = node.kind === "directory" ? "folder" : "file";
  label.textContent = node.path ? `${node.name} (${node.path})` : node.name;
  item.appendChild(label);

  if (Array.isArray(node.children) && node.children.length > 0) {
    const list = document.createElement("ul");
    for (const child of node.children) {
      list.appendChild(renderWorkspaceNode(child));
    }
    item.appendChild(list);
  }

  return item;
}

async function loadWorkspaceTree() {
  try {
    const payload = await apiGet("/api/workspace/tree?depth=2");
    if (!elements.workspaceTree) {
      return;
    }
    elements.workspaceTree.replaceChildren();
    const children = Array.isArray(payload.tree && payload.tree.children) ? payload.tree.children : [];
    if (!payload.tree || payload.tree.kind !== "directory") {
      renderEmptyState(elements.workspaceTree, "Workspace unavailable", "Refresh the tree to try again.");
      return;
    }
    if (payload.tree && payload.tree.kind === "directory" && children.length === 0) {
      renderEmptyState(elements.workspaceTree, "Workspace is empty");
      return;
    }
    const list = document.createElement("ul");
    list.appendChild(renderWorkspaceNode(payload.tree));
    elements.workspaceTree.appendChild(list);
  } catch (error) {
    console.error(error);
    if (elements.workspaceTree) {
      elements.workspaceTree.replaceChildren();
      renderEmptyState(elements.workspaceTree, "Workspace unavailable", "Refresh the tree to try again.");
    }
  }
}

async function loadRecentFiles() {
  try {
    const payload = await apiGet("/api/workspace/recent?limit=20");
    if (!elements.recentFiles) {
      return;
    }
    elements.recentFiles.replaceChildren();
    const files = Array.isArray(payload.files) ? payload.files : [];
    if (files.length === 0) {
      const item = document.createElement("li");
      item.className = "empty-list-item";
      item.textContent = "Workspace is empty";
      elements.recentFiles.appendChild(item);
      return;
    }
    for (const file of files) {
      const item = document.createElement("li");
      const path = document.createElement("span");
      path.className = "recent-file-path";
      path.textContent = file.path || file.name || "(unknown)";

      const meta = document.createElement("span");
      meta.className = "recent-file-meta";
      const size = typeof file.size === "number" ? `${file.size} bytes` : "size n/a";
      meta.textContent = `${size} - ${formatTimestamp(file.modified_at)}`;

      item.appendChild(path);
      item.appendChild(meta);
      elements.recentFiles.appendChild(item);
    }
  } catch (error) {
    console.error(error);
    if (elements.recentFiles) {
      elements.recentFiles.replaceChildren();
      const item = document.createElement("li");
      item.className = "empty-list-item";
      item.textContent = "Recent files unavailable";
      elements.recentFiles.appendChild(item);
    }
  }
}

async function loadAgentState() {
  if (!state.activeSessionId || !elements.agentState) {
    return;
  }
  try {
    const payload = await apiGet(`/api/sessions/${state.activeSessionId}/state`);
    renderAgentState(payload.state || {});
  } catch (error) {
    renderAgentState({ error: String(error) });
  }
}

async function loadSession(sessionId) {
  const payload = await apiGet(`/api/sessions/${sessionId}?event_limit=${SESSION_EVENT_LIMIT}`);
  return payload.session;
}

async function selectSession(sessionId) {
  closeEventStream();
  state.activeSessionId = sessionId;
  state.activeSession = null;

  clearChatFeed();
  setSessionTitle("Loading session...");
  setRunLock(true);
  setLivePill("loading");

  try {
    const session = await loadSession(sessionId);
    state.activeSession = session;
    setSessionTitle(session.title || "Untitled Session");
    setRunLock(Boolean(session.is_running));
    setLivePill(session.is_running ? "running" : "idle");

    state.lastEventSeq = 0;
    state.oldestEventSeq = null;
    state.hasOlderEvents = Boolean(session.has_older_events);
    updateHistoryButton();

    const events = Array.isArray(session.events) ? session.events : [];
    if (events.length > 0) {
      state.oldestEventSeq = Number(events[0].seq) || null;
    }

    for (const event of events) {
      renderEvent(event, "append");
    }

    if (events.length === 0) {
      setLivePill(session.is_running ? "running" : "idle");
    }

    renderSessions();
    connectEventStream(state.lastEventSeq);
    await loadAgentState();
    setMobilePanel("run");
  } catch (error) {
    console.error(error);
    setSessionTitle("Failed to load session");
    setRunLock(false);
    setLivePill("idle");
  }
}

async function loadOlderEvents() {
  if (!state.activeSessionId || !state.hasOlderEvents || state.loadingOlderEvents || !state.oldestEventSeq) {
    return;
  }

  const beforeSeq = state.oldestEventSeq;
  state.loadingOlderEvents = true;
  updateHistoryButton();

  const feed = elements.chatFeed;
  const previousHeight = feed ? feed.scrollHeight : 0;
  const previousTop = feed ? feed.scrollTop : 0;

  try {
    const payload = await apiGet(
      `/api/sessions/${state.activeSessionId}/events?before=${beforeSeq}&limit=${OLDER_EVENTS_LIMIT}`,
    );
    const events = Array.isArray(payload.events) ? payload.events : [];
    for (const event of events) {
      renderEvent(event, "prepend");
    }

    if (events.length > 0) {
      state.oldestEventSeq = Number(events[0].seq) || state.oldestEventSeq;
    }
    state.hasOlderEvents = Boolean(payload.has_older_events);
  } catch (error) {
    console.error(error);
  } finally {
    state.loadingOlderEvents = false;
    updateHistoryButton();
    if (feed) {
      const nextHeight = feed.scrollHeight;
      feed.scrollTop = previousTop + (nextHeight - previousHeight);
    }
  }
}

function collectRunConfig() {
  const provider = elements.providerSelect ? elements.providerSelect.value : "hf_inference";
  return {
    provider,
    model_id: elements.modelIdInput ? elements.modelIdInput.value.trim() : "",
    api_base: elements.apiBaseInput ? elements.apiBaseInput.value.trim() : "",
    api_key: elements.apiKeyInput ? elements.apiKeyInput.value.trim() : "",
    hf_provider: elements.hfProviderInput ? elements.hfProviderInput.value.trim() : "",
    max_steps: elements.maxStepsInput ? Number(elements.maxStepsInput.value) : 12,
    planning_interval: elements.planningIntervalInput ? elements.planningIntervalInput.value : "",
    additional_imports: elements.importsInput ? elements.importsInput.value : "",
  };
}

async function submitRun(event) {
  event.preventDefault();
  if (!state.activeSessionId || state.runLocked) {
    return;
  }

  const prompt = elements.promptInput ? elements.promptInput.value.trim() : "";
  if (!prompt) {
    return;
  }

  setRunLock(true);
  setLivePill("running");

  try {
    await apiPost(`/api/sessions/${state.activeSessionId}/runs`, {
      prompt,
      config: collectRunConfig(),
    });
    if (elements.promptInput) {
      elements.promptInput.value = "";
    }
    scheduleLoadSessions();
  } catch (error) {
    console.error(error);
    renderRunFailed({ payload: { error: String(error.message || error) } }, "append");
    await loadSessions(true);
    if (state.activeSessionId) {
      await selectSession(state.activeSessionId);
    }
  }
}

async function createSession() {
  try {
    const payload = await apiPost("/api/sessions", {});
    await loadSessions(true);
    if (payload.session && payload.session.id) {
      await selectSession(payload.session.id);
    }
  } catch (error) {
    console.error(error);
  }
}

function handleProviderChanged() {
  if (!elements.providerSelect || !elements.modelIdInput) {
    return;
  }
  const provider = elements.providerSelect.value;
  if (!Object.prototype.hasOwnProperty.call(DEFAULT_MODEL_BY_PROVIDER, provider)) {
    return;
  }

  const current = elements.modelIdInput.value.trim();
  const knownDefaults = Object.values(DEFAULT_MODEL_BY_PROVIDER);
  if (!current || knownDefaults.includes(current)) {
    elements.modelIdInput.value = DEFAULT_MODEL_BY_PROVIDER[provider];
  }
}

function bindEvents() {
  if (elements.themeSelect) {
    elements.themeSelect.addEventListener("change", () => {
      applyTheme(elements.themeSelect.value);
    });
  }

  for (const button of elements.mobileTabs) {
    button.addEventListener("click", () => {
      setMobilePanel(button.dataset.target || "run");
    });
  }

  if (elements.newSessionButton) {
    elements.newSessionButton.addEventListener("click", () => {
      void createSession();
    });
  }

  if (elements.runForm) {
    elements.runForm.addEventListener("submit", (event) => {
      void submitRun(event);
    });
  }

  if (elements.providerSelect) {
    elements.providerSelect.addEventListener("change", handleProviderChanged);
  }

  if (elements.refreshTreeButton) {
    elements.refreshTreeButton.addEventListener("click", () => {
      void loadWorkspaceTree();
      void loadRecentFiles();
    });
  }

  if (elements.refreshStateButton) {
    elements.refreshStateButton.addEventListener("click", () => {
      void loadAgentState();
    });
  }

  window.addEventListener("beforeunload", () => {
    closeEventStream();
  });
}

async function bootstrap() {
  loadThemeFromStorage();
  setMobilePanel(elements.body.dataset.mobilePanel || "run");
  bindEvents();
  ensureHistoryControls();

  await loadSessions(true);
  await loadWorkspaceTree();
  await loadRecentFiles();

  if (!state.activeSessionId && state.sessions.length > 0) {
    await selectSession(state.sessions[0].id);
  } else if (!state.activeSessionId) {
    setSessionTitle("No run selected");
    renderNoRunSelected();
    renderAgentState({});
  }

  setRunLock(Boolean(state.activeSession && state.activeSession.is_running));
  setLivePill(state.runLocked ? "running" : "idle");
}

void bootstrap();

