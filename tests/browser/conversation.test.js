import assert from "node:assert/strict";
import {test} from "node:test";
import {Conversation} from "../../src/ai_overview/static/conversation.js";

const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(picker = true) {
  const calls = [];
  const events = [];
  const conversation = new Conversation({
    token: "original-search",
    selected: {profile: "go", model: "first"},
    endpoints: {stream: "/stream", ...(picker ? {models: "/models", select: "/select"} : {})},
    onEvent: (event, state) => events.push({event, state}),
    fetch: (url, options) => new Promise((resolve, reject) => {
      calls.push({url, body: JSON.parse(options.body), signal: options.signal, resolve, reject});
    }),
  });
  return {conversation, calls, events};
}
function sse(...events) {
  return new Response(events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join(""),
    {headers: {"Content-Type": "text/event-stream"}});
}
const done = token => sse(["text_delta", {text: "Answer [1]"}], ["done", {token, can_follow_up: true}]);
const json = (data, status = 200) => new Response(JSON.stringify(data), {status, headers: {"Content-Type": "application/json"}});
async function nextCall(calls, count) {
  for (let i = 0; i < 10 && calls.length < count; i++) await tick();
  assert.equal(calls.length, count);
  return calls[count - 1];
}

test("model selection reserves the conversation against Retry and other actions", async () => {
  const {conversation: c, calls, events} = harness();
  const first = c.run();
  calls[0].resolve(sse(["error", {message: "Failed"}]));
  await first;
  assert.equal(c.state.canRetry, true);
  const switching = c.restart({profile: "go", model: "second"});
  assert.equal(c.state.phase, "selecting");
  await Promise.all([c.retry(), c.run("follow-up"), c.restart()]);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, "/select");
  assert.equal(calls[1].body.token, "original-search");
  calls[1].resolve(json({token: "selected-search"}));
  const generation = await nextCall(calls, 3);
  assert.equal(generation.body.token, "selected-search");
  generation.resolve(done("second-continuation"));
  await switching;
  const followup = c.run("Why?");
  assert.deepEqual(calls[3].body, {token: "second-continuation", question: "Why?"});
  calls[3].resolve(done("next-continuation"));
  await followup;
  assert.equal(events.filter(e => e.event.name === "reset").length, 1);
});

test("failed selection preserves the previous continuation and retry question", async () => {
  const {conversation: c, calls, events} = harness();
  let work = c.run(); calls[0].resolve(done("first-continuation")); await work;
  work = c.run("Why?"); calls[1].resolve(sse(["error", {message: "Failed"}])); await work;
  work = c.restart({profile: "go", model: "second"});
  calls[2].resolve(json({message: "Unavailable"}, 503));
  await assert.rejects(work, /Unavailable/);
  assert.equal(c.state.selected.model, "first");
  assert.equal(c.state.canFollowUp, true);
  assert.equal(c.state.canRetry, true);
  assert.equal(events.some(e => e.event.name === "reset"), false);
  work = c.retry();
  assert.deepEqual(calls[3].body, {token: "first-continuation", question: "Why?"});
  calls[3].resolve(done("retry-continuation")); await work;
});

test("Stop rejects a late done and retries with the last successful token", async () => {
  const {conversation: c, calls, events} = harness(false);
  let work = c.run(); calls[0].resolve(done("first-continuation")); await work;
  let streamController;
  let cancelled = false;
  const body = new ReadableStream({start(controller) { streamController = controller; }, cancel() { cancelled = true; }});
  work = c.run("Why?");
  calls[1].resolve(new Response(body, {headers: {"Content-Type": "text/event-stream"}}));
  await tick();
  c.stop();
  assert.equal(calls[1].signal.aborted, true);
  streamController.enqueue(new TextEncoder().encode('event: done\ndata: {"token":"late-token","can_follow_up":true}\n\n'));
  await work;
  assert.equal(cancelled, true);
  assert.match(events.findLast(e => e.event.name === "turn_error").event.data.message, /Stopped/);
  work = c.retry();
  assert.deepEqual(calls[2].body, {token: "first-continuation", question: "Why?"});
  calls[2].resolve(done("retry-continuation")); await work;
});

test("configured model starts while model discovery is pending", async () => {
  const {conversation: c, calls} = harness();
  const work = c.start();
  assert.equal(calls[0].url, "/stream");
  const catalog = await nextCall(calls, 2);
  assert.equal(catalog.url, "/models");
  calls[0].resolve(done("continuation")); await work;
  assert.equal(c.state.loadingModels, true);
  catalog.resolve(json({choices: [], warnings: []})); await tick();
  assert.equal(c.state.loadingModels, false);
});

test("saved model is selected before initial generation, with no overlapping start", async () => {
  const {conversation: c, calls} = harness();
  const choice = {profile: "go", model: "second", available: true};
  const work = c.start(choice);
  const catalog = await nextCall(calls, 1);
  assert.equal(catalog.url, "/models");
  await c.run(); assert.equal(calls.length, 1);
  catalog.resolve(json({choices: [choice], warnings: []}));
  const selection = await nextCall(calls, 2);
  assert.equal(selection.url, "/select"); selection.resolve(json({token: "selected"}));
  const stream = await nextCall(calls, 3);
  assert.equal(stream.body.token, "selected"); stream.resolve(done("continuation"));
  await work;
});

