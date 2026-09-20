// No provider-specific behavior or model-provided HTML belongs in this component.
export async function* events(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let name = "message";
  let data = [];
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      let end;
      while ((end = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, end).replace(/\r$/, "");
        buffer = buffer.slice(end + 1);
        if (!line) {
          if (data.length) yield {name, data: JSON.parse(data.join("\n"))};
          name = "message";
          data = [];
        } else if (line.startsWith("event:")) {
          name = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          data.push(line.slice(5).replace(/^ /, ""));
        }
      }
      if (buffer.length > 300000 || data.join("").length > 300000) {
        throw new Error("The overview response was too large.");
      }
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function validURL(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password;
  } catch { return false; }
}

export function renderCitations(element, text, sources) {
  const fragment = document.createDocumentFragment();
  const pattern = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    fragment.append(document.createTextNode(text.slice(offset, match.index)));
    const ids = match[1].split(",").map(Number);
    const selected = ids.map(id => sources.find(source => source.id === id));
    if (selected.every(source => source && validURL(source.url))) {
      selected.forEach(source => {
        const link = document.createElement("a");
        link.href = source.url;
        link.textContent = `[${source.id}]`;
        link.title = source.title;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        fragment.append(link);
      });
    } else {
      fragment.append(document.createTextNode(match[0]));
    }
    offset = match.index + match[0].length;
  }
  fragment.append(document.createTextNode(text.slice(offset)));
  element.replaceChildren(fragment);
}

function sourceList(sources) {
  const details = document.createElement("details");
  details.className = "ai-sources";
  const summary = document.createElement("summary");
  summary.textContent = `${sources.length} sources · Search snippets`;
  const list = document.createElement("ol");
  for (const source of sources) {
    if (!validURL(source.url)) continue;
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = source.url;
    link.textContent = source.title;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const host = document.createElement("small");
    host.textContent = new URL(source.url).hostname;
    item.append(link, host);
    list.append(item);
  }
  details.append(summary, list);
  return details;
}

