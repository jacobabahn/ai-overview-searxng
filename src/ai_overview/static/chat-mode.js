// Chat mode: a client-side "Chat" entry in SearXNG's category row that turns the
// results page into a full-width conversation with the AI Summary. It is not a
// server category: the signed continuation lives only in page memory, so a real
// navigation would lose the conversation. Entering pushes a history entry so Back
// exits; nothing is written to the URL, and a reload returns to normal results.
// What gets hidden while chatting is decided in chat-mode.css.

const HISTORY_KEY = "aiOverviewChat";
// Ionicons chatbubble-outline (MIT), in the same icon set and stroke as the host's.
const ICON = '<svg viewBox="0 0 512 512" class="ionicon sxng-icon-set-big" aria-hidden="true"><path d="M87.48 380c1.2-4.38-1.43-10.47-3.94-14.86a42.63 42.63 0 0 0-2.54-3.8 199.81 199.81 0 0 1-33-110C47.64 139.09 140.72 48 255.82 48 356.2 48 440 117.54 459.57 209.85a199 199 0 0 1 4.43 41.64c0 112.41-89.49 204.93-204.59 204.93-18.31 0-43-4.6-56.47-8.37s-26.92-8.77-30.39-10.11a31.14 31.14 0 0 0-11.13-2.07 30.7 30.7 0 0 0-12.08 2.43L81.5 467.23a16.48 16.48 0 0 1-4.78 1.26 9.81 9.81 0 0 1-9.75-9.85 16.17 16.17 0 0 1 .6-3.33Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-miterlimit="10" stroke-width="32px"/></svg>';

const SEND_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>';
const MAX_NOTES = 4;
const inactive = {update() {}, active: () => false};

