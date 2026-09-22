import assert from "node:assert/strict";
import {test} from "node:test";
import {hasClosedFence} from "../../src/ai_overview/static/syntax.js";

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
