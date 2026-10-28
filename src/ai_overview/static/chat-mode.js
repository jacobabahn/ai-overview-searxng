// Chat mode: a client-side "Chat" entry in SearXNG's category row that turns the
// results page into a full-width conversation with the AI Summary. It is not a
// server category: the signed continuation lives only in page memory, so a real
// navigation would lose the conversation. Entering pushes a history entry so Back
// exits; nothing is written to the URL, and a reload returns to normal results.
// What gets hidden while chatting is decided in chat-mode.css.

const HISTORY_KEY = "aiOverviewChat";
// Ionicons chatbubble-outline (MIT), in the same icon set and stroke as the host's.
const ICON = '<svg viewBox="0 0 512 512" class="ionicon sxng-icon-set-big" aria-hidden="true"><path d="M87.48 380c1.2-4.38-1.43-10.47-3.94-14.86a42.63 42.63 0 0 0-2.54-3.8 199.81 199.81 0 0 1-33-110C47.64 139.09 140.72 48 255.82 48 356.2 48 440 117.54 459.57 209.85a199 199 0 0 1 4.43 41.64c0 112.41-89.49 204.93-204.59 204.93-18.31 0-43-4.6-56.47-8.37s-26.92-8.77-30.39-10.11a31.14 31.14 0 0 0-11.13-2.07 30.7 30.7 0 0 0-12.08 2.43L81.5 467.23a16.48 16.48 0 0 1-4.78 1.26 9.81 9.81 0 0 1-9.75-9.85 16.17 16.17 0 0 1 .6-3.33Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-miterlimit="10" stroke-width="32px"/></svg>';

const inactive = {update() {}};

// `expand(value)` sets the panel's disclosure; `focusComposer()` moves focus to
// the follow-up composer when it is shown, without scrolling to it.
export function chatMode(panel, {expand, focusComposer}) {
  const row = document.getElementById("categories_container");
  if (!row || document.getElementById("ai-chat-tab")) return inactive;
  const root = document.documentElement;
  const content = panel.querySelector(".ai-content");
  const collapse = panel.querySelector(".ai-collapse");
  const turns = panel.querySelector(".ai-turns");

  const tab = document.createElement("button");
  tab.type = "button";
  tab.id = "ai-chat-tab";
  tab.className = "category category_button";
  tab.hidden = true;
  tab.setAttribute("aria-pressed", "false");
  tab.innerHTML = `${ICON}<div class="category_name">chat</div>`;
  const general = row.querySelector('button[name="category_general"]');
  if (general) general.after(tab);
  else row.append(tab);

  // Wide screens show each turn's sources open in a margin beside its answer.
  const wide = window.matchMedia("(min-width: 64rem)");
  const query = document.querySelector("#q")?.defaultValue.trim() || "";
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
    }
  }
  function unannotate() {
    turns.querySelectorAll(".ai-chat-query").forEach(heading => heading.remove());
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

  let available = false;
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
    if (active() || !available) return;
    saved = {
      scroll: window.scrollY,
      selected: [...row.querySelectorAll(".selected")],
      expanded: panel.dataset.expanded === "true",
      collapsed: content.hidden,
      turns: turns.childElementCount,
    };
    if (!fromHistory) {
      history.pushState({...history.state, [HISTORY_KEY]: true}, "");
      // The chat entry restores its own scroll position: the host theme scrolls
      // smoothly, and the browser's restoration would glide across the reflow.
      history.scrollRestoration = "manual";
    }
    swap(() => {
      saved.selected.forEach(button => button.classList.remove("selected"));
      tab.classList.add("selected");
      tab.setAttribute("aria-pressed", "true");
      root.dataset.aiChat = "true";
      panel.dataset.chat = "true";
      if (content.hidden) collapse.click();
      expand(true);
      annotate();
      // Forward returns to where the thread was left; a fresh entry starts at its top.
      window.scrollTo({top: fromHistory ? chatScroll : 0, behavior: "instant"});
      if (!fromHistory) focusComposer();
    });
  }

  function exit({fromHistory = false} = {}) {
    if (!active()) return;
    const previous = saved;
    saved = null;
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
      tab.hidden = !available;
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
    update(state) {
      available = state.canFollowUp;
      tab.hidden = !available && !active();
    },
  };
}
