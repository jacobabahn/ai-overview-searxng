import hljs from "./highlight-core.js";
import python from "./highlight-python.js";
import javascript from "./highlight-javascript.js";
import typescript from "./highlight-typescript.js";
import xml from "./highlight-xml.js";
import css from "./highlight-css.js";
import json from "./highlight-json.js";
import bash from "./highlight-bash.js";
import sql from "./highlight-sql.js";

for (const [name, grammar] of Object.entries({python, javascript, typescript, xml, css, json, bash, sql})) {
  hljs.registerLanguage(name, grammar);
}

const painted = new WeakMap();
const entities = {amp: "&", lt: "<", gt: ">", quot: '"', "#x27": "'", "#39": "'"};

// Highlight.js emits escaped text and span tags. Rebuild just those nodes rather
// than insert HTML, so even HTML examples remain literal, inert code.
function highlightedNodes(html) {
  const fragment = document.createDocumentFragment();
  const stack = [fragment];
  for (const part of html.split(/(<span class="[\w -]+">|<\/span>)/g)) {
    if (part === "</span>") {
      if (stack.length > 1) stack.pop();
    } else if (part.startsWith('<span class="')) {
      const span = document.createElement("span");
      span.className = part.slice(13, -2);
      stack.at(-1).append(span);
      stack.push(span);
    } else {
      stack.at(-1).append(document.createTextNode(part.replace(/&(amp|lt|gt|quot|#x27|#39);/g, (_, entity) => entities[entity])));
    }
  }
  return fragment;
}

export function paintCode(element, text, language, ready) {
  language = language.toLowerCase();
  const previous = painted.get(element);
  if (previous?.text === text && previous.language === language && previous.ready === ready) return;
  painted.set(element, {text, language, ready});
  // Bound synchronous work; huge or unsupported examples are still fully usable.
  if (ready && text.length <= 50000 && hljs.getLanguage(language)) {
    try {
      const result = hljs.highlight(text, {language, ignoreIllegals: true});
      const nodes = highlightedNodes(result.value);
      if (nodes.textContent === text) {
        element.replaceChildren(nodes);
        return;
      }
    } catch { /* A grammar failure should never interrupt the answer. */ }
  }
  if (element.textContent !== text || element.childElementCount) element.textContent = text;
}

export function hasClosedFence(raw) {
  const lines = raw.replace(/\n$/, "").split("\n");
  const opening = lines[0].match(/^ {0,3}(`{3,}|~{3,})/);
  if (!opening || lines.length < 2) return false;
  return new RegExp(`^ {0,3}${opening[1][0]}{${opening[1].length},}[ \\t]*$`).test(lines.at(-1));
}