test("without a picker, restart uses the original search and clears follow-up state", async () => {
  const {conversation: c, calls, events} = harness(false);
  let work = c.start(); calls[0].resolve(done("continuation")); await work;
  work = c.restart();
  assert.deepEqual(calls[1].body, {token: "original-search"});
  assert.equal(c.state.canFollowUp, false);
  calls[1].resolve(done("regenerated")); await work;
  assert.equal(events.filter(e => e.event.name === "reset").length, 1);
});

test("premature EOF does not advance the continuation", async () => {
  const {conversation: c, calls} = harness(false);
  let work = c.run(); calls[0].resolve(done("continuation")); await work;
  work = c.run("Why?"); calls[1].resolve(sse(["text_delta", {text: "Partial"}])); await work;
  assert.equal(c.state.canRetry, true);
  work = c.retry(); assert.equal(calls[2].body.token, "continuation");
  calls[2].resolve(done("retry")); await work;
});

test("aborting selection cannot reset the displayed conversation or commit its token", async () => {
  const {conversation: c, calls, events} = harness();
  let work = c.run(); calls[0].resolve(done("continuation")); await work;
  work = c.restart({profile: "go", model: "second"});
  c.stop(); calls[1].resolve(json({token: "late-selection"}));
  await assert.rejects(work, {name: "AbortError"});
  assert.equal(c.state.selected.model, "first");
  assert.equal(events.some(e => e.event.name === "reset"), false);
  work = c.run("Why?"); assert.equal(calls[2].body.token, "continuation");
  calls[2].resolve(done("next")); await work;
});

const busy = () => new Response('event: error\ndata: {"code":"busy","message":"Busy"}\n\n',
  {status: 429, headers: {"Content-Type": "text/event-stream"}});

test("busy admission retries the same turn and reserves the conversation while waiting", async t => {
  t.mock.timers.enable({apis: ["setTimeout"]});
  const {conversation: c, calls, events} = harness(false);
  let work = c.run(); calls[0].resolve(done("continuation")); await work;
  work = c.run("Why?"); calls[1].resolve(busy()); await tick();
  assert.equal(c.state.phase, "waiting");
  assert.equal(c.state.busy, true);
  assert.equal(c.state.canRetry, false);
  await Promise.all([c.retry(), c.restart(), c.run("Other")]);
  assert.equal(calls.length, 2);
  t.mock.timers.tick(1999); await tick(); assert.equal(calls.length, 2);
  t.mock.timers.tick(1);
  const retry = await nextCall(calls, 3);
  assert.deepEqual(retry.body, {token: "continuation", question: "Why?"});
  retry.resolve(done("next")); await work;
  assert.equal(c.state.busy, false);
  assert.equal(c.state.canRetry, false);
  assert.equal(events.filter(e => e.event.name === "turn_start").length, 2);
  assert.equal(events.filter(e => e.event.name === "turn_error").length, 0);
  assert.deepEqual(events.find(e => e.event.name === "waiting").event.data,
    {attempt: 1, maxAttempts: 3, delay: 2000});
});

test("busy retries back off three times then stop, with manual retry starting a fresh budget", async t => {
  t.mock.timers.enable({apis: ["setTimeout"]});
  const {conversation: c, calls, events} = harness(false);
  let work = c.run(); calls[0].resolve(busy()); await tick();
  for (const [index, delay] of [2000, 4000, 8000].entries()) {
    assert.equal(c.state.phase, "waiting");
    t.mock.timers.tick(delay);
    const request = await nextCall(calls, index + 2);
    request.resolve(busy()); await tick();
  }
  await work;
  assert.equal(c.state.busy, false);
  assert.equal(c.state.canRetry, true);
  assert.match(events.findLast(e => e.event.name === "turn_error").event.data.message, /still busy/);
  t.mock.timers.tick(60000); await tick(); assert.equal(calls.length, 4);
  work = c.retry(); calls[4].resolve(busy()); await tick();
  assert.equal(events.findLast(e => e.event.name === "waiting").event.data.attempt, 1);
  t.mock.timers.tick(2000);
  const request = await nextCall(calls, 6); request.resolve(done("next")); await work;
});

test("canceling a busy wait immediately releases it and cancels every scheduled request", async t => {
  t.mock.timers.enable({apis: ["setTimeout"]});
  const {conversation: c, calls, events} = harness(false);
  const work = c.run(); calls[0].resolve(busy()); await tick();
  c.stop(); await work;
  assert.equal(c.state.busy, false);
  assert.equal(c.state.canRetry, true);
  assert.match(events.findLast(e => e.event.name === "turn_error").event.data.message, /Waiting canceled/);
  t.mock.timers.tick(60000); await tick(); assert.equal(calls.length, 1);
});

test("provider limits, other HTTP failures, and partial answers never auto-retry", async t => {
  t.mock.timers.enable({apis: ["setTimeout"]});
  for (const response of [
    new Response('event: error\ndata: {"code":"provider_limit","message":"Usage limit"}\n\n',
      {status: 429, headers: {"Content-Type": "text/event-stream"}}),
    sse(["error", {code: "busy", message: "Upstream busy"}]),
    new Response('event: text_delta\ndata: {"text":"Partial"}\n\nevent: error\ndata: {"code":"busy","message":"Busy"}\n\n',
      {status: 429, headers: {"Content-Type": "text/event-stream"}}),
    new Response("Unavailable", {status: 503}),
  ]) {
    const {conversation: c, calls, events} = harness(false);
    const work = c.run(); calls[0].resolve(response); await work;
    assert.equal(c.state.canRetry, true);
    assert.equal(events.some(e => e.event.name === "waiting"), false);
    t.mock.timers.tick(60000); await tick(); assert.equal(calls.length, 1);
  }
});
