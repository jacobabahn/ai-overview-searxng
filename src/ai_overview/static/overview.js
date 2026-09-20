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
        link.textContent = String(source.id);
        link.dataset.sourceId = String(source.id);
        link.setAttribute("aria-label", `Source ${source.id}: ${source.title}`);
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
  summary.textContent = `${sources.length} sources`;
  const domains = document.createElement("span");
  domains.textContent = [...new Set(sources.filter(s => validURL(s.url)).map(s => new URL(s.url).hostname.replace(/^www\./, "")))].slice(0, 2).join(" · ");
  summary.append(domains);
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
    item.value = source.id;
    item.dataset.sourceId = String(source.id);
    item.tabIndex = -1;
    const snippet = document.createElement("p");
    snippet.textContent = source.snippet || "";
    item.append(link, host, snippet);
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
  const more = panel.querySelector(".ai-more");
  const moreRow = panel.querySelector(".ai-more-row");
  const copy = panel.querySelector(".ai-copy");
  const copyStatus = panel.querySelector(".ai-copy-status");
  let expanded = false;
  function expand(value) {
    expanded = value;
    panel.dataset.expanded = String(value);
    more.setAttribute("aria-expanded", String(value));
    more.textContent = value ? "Less ⌃" : "More ⌄";
    form.hidden = !canFollowUp || !expanded;
  }
  more.addEventListener("click", () => expand(!expanded));
  copy.addEventListener("click", async () => {
    const text = [...turns.querySelectorAll(".ai-answer")].map(answer => answer.textContent).join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      copyStatus.textContent = "Answer copied.";
    } catch {
      copyStatus.textContent = "Could not copy. Select the answer text to copy it.";
      status.textContent = copyStatus.textContent;
      status.hidden = false;
    }
  });
  const settingsToggle = panel.querySelector(".ai-settings-toggle");
  const settings = panel.querySelector(".ai-model-settings");
  const optionsToggle = panel.querySelector(".ai-options-toggle");
  const options = panel.querySelector(".ai-options");
  const regenerate = panel.querySelector(".ai-regenerate");
  const preview = panel.querySelector(".ai-collapsed-preview");
  const applyModel = panel.querySelector(".ai-apply-model");
  const picker = panel.querySelector(".ai-model");
  function closeOptions() {
    options.hidden = true;
    optionsToggle.setAttribute("aria-expanded", "false");
  }
  optionsToggle.addEventListener("click", () => {
    options.hidden = !options.hidden;
    optionsToggle.setAttribute("aria-expanded", String(!options.hidden));
  });
  document.addEventListener("click", event => {
    if (!options.contains(event.target) && !optionsToggle.contains(event.target)) closeOptions();
  });
  panel.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeOptions();
      if (settings) { settings.hidden = true; settingsToggle.setAttribute("aria-expanded", "false"); }
      optionsToggle.focus();
    }
  });
  regenerate.addEventListener("click", async () => {
    if (controller || switchingModel || loadingModels) return;
    closeOptions();
    try {
      if (picker) {
        await chooseModel(selected);
        picker.value = String(choices.findIndex(c => c.profile === selected.profile && c.model === selected.model));
      } else { token = initialToken; turns.replaceChildren(); canFollowUp = false; }
      if (panel.querySelector(".ai-content").hidden) collapse.click();
      optionsToggle.focus();
      await run();
    } catch (error) {
      if (panel.querySelector(".ai-content").hidden) collapse.click();
      status.hidden = false;
      status.textContent = error.message;
    } finally {
      if (picker) picker.disabled = loadingModels || !choices.length;
    }
  });
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
    applyModel.disabled = true;
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
      applyModel.disabled = Boolean(controller) || !choices.length;
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
      panel.querySelector(".ai-current-model").textContent = `Current model: ${choice.model}`;
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
      closeOptions();
      if (!settings.hidden && !picker.disabled) picker.focus();
    });
    reloadModels.addEventListener("click", loadModels);
    applyModel.addEventListener("click", async () => {
      if (controller || switchingModel || loadingModels) return;
      const choice = choices[Number(picker.value)];
      if (!choice?.available) return;
      picker.disabled = true;
      reloadModels.disabled = true;
      applyModel.disabled = true;
      try {
        await chooseModel(choice);
        settings.hidden = true;
        settingsToggle.setAttribute("aria-expanded", "false");
        optionsToggle.focus();
        if (panel.querySelector(".ai-content").hidden) collapse.click();
        await run();
      } catch (error) {
        modelStatus.textContent = error.message;
        picker.value = String(choices.findIndex(c => c.profile === selected.profile && c.model === selected.model));
      } finally {
        picker.disabled = false;
        reloadModels.disabled = false;
        applyModel.disabled = false;
      }
    });
  }
  collapse.addEventListener("click", () => {
    const content = panel.querySelector(".ai-content");
    content.hidden = !content.hidden;
    collapse.setAttribute("aria-expanded", String(!content.hidden));
    collapse.textContent = content.hidden ? "⌄" : "⌃";
    collapse.setAttribute("aria-label", content.hidden ? "Expand overview" : "Collapse overview");
    collapse.title = content.hidden ? "Expand overview" : "Collapse overview";
    preview.hidden = !content.hidden;
    preview.textContent = turns.querySelector(".ai-answer")?.textContent || status.textContent;
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
    if (!question && !turns.childElementCount) {
      expand(false);
      moreRow.hidden = true;
      copy.disabled = true;
    }
    copyStatus.textContent = "";
    controller = new AbortController();
    panel.dataset.loading = "true";
    if (picker) { picker.disabled = true; reloadModels.disabled = true; }
    stop.hidden = false;
    retry.hidden = true;
    input.disabled = true;
    submit.disabled = true;
    status.hidden = false;
    status.textContent = "Reading search results…";
    regenerate.disabled = true;
    if (applyModel) applyModel.disabled = true;
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
    answer.addEventListener("click", event => {
      const link = event.target.closest("a[data-source-id]");
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const details = turn.querySelector(".ai-sources");
      const item = details?.querySelector(`li[data-source-id="${link.dataset.sourceId}"]`);
      if (!item) return;
      event.preventDefault();
      expand(true);
      details.open = true;
      item.focus();
    });
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
          const details = sourceList(sources);
          const pills = document.createElement("div");
          pills.className = "ai-source-pills";
          for (const source of sources.filter(source => validURL(source.url)).slice(0, 3)) {
            const pill = document.createElement("button");
            pill.type = "button";
            pill.textContent = `› ${new URL(source.url).hostname.replace(/^www\./, "")}`;
            pill.title = source.title;
            pill.setAttribute("aria-label", `View source ${source.id}: ${source.title}`);
            pill.addEventListener("click", () => {
              expand(true);
              details.open = true;
              details.querySelector(`li[data-source-id="${source.id}"]`)?.focus();
            });
            pills.append(pill);
          }
          turn.append(pills, details);
        }
        if (event.name === "text_delta") {
          status.hidden = true;
          moreRow.hidden = false;
          copy.disabled = false;
          text += event.data.text;
          renderCitations(answer, text, sources);
          preview.textContent = turns.querySelector(".ai-answer")?.textContent || "";
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
      status.textContent = canFollowUp ? "" : "Start a new search to continue.";
      status.hidden = canFollowUp;
      input.value = "";
    } catch (error) {
      const message = error.name === "AbortError" ? "Stopped. This answer is incomplete." : error.message;
      status.hidden = false;
      status.textContent = message;
      turnStatus.textContent = text ? "Incomplete answer" : message;
      turnStatus.hidden = !text;
      failedTurn = turn;
      retry.hidden = false;
    } finally {
      controller = null;
      panel.dataset.loading = "false";
      regenerate.disabled = false;
      if (applyModel) applyModel.disabled = loadingModels || !choices.length;
      stop.hidden = true;
      form.hidden = !canFollowUp || !expanded;
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
