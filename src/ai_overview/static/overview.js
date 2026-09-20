import {Conversation} from "./conversation.js";
export {events} from "./conversation.js";

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
  sources = sources.filter(source => validURL(source.url));
  const details = document.createElement("details");
  details.className = "ai-sources";
  const summary = document.createElement("summary");
  summary.textContent = `${sources.length} ${sources.length === 1 ? "source" : "sources"}`;
  const domains = document.createElement("span");
  domains.textContent = [...new Set(sources.map(s => new URL(s.url).hostname.replace(/^www\./, "")))].slice(0, 2).join(", ");
  summary.append(domains);
  const list = document.createElement("ol");
  for (const source of sources) {
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
  const initialToken = panel.dataset.token;
  delete panel.dataset.token;
  let failedTurn;
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
    if (!value) turns.querySelectorAll(".ai-answer-revealed").forEach(answer => answer.classList.remove("ai-answer-revealed"));
    panel.dataset.expanded = String(value);
    more.setAttribute("aria-expanded", String(value));
    more.querySelector("span").textContent = value ? "Less" : "More";
    form.hidden = !conversation.state.canFollowUp || !expanded;
  }
  function updateDisclosure() {
    moreRow.hidden = !turns.querySelector(".ai-answer")?.textContent && !conversation.state.canFollowUp;
  }
  more.addEventListener("click", () => expand(!expanded));
  copy.addEventListener("click", async () => {
    const text = [...turns.querySelectorAll("article")].map(turn => {
      const answer = turn.querySelector(".ai-answer").cloneNode(true);
      answer.querySelectorAll("a[data-source-id]").forEach(link => {
        link.replaceWith(`[${link.dataset.sourceId}]`);
      });
      const question = turn.querySelector(".ai-question")?.textContent;
      return [question, answer.textContent].filter(Boolean).join("\n\n");
    }).join("\n\n");
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
    // Keep the host's global Escape shortcut from moving focus to search.
    if (event.key === "Escape") event.stopPropagation();
    if (event.key === "Escape" && (!options.hidden || (settings && !settings.hidden))) {
      event.preventDefault();
      closeOptions();
      if (settings) { settings.hidden = true; settingsToggle.setAttribute("aria-expanded", "false"); }
      optionsToggle.focus();
    }
  });
  const reloadModels = panel.querySelector(".ai-refresh-models");
  const modelStatus = panel.querySelector(".ai-model-status");
  const selectionKey = "searxng-ai-overview-model";
  let activeTurn;
  const conversation = new Conversation({
    token: initialToken,
    selected: {profile: panel.dataset.profile, model: panel.dataset.model},
    endpoints: {stream: panel.dataset.endpoint, models: picker ? panel.dataset.modelsEndpoint : null, select: picker ? panel.dataset.selectEndpoint : null},
    onEvent: renderEvent,
  });

  function updateControls(state) {
    panel.dataset.loading = String(state.phase === "streaming");
    stop.hidden = state.phase !== "streaming";
    retry.hidden = !state.canRetry;
    retry.disabled = state.busy;
    input.disabled = state.busy;
    submit.disabled = state.busy;
    regenerate.disabled = state.busy || state.loadingModels;
    form.hidden = !state.canFollowUp || !expanded;
    if (picker) {
      picker.disabled = state.busy || state.loadingModels || !state.choices.length;
      reloadModels.disabled = state.busy || state.loadingModels;
      applyModel.disabled = picker.disabled;
    }
  }

  function showConversation() {
    if (panel.querySelector(".ai-content").hidden) collapse.click();
    optionsToggle.focus();
  }

  regenerate.addEventListener("click", async () => {
    closeOptions();
    showConversation();
    try { await conversation.restart(); }
    catch (error) { status.hidden = false; status.textContent = error.message; }
  });

  if (picker) {
    settingsToggle.addEventListener("click", () => {
      settings.hidden = !settings.hidden;
      settingsToggle.setAttribute("aria-expanded", String(!settings.hidden));
      closeOptions();
      if (!settings.hidden && !picker.disabled) picker.focus();
    });
    reloadModels.addEventListener("click", () => conversation.loadModels());
    applyModel.addEventListener("click", async () => {
      const choice = conversation.state.choices[Number(picker.value)];
      if (!choice?.available) return;
      try {
        await conversation.restart(choice);
      } catch (error) {
        modelStatus.textContent = error.message;
        const {choices, selected} = conversation.state;
        picker.value = String(choices.findIndex(c => c.profile === selected.profile && c.model === selected.model));
      }
    });
  }
  collapse.addEventListener("click", () => {
    const content = panel.querySelector(".ai-content");
    content.hidden = !content.hidden;
    collapse.setAttribute("aria-expanded", String(!content.hidden));
    collapse.setAttribute("aria-label", content.hidden ? "Expand overview" : "Collapse overview");
    collapse.title = content.hidden ? "Expand overview" : "Collapse overview";
    preview.hidden = !content.hidden;
    preview.textContent = turns.querySelector(".ai-answer")?.textContent || status.textContent;
    if (!content.hidden) updateDisclosure();
  });
  stop.addEventListener("click", () => conversation.stop());
  window.addEventListener("pagehide", () => conversation.stop());
  retry.addEventListener("click", () => conversation.retry());
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (input.value.trim()) conversation.run(input.value.trim());
  });

  function beginTurn(question) {
    failedTurn?.remove();
    failedTurn = null;
    if (!question && !turns.childElementCount) {
      expand(false);
      moreRow.hidden = true;
      copy.disabled = true;
    }
    if (question) expand(true);
    copyStatus.textContent = "";
    status.hidden = false;
    status.textContent = "Reading search results…";
    const turn = document.createElement("article");
    if (question) {
      const heading = document.createElement("h3");
      heading.className = "ai-question";
      heading.textContent = question;
      turn.append(heading);
    }
    const answer = document.createElement("div");
    answer.className = "ai-answer";
    answer.addEventListener("focusin", () => answer.classList.add("ai-answer-revealed"));
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
      details.open = true;
      item.focus();
    });
    turns.append(turn);
    activeTurn = {turn, answer, turnStatus, text: "", sources: [], question};
  }

  function renderEvent(event, state) {
    updateControls(state);
    if (event.name === "models_loading") modelStatus.textContent = "Loading models…";
    if (event.name === "models_error") modelStatus.textContent = event.data.message;
    if (event.name === "models") {
      picker.replaceChildren();
      for (const [index, choice] of state.choices.entries()) {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = `${choice.profile} / ${choice.model}${choice.available ? "" : " (not configured)"}`;
        option.disabled = !choice.available;
        option.selected = choice.profile === state.selected.profile && choice.model === state.selected.model;
        picker.append(option);
      }
      modelStatus.textContent = event.data.warnings.join(" ");
    }
    if (event.name === "reset") {
      turns.replaceChildren();
      activeTurn = failedTurn = null;
      input.value = "";
      if (picker) {
        panel.querySelector(".ai-current-model").textContent = `Current model: ${state.selected.model}`;
        picker.value = String(state.choices.findIndex(c => c.profile === state.selected.profile && c.model === state.selected.model));
        try { localStorage.setItem(selectionKey, JSON.stringify(state.selected)); } catch { /* Storage is optional. */ }
        settings.hidden = true;
        settingsToggle.setAttribute("aria-expanded", "false");
      }
      showConversation();
    }
    if (event.name === "turn_start") beginTurn(event.data.question);
    if (event.name === "status") status.textContent = event.data.message;
    if (event.name === "sources") {
      activeTurn.sources = event.data.sources;
      const details = sourceList(activeTurn.sources);
      if (details.querySelector("li")) activeTurn.turn.append(details);
    }
    if (event.name === "text_delta") {
      status.hidden = true;
      copy.disabled = false;
      activeTurn.text += event.data.text;
      renderCitations(activeTurn.answer, activeTurn.text, activeTurn.sources);
      updateDisclosure();
      preview.textContent = turns.querySelector(".ai-answer")?.textContent || "";
    }
    if (event.name === "turn_done") {
      status.textContent = state.canFollowUp ? "" : "Start a new search to continue.";
      status.hidden = state.canFollowUp;
      input.value = "";
    }
    if (event.name === "turn_error") {
      status.hidden = false;
      status.textContent = event.data.message;
      activeTurn.turnStatus.textContent = activeTurn.text ? "Incomplete answer" : event.data.message;
      activeTurn.turnStatus.hidden = !activeTurn.text;
      failedTurn = activeTurn.turn;
    }
    if (event.name === "state" && !state.busy && activeTurn) {
      updateDisclosure();
      if (activeTurn.question && !form.hidden && (document.activeElement === document.body || form.contains(document.activeElement))) input.focus();
    }
  }

  let saved;
  try { saved = JSON.parse(localStorage.getItem(selectionKey) || "null"); } catch { /* Storage is optional. */ }
  conversation.start(saved).catch(error => {
    if (error.name !== "AbortError") { status.hidden = false; status.textContent = error.message; }
  });
}

document.querySelectorAll(".ai-overview").forEach(mount);
