// AgentForge Local AI - browser code for the local web interface.
// Everything from the server is inserted with textContent (never innerHTML), so model
// output can never run as code in the page.
"use strict";

const $ = (id) => document.getElementById(id);
const state = { tools: [], busy: false };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  try {
    const response = await fetch(path, options);
    const data = await response.json();
    return { status: response.status, data };
  } catch (error) {
    return { status: 0, data: { error: "The AgentForge server is not responding. Is `agentforge --web` still running?" } };
  }
}

// ---- Runtime status ------------------------------------------------------------------

function setPill(stateName, text) {
  $("runtime-pill").dataset.state = stateName;
  $("runtime-text").textContent = text;
}

function showBanner(text) {
  const banner = $("error-banner");
  banner.textContent = text;
  banner.classList.toggle("hidden", !text);
}

async function loadStatus() {
  setPill("checking", "Checking local runtime…");
  const { status, data } = await api("/api/status");
  if (status !== 200) {
    setPill("offline", "AgentForge server unavailable");
    showBanner(data.error);
    return;
  }
  $("version").textContent = "v" + data.app.version;
  $("ollama-url").textContent = data.ollama_url;
  $("input").maxLength = data.max_input_chars;

  const runtime = data.runtime || {};
  const details = $("runtime-details");
  details.replaceChildren();
  const rows = [
    ["Model", data.model],
    ["Ollama", runtime.reachable ? "reachable, v" + runtime.server_version : "not reachable"],
    ["Downloaded", runtime.model_available ? "yes" : "no / unknown"],
    ["Tools", runtime.capabilities ? (runtime.capabilities.includes("tools") ? "supported" : "not supported") : "unknown"],
    ["Thinking", data.think ? "on" : "off"],
    ["Max steps", String(data.max_iterations)],
  ];
  for (const [key, value] of rows) {
    details.append(el("dt", "", key), el("dd", "", value));
  }

  const problems = $("runtime-problems");
  problems.replaceChildren();
  for (const problem of runtime.problems || []) problems.append(el("li", "", problem));
  for (const warning of runtime.warnings || []) problems.append(el("li", "warn", warning));

  if (runtime.ok) {
    setPill("ready", data.model + " · ready");
    showBanner("");
  } else if (runtime.reachable) {
    setPill("warning", data.model + " · needs attention");
    showBanner("The local model is not ready: " + (runtime.problems || []).join(" "));
  } else {
    setPill("offline", "Ollama offline");
    showBanner("Chat needs Ollama running on this computer. Direct tools and notes still work.");
  }
  loadModels(runtime.reachable);
}

async function loadModels(reachable) {
  const select = $("model-select");
  select.replaceChildren();
  if (!reachable) {
    select.append(el("option", "", "Ollama not reachable"));
    select.disabled = true;
    return;
  }
  const { status, data } = await api("/api/models");
  const models = status === 200 ? data.models : [];
  if (!models.length) {
    select.append(el("option", "", "No local models found"));
    select.disabled = true;
    return;
  }
  for (const name of models) {
    const option = el("option", "", name);
    option.value = name;
    option.selected = name === data.current;
    select.append(option);
  }
  if (!models.includes(data.current)) {
    const option = el("option", "", data.current + " (not downloaded)");
    option.value = data.current;
    option.selected = true;
    select.prepend(option);
  }
  select.disabled = false;
}

async function selectModel() {
  const name = $("model-select").value;
  const { status, data } = await api("/api/model", { model: name });
  if (status === 200) {
    clearConversation();
    addMessage("system", "Switched to " + data.model + ". New conversation started.");
  } else {
    addError(data);
  }
  loadStatus();
}

// ---- Conversation --------------------------------------------------------------------

function hideEmptyState() {
  $("empty-state").classList.add("hidden");
}

function clearConversation() {
  for (const node of [...$("messages").children]) {
    if (node.id !== "empty-state") node.remove();
  }
  $("empty-state").classList.remove("hidden");
}

