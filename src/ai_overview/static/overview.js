import {copyText} from "./clipboard.js";
import {Conversation} from "./conversation.js";
import {renderMarkdown} from "./markdown.js";
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
  const provenance = document.createElement("p");
  provenance.className = "ai-provenance";
  provenance.textContent = "Based on search snippets";
  details.append(summary, provenance, list);
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
  const rawAnswers = new WeakMap();
  const stop = panel.querySelector(".ai-stop");
  const retry = panel.querySelector(".ai-retry");
  const cancelWait = panel.querySelector(".ai-cancel-wait");
  const form = panel.querySelector(".ai-follow-up");
  const input = form.querySelector("input");
  const submit = form.querySelector("button");
  const collapse = panel.querySelector(".ai-collapse");
  const more = panel.querySelector(".ai-more");
  const moreRow = panel.querySelector(".ai-more-row");
  const copy = panel.querySelector(".ai-copy");
  const copyStatus = panel.querySelector(".ai-copy-status");
  let expanded = false;
  let disclosureAnimation;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  function cancelDisclosureAnimation() {
    disclosureAnimation?.cancel();
    disclosureAnimation = null;
  }
  function expand(value, animate = false) {
    const before = turns.getBoundingClientRect().height;
    cancelDisclosureAnimation();
    expanded = value;
    if (!value) turns.querySelectorAll(".ai-answer-revealed").forEach(answer => answer.classList.remove("ai-answer-revealed"));
    panel.dataset.expanded = String(value);
    updateDisclosure();
    const after = turns.getBoundingClientRect().height;
    if (animate && !reducedMotion.matches && Math.abs(after - before) > 1) {
      disclosureAnimation = turns.animate([
        {height: `${before}px`, overflow: "clip"},
        {height: `${after}px`, overflow: "clip"},
      ], {duration: 260, easing: "cubic-bezier(0.2, 0, 0, 1)"});
      disclosureAnimation.onfinish = () => {
        disclosureAnimation = null;
        if (!value && more.getBoundingClientRect().top < 0) more.scrollIntoView({block: "nearest"});
      };
    } else if (animate && !value && more.getBoundingClientRect().top < 0) {
      more.scrollIntoView({block: "nearest"});
    }
  }
  function updateDisclosure() {
    const answer = turns.querySelector(".ai-answer");
    const clipped = answer && (answer.querySelector(".ai-code-block") || answer.scrollHeight > parseFloat(getComputedStyle(answer).lineHeight) * 4 + 1);
    const hasConversation = turns.childElementCount > 1;
    moreRow.hidden = !clipped && !hasConversation;
    more.setAttribute("aria-expanded", String(expanded));
    more.querySelector("span").textContent = expanded ? "Show less" : hasConversation ? "Show conversation" : "Show full answer";
    // Follow-up entry is temporarily hidden; keep the conversation support intact.
    form.hidden = true;
  }
  new ResizeObserver(() => {
    cancelDisclosureAnimation();
    updateDisclosure();
  }).observe(panel.querySelector(".ai-overview-header"));
  reducedMotion.addEventListener("change", cancelDisclosureAnimation);
  more.addEventListener("click", () => expand(!expanded, true));
  copy.addEventListener("click", async () => {
    const text = [...turns.querySelectorAll("article")].map(turn => {
      const answer = turn.querySelector(".ai-answer");
      const question = turn.querySelector(".ai-question")?.textContent;
      return [question, rawAnswers.get(answer) || ""].filter(Boolean).join("\n\n");
    }).join("\n\n");
    try {
      await copyText(text);
      copyStatus.textContent = "Answer copied.";
    } catch {
      copyStatus.textContent = "Could not copy. Select the answer text to copy it.";
      status.textContent = copyStatus.textContent;
      status.hidden = false;
    }
  });
  const optionsToggle = panel.querySelector(".ai-options-toggle");
  const options = panel.querySelector(".ai-options");
  const regenerate = panel.querySelector(".ai-regenerate");
  const preview = panel.querySelector(".ai-collapsed-preview");
  const applyModel = panel.querySelector(".ai-apply-model");
  const picker = panel.querySelector(".ai-model");
  function resetDraft() {
    if (!picker) return;
    const {choices, selected} = conversation.state;
    if (choices.length) picker.value = String(choices.findIndex(c => c.profile === selected.profile && c.model === selected.model));
    updateControls(conversation.state);
  }
  function closeOptions(restoreFocus = false) {
    options.hidden = true;
    optionsToggle.setAttribute("aria-expanded", "false");
    if (restoreFocus) optionsToggle.focus();
  }
  optionsToggle.addEventListener("click", () => {
    if (!options.hidden) return closeOptions(true);
    resetDraft();
    options.hidden = false;
    optionsToggle.setAttribute("aria-expanded", "true");
    options.querySelector(".ai-settings-close").focus();
  });
  options.querySelector(".ai-settings-close").addEventListener("click", () => closeOptions(true));
  document.addEventListener("focusin", event => {
    if (!options.hidden && !options.contains(event.target) && !optionsToggle.contains(event.target)) closeOptions();
  });
  document.addEventListener("click", event => {
    if (!options.hidden && !options.contains(event.target) && !optionsToggle.contains(event.target)) {
      closeOptions(options.contains(document.activeElement));
    }
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !options.hidden) {
      event.preventDefault();
      event.stopPropagation();
      closeOptions(true);
    }
  }, true);
  panel.addEventListener("keydown", event => {
    // Keep the host's global Escape shortcut from moving focus to search.
    if (event.key === "Escape") event.stopPropagation();
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
    const waiting = state.phase === "waiting";
    const cancelHadFocus = document.activeElement === cancelWait ||
      (document.activeElement === stop && stop.getAttribute("aria-label") === "Cancel waiting");
    panel.dataset.phase = state.phase;
    stop.hidden = state.phase !== "streaming" && !waiting;
    stop.setAttribute("aria-label", waiting ? "Cancel waiting" : "Stop generating");
    stop.title = waiting ? "Cancel waiting" : "Stop generating";
    cancelWait.hidden = !waiting;
    retry.hidden = !state.canRetry;
    retry.disabled = state.busy;
    if (cancelHadFocus && !waiting) {
      if (!stop.hidden) stop.focus();
      else if (!retry.hidden && !retry.disabled) {
        if (panel.querySelector(".ai-content").hidden) collapse.focus();
        else retry.focus();
      }
    }
    input.disabled = state.busy;
    submit.disabled = state.busy;
    regenerate.disabled = state.busy;
    panel.querySelector(".ai-settings-busy").hidden = !state.busy;
    panel.querySelector(".ai-settings-busy").textContent = state.phase === "selecting"
      ? "Restarting overview…" : waiting ? "Cancel waiting to change models or restart."
        : "Wait for the answer to finish, or stop generating to restart.";
    updateDisclosure();
    if (picker) {
      picker.disabled = state.busy || state.loadingModels || !state.choices.length;
      reloadModels.disabled = state.busy || state.loadingModels;
      const choice = picker.value === "" ? undefined : state.choices[Number(picker.value)];
      const changed = choice && (choice.profile !== state.selected.profile || choice.model !== state.selected.model);
      applyModel.hidden = !changed;
      regenerate.hidden = Boolean(changed);
      applyModel.disabled = picker.disabled || !choice?.available || !changed;
      reloadModels.textContent = state.loadingModels ? "Refreshing…" : "Refresh list";
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
    picker.addEventListener("change", () => updateControls(conversation.state));
    reloadModels.addEventListener("click", () => conversation.loadModels());
    applyModel.addEventListener("click", async () => {
      const choice = conversation.state.choices[Number(picker.value)];
      if (applyModel.disabled || !choice?.available) return;
      try {
        await conversation.restart(choice);
      } catch (error) {
        modelStatus.textContent = error.message;
        updateControls(conversation.state);
        if (!options.hidden && document.activeElement === document.body) applyModel.focus();
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
    preview.textContent = rawAnswers.get(turns.querySelector(".ai-answer")) || status.textContent;
    if (!content.hidden) updateDisclosure();
  });
  stop.addEventListener("click", () => conversation.stop());
  cancelWait.addEventListener("click", () => conversation.stop());
  window.addEventListener("pagehide", () => conversation.stop());
  retry.addEventListener("click", () => conversation.retry());
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (input.value.trim()) conversation.run(input.value.trim());
  });

  function beginTurn(question) {
    cancelDisclosureAnimation();
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
    answer.addEventListener("focusin", () => {
      cancelDisclosureAnimation();
      answer.classList.add("ai-answer-revealed");
    });
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
      updateControls(state);
    }
    if (event.name === "reset") {
      turns.replaceChildren();
      activeTurn = failedTurn = null;
      input.value = "";
      if (picker) {
        panel.querySelector(".ai-current-model").textContent = `Current: ${state.selected.model}`;
        picker.value = String(state.choices.findIndex(c => c.profile === state.selected.profile && c.model === state.selected.model));
        try { localStorage.setItem(selectionKey, JSON.stringify(state.selected)); } catch { /* Storage is optional. */ }
        updateControls(state);
      }
      closeOptions();
      showConversation();
    }
    if (event.name === "turn_start") beginTurn(event.data.question);
    if (event.name === "waiting") {
      status.hidden = false;
      const {attempt, maxAttempts, delay} = event.data;
      status.textContent = `AI Summary is busy. Trying again in ${delay / 1000} seconds (${attempt} of ${maxAttempts}).`;
      if (!activeTurn?.text) preview.textContent = status.textContent;
    }
    if (event.name === "status") {
      status.hidden = false;
      status.textContent = event.data.message;
    }
    if (event.name === "sources") {
      activeTurn.sources = event.data.sources;
      const details = sourceList(activeTurn.sources);
      if (details.querySelector("li")) activeTurn.turn.append(details);
    }
    if (event.name === "text_delta") {
      cancelDisclosureAnimation();
      status.hidden = true;
      copy.disabled = false;
      activeTurn.text += event.data.text;
      rawAnswers.set(activeTurn.answer, activeTurn.text);
      renderMarkdown(activeTurn.answer, activeTurn.text, activeTurn.sources, renderCitations, {complete: false});
      updateDisclosure();
      preview.textContent = rawAnswers.get(turns.querySelector(".ai-answer")) || "";
    }
    if (event.name === "turn_done") {
      renderMarkdown(activeTurn.answer, activeTurn.text, activeTurn.sources, renderCitations);
      status.textContent = state.canFollowUp ? "" : "Start a new search to continue.";
      status.hidden = state.canFollowUp;
      input.value = "";
    }
    if (event.name === "turn_error") {
      status.hidden = false;
      status.textContent = event.data.message;
      if (!activeTurn.text) preview.textContent = status.textContent;
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