function mount(panel) {
  if (panel.dataset.mounted) return;
  panel.dataset.mounted = "true";
  let token = panel.dataset.token;
  const initialToken = token;
  delete panel.dataset.token;
  let controller;
  let pendingQuestion;
  let failedTurn;
  let canFollowUp = false;
  const status = panel.querySelector(".ai-status");
  const turns = panel.querySelector(".ai-turns");
  const stop = panel.querySelector(".ai-stop");
  const retry = panel.querySelector(".ai-retry");
  const form = panel.querySelector(".ai-follow-up");
  const input = form.querySelector("input");
  const submit = form.querySelector("button");
  const collapse = panel.querySelector(".ai-collapse");
  const settingsToggle = panel.querySelector(".ai-settings-toggle");
  const settings = panel.querySelector(".ai-model-settings");
  const picker = panel.querySelector(".ai-model");
  const reloadModels = panel.querySelector(".ai-refresh-models");
  const modelStatus = panel.querySelector(".ai-model-status");
  let choices = [];
  let selected = {profile: panel.dataset.profile, model: panel.dataset.model};
  let loadingModels = false;
  let switchingModel = false;
  const selectionKey = "searxng-ai-overview-model";

  async function modelRequest(endpoint, body) {
    const response = await fetch(endpoint, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: initialToken, ...body}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "Could not load model settings.");
    return data;
  }

  async function loadModels() {
    loadingModels = true;
    picker.disabled = true;
    reloadModels.disabled = true;
    modelStatus.textContent = "Loading models…";
    try {
      const result = await modelRequest(panel.dataset.modelsEndpoint, {});
      choices = result.choices;
      picker.replaceChildren();
      for (const [index, choice] of choices.entries()) {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = `${choice.profile} / ${choice.model}${choice.available ? "" : " (not configured)"}`;
        option.disabled = !choice.available;
        option.selected = choice.profile === selected.profile && choice.model === selected.model;
        picker.append(option);
      }
      modelStatus.textContent = result.warnings.join(" ");
    } catch (error) {
      modelStatus.textContent = `${error.message} Using the current model.`;
    } finally {
      loadingModels = false;
      picker.disabled = Boolean(controller) || !choices.length;
      reloadModels.disabled = Boolean(controller);
    }
  }

  async function chooseModel(choice) {
    switchingModel = true;
    picker.disabled = true;
    input.disabled = true;
    submit.disabled = true;
    try {
      const result = await modelRequest(panel.dataset.selectEndpoint, {profile: choice.profile, model: choice.model});
      token = result.token;
      selected = {profile: choice.profile, model: choice.model};
      try { localStorage.setItem(selectionKey, JSON.stringify(selected)); } catch { /* Storage is optional. */ }
      turns.replaceChildren();
      failedTurn = null;
      canFollowUp = false;
      form.hidden = true;
      input.value = "";
    } finally {
      switchingModel = false;
      input.disabled = false;
      submit.disabled = false;
    }
  }

  if (picker) {
    settingsToggle.addEventListener("click", () => {
      settings.hidden = !settings.hidden;
      settingsToggle.setAttribute("aria-expanded", String(!settings.hidden));
      if (!settings.hidden && panel.querySelector(".ai-content").hidden) collapse.click();
    });
    reloadModels.addEventListener("click", loadModels);
    picker.addEventListener("change", async () => {
      if (controller || switchingModel || loadingModels) return;
      const choice = choices[Number(picker.value)];
      if (!choice?.available) return;
      picker.disabled = true;
      reloadModels.disabled = true;
      try {
        await chooseModel(choice);
        settings.hidden = true;
        settingsToggle.setAttribute("aria-expanded", "false");
        await run();
      } catch (error) {
        modelStatus.textContent = error.message;
        picker.value = String(choices.findIndex(c => c.profile === selected.profile && c.model === selected.model));
      } finally {
        picker.disabled = false;
        reloadModels.disabled = false;
      }
    });
  }
  collapse.addEventListener("click", () => {
    const content = panel.querySelector(".ai-content");
    content.hidden = !content.hidden;
    collapse.setAttribute("aria-expanded", String(!content.hidden));
    collapse.textContent = content.hidden ? "Expand" : "Collapse";
  });
  stop.addEventListener("click", () => controller?.abort());
  window.addEventListener("pagehide", () => controller?.abort());
  retry.addEventListener("click", () => run(pendingQuestion));
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!controller && !switchingModel && input.value.trim()) run(input.value.trim());
  });

  async function run(question) {
    if (controller) return;
    failedTurn?.remove();
    failedTurn = null;
    pendingQuestion = question;
    controller = new AbortController();
    if (picker) { picker.disabled = true; reloadModels.disabled = true; }
    stop.hidden = false;
    retry.hidden = true;
    input.disabled = true;
    submit.disabled = true;
    status.textContent = "Connecting…";
    const turn = document.createElement("article");
    if (question) {
      const heading = document.createElement("h3");
      heading.className = "ai-question";
      heading.textContent = question;
      turn.append(heading);
    }
    const answer = document.createElement("div");
    answer.className = "ai-answer";
    const turnStatus = document.createElement("p");
    turnStatus.className = "ai-turn-status";
    turnStatus.hidden = true;
    turn.append(answer, turnStatus);
    turns.append(turn);
    let text = "";
    let sources = [];
    let complete = false;
    try {
      const response = await fetch(panel.dataset.endpoint, {
        method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: {"Content-Type": "application/json", "Accept": "text/event-stream"},
        body: JSON.stringify({token, ...(question ? {question} : {})}),
      });
      if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
        throw new Error("Could not start the overview. Try again.");
      }
      for await (const event of events(response.body)) {
        if (event.name === "status") status.textContent = event.data.message;
        if (event.name === "sources") {
          sources = event.data.sources;
          turn.append(sourceList(sources));
        }
        if (event.name === "text_delta") {
          text += event.data.text;
          renderCitations(answer, text, sources);
        }
        if (event.name === "error") throw new Error(event.data.message);
        if (event.name === "done") {
          token = event.data.token;
          canFollowUp = event.data.can_follow_up;
          complete = true;
          break;
        }
      }
      if (!complete) throw new Error("The connection ended before the answer was complete.");
      status.textContent = canFollowUp ? "Check the sources for details." : "Start a new search to continue.";
      input.value = "";
    } catch (error) {
      const message = error.name === "AbortError" ? "Stopped. This answer is incomplete." : error.message;
      status.textContent = message;
      turnStatus.textContent = text ? "Incomplete answer" : message;
      turnStatus.hidden = false;
      failedTurn = turn;
      retry.hidden = false;
    } finally {
      controller = null;
      stop.hidden = true;
      form.hidden = !canFollowUp;
      input.disabled = false;
      submit.disabled = false;
      if (picker) {
        picker.disabled = loadingModels || !choices.length;
        reloadModels.disabled = loadingModels;
      }
    }
  }
  async function start() {
    if (picker) {
      await loadModels();
      try {
        const saved = JSON.parse(localStorage.getItem(selectionKey) || "null");
        const choice = choices.find(c => c.available && c.profile === saved?.profile && c.model === saved?.model);
        if (choice && (choice.profile !== selected.profile || choice.model !== selected.model)) {
          await chooseModel(choice);
          picker.value = String(choices.indexOf(choice));
        }
      } catch { /* Use the configured default if saved preferences are unavailable. */ }
    }
    await run();
  }
  start();
}

document.querySelectorAll(".ai-overview").forEach(mount);
