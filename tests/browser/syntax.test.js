import assert from "node:assert/strict";
import {readdirSync} from "node:fs";
import {test} from "node:test";
import {grammarFor, hasClosedFence, paintCode} from "../../src/ai_overview/static/syntax.js";
import {Node, settle} from "./dom.js";

const staticFiles = new URL("../../src/ai_overview/static/", import.meta.url);
const packaged = readdirSync(staticFiles)
  .map(file => file.match(/^highlight-(.+)\.js$/)?.[1])
  .filter(name => name && name !== "core");

test("only matching complete Markdown fences close a streaming code block", () => {
  for (const raw of [
    "```python\nx = 1\n```", "```js\nconst x = 1;\n````\n",
    "~~~sql\nSELECT 1;\n~~~", "  ```py\nx = 1\n  ``` \t",
  ]) assert.equal(hasClosedFence(raw), true, raw);
  for (const raw of [
    "```", "```python\n", "```python\nx = 1", "```py\nx = 1\n``",
    "````py\nx = 1\n```", "```py\nx = 1\n~~~", "```py\nx = 1\n```more",
    "    x = 1\n", "```py\nprint('```')\n",
  ]) assert.equal(hasClosedFence(raw), false, raw);
});

test("every packaged grammar is reachable by its name and its own aliases", async () => {
  const {default: hljs} = await import(new URL("highlight-core.js", staticFiles));
  assert.ok(packaged.length >= 39);
  for (const name of packaged) {
    const {default: grammar} = await import(new URL(`highlight-${name}.js`, staticFiles));
    for (const label of [name, ...(grammar(hljs).aliases || [])]) {
      // `shell` is deliberately Bash; the transcript grammar keeps its aliases.
      assert.equal(grammarFor(label), label === "shell" ? "bash" : name, label);
    }
  }
});

test("fence labels select a packaged grammar or nothing", () => {
  for (const [label, name] of Object.entries({
    JS: "javascript", ts: "typescript", py: "python", sh: "bash", zsh: "bash", shell: "bash",
    console: "shell", html: "xml", jsonc: "json", "c++": "cpp", "c#": "csharp", golang: "go",
    rs: "rust", yml: "yaml", toml: "ini", docker: "dockerfile", md: "markdown", kt: "kotlin",
  })) {
    assert.equal(grammarFor(label), name, label);
    assert.ok(packaged.includes(name), name);
  }
  for (const label of ["", "code", "text", "unknown-language", "constructor", "__proto__", "../overview"]) {
    assert.equal(grammarFor(label), undefined, label);
  }
});

test("a grammar is loaded on demand and paints the block that was waiting for it", async () => {
  const code = new Node("");
  const text = 'func main() { fmt.Println("hi") } // done';
  paintCode(code, text, "go", true);
  // Plain at once, highlighted when the grammar arrives.
  assert.equal(code.textContent, text);
  assert.equal(code.childElementCount, 0);
  await settle();
  assert.equal(code.textContent, text);
  assert.ok(code.classes().includes("hljs-keyword"));
  assert.ok(code.classes().includes("hljs-string"));
  // Once loaded, the same grammar paints synchronously, under an alias too.
  const again = new Node("");
  paintCode(again, "package main", "Golang", true);
  assert.ok(again.classes().includes("hljs-keyword"));
});

test("a block repainted while its grammar loads keeps the newer text", async () => {
  const code = new Node("");
  paintCode(code, "fn main() {}", "rust", true);
  paintCode(code, "let total = 1;", "unknown-language", true);
  await settle();
  assert.equal(code.textContent, "let total = 1;");
  assert.equal(code.childElementCount, 0);
});

test("an open fence stays plain, then highlights when it closes", async () => {
  const code = new Node("");
  paintCode(code, "name: value", "yaml", false);
  await settle();
  assert.equal(code.childElementCount, 0);
  paintCode(code, "name: value", "yaml", true);
  assert.ok(code.classes().includes("hljs-attr"));
});

test("unknown, unlabelled and oversized code stays plain", async () => {
  for (const [text, label] of [["plain <b>", "unknown-language"], ["plain", "Code"], ["x = 1\n".repeat(10000), "python"]]) {
    const code = new Node("");
    paintCode(code, text, label, true);
    await settle();
    assert.equal(code.textContent, text);
    assert.equal(code.childElementCount, 0);
  }
});

test("each added language highlights and keeps its text", async () => {
  const samples = {
    go: "package main", rust: "fn main() {}", java: "public class A {}", c: "int main(void) { return 0; }",
    cpp: "class A {};", csharp: "public class A {}", php: "<?php echo 'a';", ruby: "def a; end",
    kotlin: "fun main() {}", swift: "let a = 1", yaml: "a: 1", toml: 'a = "b"',
    dockerfile: "FROM alpine\nRUN echo hi", diff: "-a\n+b", markdown: "# Title", lua: "local a = 1",
    console: "$ echo hi", scss: "$a: 1px;", powershell: "Get-ChildItem -Path .", nginx: "listen 80;",
    makefile: "all:\n\techo hi", graphql: "query { a }", r: "x <- 1", perl: "my $a = 1;",
    scala: "object A", dart: "void main() {}", elixir: "def a, do: 1", haskell: "main = return ()",
    objectivec: "@interface A : NSObject\n@end", http: "GET / HTTP/1.1", protobuf: "message A {}",
    html: "<style>a { color: red; }</style><script>let a = 1;</script>",
  };
  for (const [label, text] of Object.entries(samples)) {
    const code = new Node("");
    paintCode(code, text, label, true);
    await settle();
    assert.equal(code.textContent, text, label);
    assert.ok(code.childElementCount > 0, label);
  }
});