function addMessage(kind, text) {
  hideEmptyState();
  const node = el("div", "msg " + kind, text);
  $("messages").append(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function addError(data) {
  const node = addMessage("error", data.error || "Something went wrong.");
  if (data.hint) node.append(el("span", "hint", data.hint));
  return node;
}

function renderSteps(container, steps) {
  if (!steps.length) return;
  const details = el("details", "steps");
  details.open = true;
  details.append(el("summary", "", "Tool steps (" + steps.length + ")"));
  for (const step of steps) {
    const box = el("div", "step" + (step.ok ? "" : " failed"));
    const label = step.repeated ? "repeated · not run" : step.skipped ? "skipped" : step.ok ? "ok" : "rejected / failed";
    box.append(el("span", "badge", label));
    box.append(el("code", "", step.tool + "(" + JSON.stringify(step.arguments ?? {}) + ")"));
    box.append(el("div", "out", "→ " + step.output));
    details.append(box);
  }
  container.append(details);
}

async function send(text) {
  const message = text.trim();
  if (!message || state.busy) return;
  state.busy = true;
  $("send").disabled = true;
  $("input").value = "";
  addMessage("user", message);

  const pending = addMessage("assistant pending", "Working locally…");
  const started = Date.now();
  const timer = setInterval(() => {
    pending.textContent = "Working locally… " + Math.round((Date.now() - started) / 1000) + "s";
  }, 1000);

  const { status, data } = await api("/api/chat", { message });
  clearInterval(timer);
  pending.remove();

  if (status === 200) {
    const node = addMessage("assistant", data.answer);
    if (data.stop_reason !== "final_answer") {
      node.prepend(el("span", "badge stopped", "stopped: " + data.stop_reason.replaceAll("_", " ")));
    }
    renderSteps(node, data.steps);
    node.append(el("span", "meta", data.iterations + " model call(s) · " + ((Date.now() - started) / 1000).toFixed(1) + "s"));
    if (data.steps.some((s) => s.tool === "save_note" && s.ok)) loadNotes();
  } else {
    addError(data);
    if (status === 503) loadStatus();
  }
  state.busy = false;
  $("send").disabled = false;
  $("input").focus();
}

// ---- Direct tools --------------------------------------------------------------------

async function loadTools() {
  const { status, data } = await api("/api/tools");
  if (status !== 200) return;
  state.tools = data.tools;
  const select = $("tool-select");
  select.replaceChildren();
  for (const tool of data.tools) {
    const option = el("option", "", tool.name);
    option.value = tool.name;
    select.append(option);
  }
  renderToolFields();
}

function renderToolFields() {
  const tool = state.tools.find((t) => t.name === $("tool-select").value);
  const fields = $("tool-fields");
  fields.replaceChildren();
  if (!tool) return;
  fields.append(el("p", "hint", tool.description));
  for (const param of tool.parameters) {
    const label = el("label", "field", param.name);
    const long = param.name === "content" || param.name === "text";
    const input = el(long ? "textarea" : "input");
    if (long) input.rows = 3;
    input.dataset.param = param.name;
    input.placeholder = param.description;
    input.maxLength = param.max_length;
    label.append(input);
    fields.append(label);
  }
}

async function runTool() {
  const name = $("tool-select").value;
  const args = {};
  for (const input of $("tool-fields").querySelectorAll("[data-param]")) {
    if (input.value !== "") args[input.dataset.param] = input.value;
  }
  const { data } = await api("/api/tool", { tool: name, arguments: args });
  const output = $("tool-output");
  output.textContent = data.output ?? data.error;
  output.classList.toggle("failed", !data.ok);
  output.classList.remove("hidden");
  if (name === "save_note" && data.ok) loadNotes();
}

// ---- Notes ---------------------------------------------------------------------------

async function loadNotes() {
  const { data } = await api("/api/notes");
  const list = $("notes-list");
  list.replaceChildren();
  if (!data.ok) {
    list.append(el("li", "empty-note", data.message || data.error));
    return;
  }
  if (!data.notes.length) {
    list.append(el("li", "empty-note", "No notes yet."));
    return;
  }
  for (const name of data.notes) {
    const item = el("li");
    const button = el("button", "", name);
    button.type = "button";
    button.addEventListener("click", () => showNote(name));
    item.append(button);
    list.append(item);
  }
}

async function showNote(name) {
  const { data } = await api("/api/tool", { tool: "read_note", arguments: { name } });
  const view = $("note-view");
  view.textContent = data.ok ? name + "\n\n" + data.output : data.output;
  view.classList.toggle("failed", !data.ok);
  view.classList.remove("hidden");
}

// ---- Wiring --------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    send($("input").value);
  });
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send($("input").value);
    }
  });
  for (const chip of document.querySelectorAll(".chip")) {
    chip.addEventListener("click", () => send(chip.dataset.prompt));
  }
  $("recheck").addEventListener("click", loadStatus);
  $("reset").addEventListener("click", async () => {
    await api("/api/reset", {});
    clearConversation();
  });
  $("model-select").addEventListener("change", selectModel);
  $("tool-select").addEventListener("change", renderToolFields);
  $("tool-run").addEventListener("click", runTool);
  $("notes-refresh").addEventListener("click", loadNotes);

  loadStatus();
  loadTools();
  loadNotes();
});