// `expand(value)` sets the panel's disclosure; `focusComposer()` moves focus to
// the follow-up composer when it is shown, without scrolling to it. `suggest()`
// resolves to next questions for the latest answer, `suggestAhead()` starts them
// while an answer is still being written, and `ask(question)` sends one.
export function chatMode(panel, {expand, focusComposer, suggest, suggestAhead, ask}) {
  const row = document.getElementById("categories_container");
  // Opt-in: the operator enables chat mode with `chat_mode: true`.
  if (panel.dataset.chatMode !== "true" || !row || document.getElementById("ai-chat-tab")) return inactive;
  const root = document.documentElement;
  const content = panel.querySelector(".ai-content");
  const collapse = panel.querySelector(".ai-collapse");
  const turns = panel.querySelector(".ai-turns");

  const tab = document.createElement("button");
  tab.type = "button";
  tab.id = "ai-chat-tab";
  tab.className = "category category_button";
  tab.setAttribute("aria-pressed", "false");
  tab.innerHTML = `${ICON}<div class="category_name">chat</div>`;
  const general = row.querySelector('button[name="category_general"]');
  if (general) general.after(tab);
  else row.append(tab);

  // Wide screens show each turn's sources open in a margin beside its answer.
  const wide = window.matchMedia("(min-width: 64rem)");
  const typed = document.querySelector("#q")?.defaultValue.trim() || "";
  // A search ending in "??" opens straight into chat mode.
  let openWhenReady = /\?\?$/.test(typed);
  const query = typed.replace(/\?{2,}$/, "?");
  function annotate() {
    if (!active()) return;
    const first = turns.querySelector(":scope > article");
    if (query && first && !first.querySelector(".ai-chat-query")) {
      const heading = document.createElement("h3");
      heading.className = "ai-chat-query";
      heading.textContent = query;
      first.prepend(heading);
    }
    let previous = "";
    for (const details of turns.querySelectorAll(".ai-sources")) {
      // A turn that reused the previous turn's sources keeps them folded.
      const sources = [...details.querySelectorAll("li a")].map(link => link.href).join(" ");
      const repeated = sources === previous;
      previous = sources;
      if (wide.matches && !repeated && !details.open) {
        details.open = true;
        details.dataset.chatOpened = "true";
      } else if (!wide.matches && details.dataset.chatOpened) {
        details.open = false;
        delete details.dataset.chatOpened;
      }
      // The margin shows one line of each snippet; the whole of it is a hover away.
      details.querySelectorAll("li p:not([title])").forEach(snippet => (snippet.title = snippet.textContent));
      const turn = details.closest("article");
      if (details.open) fold(details, turn);
    }
  }
  // The margin keeps the first four sources an answer cites and folds the rest, so a
  // long source list does not push the next question far down. It folds from the start
  // and refolds as an answer streams, so notes only ever appear as they are cited.
  function fold(details, turn) {
    const citations = [...turn.querySelectorAll(".ai-answer a[data-source-id]")].map(link => link.dataset.sourceId);
    const kept = new Set([...new Set(citations)].slice(0, MAX_NOTES));
    const items = [...details.querySelectorAll("li")];
    const extra = items.filter(item => !kept.has(item.dataset.sourceId));
    // A single leftover note takes no more room than the control that would fold it.
    const folding = extra.length >= 2;
    items.forEach(item => item.classList.toggle("ai-chat-extra", folding && extra.includes(item)));
    let more = details.querySelector(".ai-chat-more");
    if (!folding) {
      more?.remove();
      details.removeAttribute("data-chat-expanded");
      return;
    }
    if (!more) {
      more = document.createElement("button");
      more.type = "button";
      more.className = "ai-chat-more";
      more.setAttribute("aria-expanded", "false");
      more.addEventListener("click", () => {
        const expanded = more.getAttribute("aria-expanded") !== "true";
        more.setAttribute("aria-expanded", String(expanded));
        details.toggleAttribute("data-chat-expanded", expanded);
        label(more);
      });
      details.querySelector("ol").after(more);
    }
    more.dataset.count = extra.length;
    more.dataset.shown = kept.size;
    label(more);
  }
  function label(more) {
    const count = Number(more.dataset.count);
    const sources = count === 1 ? "source" : "sources";
    if (more.getAttribute("aria-expanded") === "true") more.textContent = "Fewer sources";
    else more.textContent = Number(more.dataset.shown) ? `${count} more ${sources}` : `Show ${count} ${sources}`;
  }
  function unannotate() {
    turns.querySelectorAll(".ai-chat-query, .ai-chat-more").forEach(element => element.remove());
    turns.querySelectorAll(".ai-chat-extra").forEach(item => item.classList.remove("ai-chat-extra"));
    turns.querySelectorAll(".ai-sources li p[title]").forEach(snippet => snippet.removeAttribute("title"));
    turns.querySelectorAll(".ai-sources[data-chat-expanded]").forEach(details => details.removeAttribute("data-chat-expanded"));
    turns.querySelectorAll(".ai-sources[data-chat-opened]").forEach(details => {
      details.open = false;
      delete details.dataset.chatOpened;
    });
    cite(null);
  }
  // New turns and their sources arrive while chatting; ignore streamed text.
  new MutationObserver(records => {
    if (records.some(record => [...record.addedNodes].some(node => node.matches?.("article, .ai-sources")))) annotate();
  }).observe(turns, {childList: true, subtree: true});
  wide.addEventListener("change", annotate);

  let cited = [];
  function cite(link) {
    cited.forEach(element => element.classList.remove("ai-chat-cited"));
    cited = [];
    const selector = link && `.ai-sources li[data-source-id="${link.dataset.sourceId}"]`;
    let turn = link?.closest("article");
    let note = turn?.querySelector(selector);
    // A turn whose sources are folded as "Same as above" points at the open note above.
    while (note && !note.closest("details").open && (turn = turn.previousElementSibling)) {
      const earlier = turn.querySelector(selector);
      if (earlier?.querySelector("a")?.href === note.querySelector("a")?.href) note = earlier;
    }
    if (note) cited = [link, note];
    cited.forEach(element => element.classList.add("ai-chat-cited"));
  }
  const citation = event => (active() && wide.matches ? event.target.closest?.(".ai-answer a[data-source-id]") : null);
  turns.addEventListener("pointerover", event => cite(citation(event)));
  turns.addEventListener("focusin", event => cite(citation(event)));
  turns.addEventListener("pointerleave", () => cite(null));
  // Following a citation to a folded note unfolds its list first, so the note can take focus.
  turns.addEventListener("click", event => {
    const link = event.target.closest?.(".ai-answer a[data-source-id]");
    const note = link?.closest("article")?.querySelector(`.ai-sources li.ai-chat-extra[data-source-id="${link.dataset.sourceId}"]`);
    const more = note?.closest("details").querySelector(".ai-chat-more[aria-expanded='false']");
    more?.click();
  }, true);

  // Suggested next questions sit between the latest answer and the composer, set
  // like the thread's own questions so they read as the turn that could come next.
  const suggestions = document.createElement("div");
  suggestions.className = "ai-chat-suggestions";
  suggestions.hidden = true;
  suggestions.innerHTML = '<p class="ai-sr-only" id="ai-chat-suggestions-label">Ask next</p><ul role="list" aria-labelledby="ai-chat-suggestions-label"></ul>';
  panel.querySelector(".ai-follow-up").before(suggestions);
  suggestions.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (button) ask(button.textContent);
  });
  let suggestedFor = null;
  let pendingSuggestions = null;
  function clearSuggestions() {
    pendingSuggestions?.abort();
    pendingSuggestions = null;
    suggestions.hidden = true;
    suggestions.querySelector("ul").replaceChildren();
  }
  async function offerSuggestions() {
    // One request per completed answer, and only while chatting.
    const answer = turns.lastElementChild;
    if (!suggest || !active() || !answer || suggestedFor === answer) return;
    suggestedFor = answer;
    const request = pendingSuggestions = new AbortController();
    const questions = await suggest({signal: request.signal});
    if (request !== pendingSuggestions || turns.lastElementChild !== answer) return;
    pendingSuggestions = null;
    const list = suggestions.querySelector("ul");
    list.replaceChildren(...questions.map(question => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = question;
      // The composer's send arrow: choosing a suggestion asks it right away.
      button.insertAdjacentHTML("beforeend", SEND_ICON);
      item.append(button);
      return item;
    }));
    suggestions.hidden = !questions.length;
  }

  // Chat mode can open while the first answer streams; sending a follow-up and
  // suggestions wait until the conversation can continue.
  let canFollowUp = false;
  let refolding = false;
  let focusWhenReady = false;
  let busy = false;
  let saved = null;
  let chatScroll = 0;
  const active = () => saved !== null;

  // Switching modes reflows the whole page. A crossfade keeps that from reading
  // as a jump; the mode state itself changes synchronously so a second click or
  // keypress during the fade cannot enter or leave twice.
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  function swap(apply) {
    if (document.startViewTransition && !reducedMotion.matches) document.startViewTransition(apply);
    else apply();
  }

  function enter({fromHistory = false} = {}) {
    if (active()) return;
    saved = {
      scroll: window.scrollY,
      selected: [...row.querySelectorAll(".selected")],
      expanded: panel.dataset.expanded === "true",
      collapsed: content.hidden,
      turns: turns.childElementCount,
    };
    if (!fromHistory) {
      focusWhenReady = !canFollowUp || busy;
      history.pushState({...history.state, [HISTORY_KEY]: true}, "");
      // The chat entry restores its own scroll position: the host theme scrolls
      // smoothly, and the browser's restoration would glide across the reflow.
      history.scrollRestoration = "manual";
    }
    // Entered mid-answer: its suggestions can be written while it finishes.
    if (busy) suggestAhead?.();
    swap(() => {
      saved.selected.forEach(button => button.classList.remove("selected"));
      tab.classList.add("selected");
      tab.setAttribute("aria-pressed", "true");
      root.dataset.aiChat = "true";
      panel.dataset.chat = "true";
      if (content.hidden) collapse.click();
      expand(true);
      annotate();
      if (canFollowUp && !busy) offerSuggestions();
      // Forward returns to where the thread was left; a fresh entry starts at its top.
      window.scrollTo({top: fromHistory ? chatScroll : 0, behavior: "instant"});
      if (!fromHistory) focusComposer();
    });
  }

  function exit({fromHistory = false} = {}) {
    if (!active()) return;
    const previous = saved;
    saved = null;
    focusWhenReady = false;
    chatScroll = window.scrollY;
    swap(() => {
      tab.classList.remove("selected");
      tab.setAttribute("aria-pressed", "false");
      previous.selected.forEach(button => button.classList.add("selected"));
      delete root.dataset.aiChat;
      delete panel.dataset.chat;
      unannotate();
      // An unchanged conversation returns to its previous disclosure; new turns stay open.
      const unchanged = turns.childElementCount === previous.turns;
      expand(unchanged ? previous.expanded : true);
      if (unchanged && previous.collapsed && !content.hidden) collapse.click();
      window.scrollTo({top: previous.scroll, behavior: "instant"});
    });
    if (!fromHistory && history.state?.[HISTORY_KEY]) history.back();
  }

  tab.addEventListener("click", () => (active() ? exit() : enter()));
  // The previously selected category (General) leaves chat mode instead of searching again.
  row.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!active() || !button || !saved.selected.includes(button)) return;
    event.preventDefault();
    event.stopPropagation();
    exit();
  }, true);
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || !active() || event.defaultPrevented || event.isComposing) return;
    // Leave Escape to the host's own fields, such as search autocomplete.
    if (!panel.contains(event.target) && event.target.closest?.("input, textarea, select, [contenteditable]")) return;
    event.preventDefault();
    event.stopPropagation();
    exit();
  }, true);
  window.addEventListener("popstate", event => {
    if (event.state?.[HISTORY_KEY]) enter({fromHistory: true});
    else exit({fromHistory: true});
  });
  // A reload starts with normal results, so drop a chat entry inherited from before it.
  if (history.state?.[HISTORY_KEY]) {
    history.replaceState({...history.state, [HISTORY_KEY]: false}, "");
    history.scrollRestoration = "auto";
  }

  return {
    // Whether chatting, as of the latest switch; the page catches up after a crossfade.
    active,
    update(state) {
      canFollowUp = state.canFollowUp;
      busy = state.busy;
      if (openWhenReady) {
        openWhenReady = false;
        enter();
      }
      if (!busy) annotate();
      // While an answer streams, refold its notes once the new text is on the page.
      else if (!refolding) {
        refolding = true;
        requestAnimationFrame(() => {
          refolding = false;
          annotate();
        });
      }
      if (busy || !canFollowUp) clearSuggestions();
      else offerSuggestions();
      // Entered before the answer finished: the composer takes focus once it appears.
      if (focusWhenReady && canFollowUp && !busy) {
        focusWhenReady = false;
        if (active() && [document.body, tab].includes(document.activeElement)) focusComposer();
      }
    },
  };
}
