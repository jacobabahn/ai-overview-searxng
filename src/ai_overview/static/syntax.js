// Packaged Highlight.js grammars (`highlight-<name>.js`) and the fence labels that
// select each: the grammar's own aliases, plus `shell`, which answers use for
// plain commands far more often than for a prompt-and-output transcript.
const grammars = {
  bash: ["sh", "zsh", "shell"],
  c: ["h"],
  cpp: ["cc", "c++", "h++", "hpp", "hh", "hxx", "cxx"],
  csharp: ["cs", "c#"],
  css: [],
  dart: [],
  diff: ["patch"],
  dockerfile: ["docker"],
  elixir: ["ex", "exs"],
  go: ["golang"],
  graphql: ["gql"],
  haskell: ["hs"],
  http: ["https"],
  ini: ["toml"],
  java: ["jsp"],
  javascript: ["js", "jsx", "mjs", "cjs"],
  json: ["jsonc", "json5"],
  kotlin: ["kt", "kts", "ktm", "ktx"],
  lua: ["pluto"],
  makefile: ["mk", "mak", "make"],
  markdown: ["md", "mkdown", "mkd"],
  nginx: ["nginxconf"],
  objectivec: ["mm", "objc", "obj-c", "obj-c++", "objective-c", "objective-c++"],
  perl: ["pl", "pm"],
  php: [],
  powershell: ["pwsh", "ps", "ps1"],
  protobuf: ["proto"],
  python: ["py", "gyp", "ipython"],
  r: [],
  ruby: ["rb", "gemspec", "podspec", "thor", "irb"],
  rust: ["rs"],
  scala: [],
  scss: [],
  shell: ["console", "shellsession", "shell-session"],
  sql: [],
  swift: [],
  typescript: ["ts", "tsx", "mts", "cts"],
  xml: ["html", "xhtml", "rss", "atom", "xjb", "xsd", "xsl", "plist", "wsf", "svg"],
  yaml: ["yml"],
};
// Grammars that hand embedded code to another grammar, such as a script in HTML.
const embedded = {
  xml: ["css", "javascript"],
  markdown: ["xml"],
  shell: ["bash"],
  dockerfile: ["bash"],
};

const labels = new Map();
for (const name of Object.keys(grammars)) labels.set(name, name);
// Aliases go in second, so `shell` means Bash and not the transcript grammar.
for (const [name, aliases] of Object.entries(grammars)) {
  for (const label of aliases) labels.set(label, name);
}

// The packaged grammar a fence label selects, or undefined for one we do not ship.
export function grammarFor(label) {
  return labels.get(label.toLowerCase());
}

let hljs;
const loading = new Map();

// Nothing is fetched until a code block needs it: the core with the first grammar,
// each grammar once. A failed fetch resolves false and the code stays plain.
function load(name) {
  if (!loading.has(name)) {
    const parts = [import("./highlight-core.js"), import(`./highlight-${name}.js`)];
    loading.set(name, Promise.all([...parts, ...(embedded[name] || []).map(load)]).then(
      ([core, grammar]) => {
        hljs = core.default;
        hljs.registerLanguage(name, grammar.default);
        return true;
      },
      () => false,
    ));
  }
  return loading.get(name);
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

function highlight(element, text, grammar) {
  try {
    const result = hljs.highlight(text, {language: grammar, ignoreIllegals: true});
    const nodes = highlightedNodes(result.value);
    if (nodes.textContent !== text) return false;
    element.replaceChildren(nodes);
    return true;
  } catch {
    return false; // A grammar failure should never interrupt the answer.
  }
}

export function paintCode(element, text, language, ready) {
  language = language.toLowerCase();
  const previous = painted.get(element);
  if (previous?.text === text && previous.language === language && previous.ready === ready) return;
  const state = {text, language, ready};
  painted.set(element, state);
  // Bound synchronous work; huge or unsupported examples are still fully usable.
  const grammar = text.length <= 50000 ? grammarFor(language) : undefined;
  if (ready && grammar && hljs?.getLanguage(grammar) && highlight(element, text, grammar)) return;
  if (element.textContent !== text || element.childElementCount) element.textContent = text;
  // Fetch as soon as a streaming block has a full label and some code, so the
  // grammar is usually here when the fence closes. A block that is ready before
  // its grammar is painted on arrival, unless it has been repainted since.
  if (!grammar || !text) return;
  const loaded = load(grammar);
  if (ready) {
    loaded.then(ok => {
      if (ok && painted.get(element) === state) highlight(element, text, grammar);
    });
  }
}

export function hasClosedFence(raw) {
  const lines = raw.replace(/\n$/, "").split("\n");
  const opening = lines[0].match(/^ {0,3}(`{3,}|~{3,})/);
  if (!opening || lines.length < 2) return false;
  return new RegExp(`^ {0,3}${opening[1][0]}{${opening[1].length},}[ \\t]*$`).test(lines.at(-1));
}
