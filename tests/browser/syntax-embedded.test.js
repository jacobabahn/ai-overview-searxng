import assert from "node:assert/strict";
import {readdirSync, readFileSync} from "node:fs";
import {test} from "node:test";
import {paintCode} from "../../src/ai_overview/static/syntax.js";
import {Node, settle} from "./dom.js";

// This file runs in its own process, so its first block starts with nothing loaded.
test("the first JavaScript block highlights its css and html templates", async () => {
  const code = new Node("");
  const text = 'const style = css`a { color: red; }`;\nconst view = html`<p class="x">hi</p>`;';
  paintCode(code, text, "js", true);
  await settle();
  assert.equal(code.textContent, text);
  assert.ok(code.classes().includes("language-css"), code.classes().join(" "));
  assert.ok(code.classes().includes("language-xml"), code.classes().join(" "));
});

test("grammars that embed each other finish loading", async () => {
  // HTML embeds JavaScript, which embeds HTML.
  const page = new Node("");
  const html = "<style>a { color: red; }</style>\n<script>let total = 42;</script>";
  paintCode(page, html, "html", true);
  await settle();
  assert.equal(page.textContent, html);
  assert.ok(page.classes().includes("language-css"));
  assert.ok(page.classes().includes("language-javascript"));
  const typed = new Node("");
  const text = "const query: string = gql`query { viewer { id } }`;";
  paintCode(typed, text, "ts", true);
  await settle();
  assert.ok(typed.classes().includes("language-graphql"), typed.classes().join(" "));
  // Loaded grammars paint at once, embedded code included.
  const again = new Node("");
  paintCode(again, "const style = css`a { color: red; }`;", "javascript", true);
  assert.ok(again.classes().includes("language-css"));
});

test("every sub-language a packaged grammar names is embedded or deliberately left out", () => {
  const staticFiles = new URL("../../src/ai_overview/static/", import.meta.url);
  const source = readFileSync(new URL("syntax.js", staticFiles), "utf8");
  const table = source.slice(source.indexOf("const embedded = {"), source.indexOf("const labels"));
  const omitted = {yaml: ["ruby"], dart: ["markdown"], perl: ["mojolicious"]};
  for (const file of readdirSync(staticFiles)) {
    const name = file.match(/^highlight-(.+)\.js$/)?.[1];
    if (!name || name === "core") continue;
    const grammar = readFileSync(new URL(file, staticFiles), "utf8");
    for (const [, inner] of grammar.matchAll(/subLanguage:"([\w-]+)"/g)) {
      if (omitted[name]?.includes(inner)) continue;
      const row = table.match(new RegExp(`^  ${name}: \\[(.*)\\],$`, "m"));
      assert.ok(row?.[1].includes(`"${inner}"`), `${name} embeds ${inner}`);
    }
  }
});
