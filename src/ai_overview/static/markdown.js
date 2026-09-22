import {copyText} from "./clipboard.js";
import {Lexer} from "./marked.js";
import {paintCode, hasClosedFence} from "./syntax.js";

// Only character references go through the HTML decoder, never generated markup.
function decodeEntities(text) {
  return text.replace(/&(?:#\d+|#x[\da-f]+|[a-z][\da-z]+);/gi, entity => {
    const decoder = document.createElement("textarea");
    decoder.innerHTML = entity;
    return decoder.value;
  });
}

function codeBlock() {
  const block = document.createElement("div");
  block.className = "ai-code-block";
  const toolbar = document.createElement("div");
  toolbar.className = "ai-code-toolbar";
  const language = document.createElement("span");
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = "Copy code";
  const status = document.createElement("span");
  status.className = "ai-code-status";
  status.setAttribute("role", "status");
  const pre = document.createElement("pre");
  pre.tabIndex = 0;
  pre.setAttribute("aria-label", "Code block");
  const code = document.createElement("code");
  pre.append(code);
  toolbar.append(language, copy);
  block.append(toolbar, pre, status);
  copy.addEventListener("click", async () => {
    try {
      await copyText(code.textContent);
      status.textContent = "Code copied.";
    } catch {
      status.textContent = "Could not copy. Select the code to copy it.";
    }
  });
  return block;
}

// A DOM renderer for a deliberate subset of Markdown. No generated HTML is parsed
// or inserted; unsupported markup stays text. Code never enters citation parsing.
export function renderMarkdown(element, text, sources, renderCitations, {complete = true} = {}) {
  const previousCode = [...element.querySelectorAll(".ai-code-block")];
  let codeIndex = 0;
  function render(tokens, citations = true) {
    const nodes = [];
    for (const token of tokens) {
      let node;
      switch (token.type) {
        case "code": {
          const block = previousCode[codeIndex++] || codeBlock();
          const language = token.lang?.trim().split(/\s+/)[0] || "Code";
          block.querySelector(".ai-code-toolbar span").textContent = language;
          const code = block.querySelector("code");
          if (code.textContent !== token.text) {
            block.querySelector(".ai-code-status").textContent = "";
          }
          paintCode(code, token.text, language, complete || hasClosedFence(token.raw));
          const preview = document.createElement("span");
          preview.className = "ai-code-preview";
          preview.textContent = language === "Code" ? "Code block. " : `${language} code block. `;
          nodes.push(preview, block);
          continue;
        }
        case "codespan":
          node = document.createElement("code");
          node.textContent = token.text;
          break;
        case "paragraph":
        case "heading":
        case "strong":
        case "em":
        case "blockquote":
          node = document.createElement({paragraph: "p", heading: "h3", strong: "strong", em: "em", blockquote: "blockquote"}[token.type]);
          node.append(...render(token.tokens || [], citations));
          break;
        case "list":
          node = document.createElement(token.ordered ? "ol" : "ul");
          if (token.ordered) node.start = token.start;
          for (const item of token.items) {
            const li = document.createElement("li");
            li.append(...render(item.tokens, citations));
            node.append(li);
          }
          break;
        case "link":
          // Source links remain the sole clickable references in an overview.
          nodes.push(...render(token.tokens, false));
          continue;
        case "text":
          if (token.tokens) {
            nodes.push(...render(token.tokens, citations));
            continue;
          }
          node = document.createElement("span");
          if (citations) renderCitations(node, decodeEntities(token.text), sources);
          else node.textContent = decodeEntities(token.text);
          break;
        case "escape":
          node = document.createTextNode(token.text);
          break;
        case "br":
          node = document.createTextNode("\n");
          break;
        case "space":
          node = document.createTextNode(token.raw);
          break;
        default:
          node = document.createTextNode(token.raw || "");
      }
      nodes.push(node);
    }
    return nodes;
  }
  const nodes = render(Lexer.lex(text, {gfm: false}));
  // Leave existing top-level code blocks attached: focus and horizontal scroll
  // must survive each streaming delta, including the final closing fence.
  const keep = new Set(nodes);
  for (const child of [...element.childNodes]) if (!keep.has(child)) child.remove();
  nodes.forEach((node, index) => {
    if (element.childNodes[index] !== node) element.insertBefore(node, element.childNodes[index] || null);
  });
}
