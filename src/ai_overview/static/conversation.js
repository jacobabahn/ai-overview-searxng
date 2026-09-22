const BUSY_RETRY_DELAYS = [2000, 4000, 8000];

function waitForRetry(delay, signal) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const cancel = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve();
    }, delay);
    signal.addEventListener("abort", cancel, {once: true});
  });
}

// Owns request ordering and signed continuation state; independent of the DOM.
export async function* events(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let name = "message";
  let data = [];
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      let end;
      while ((end = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, end).replace(/\r$/, "");
        buffer = buffer.slice(end + 1);
        if (!line) {
          if (data.length) yield {name, data: JSON.parse(data.join("\n"))};
          name = "message";
          data = [];
        } else if (line.startsWith("event:")) {
          name = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          data.push(line.slice(5).replace(/^ /, ""));
        }
      }
      if (buffer.length > 300000 || data.join("").length > 300000) {
        throw new Error("The overview response was too large.");
      }
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export class Conversation {
  #initialToken;
  #token;
  #selected;
  #endpoints;
  #fetch;
  #notify;
  #active = null;
  #canFollowUp = false;
  #failed = false;
  #question;
  #choices = [];
  #modelsPending = null;

  constructor({token, selected, endpoints, onEvent, fetch: request = globalThis.fetch.bind(globalThis)}) {
    this.#initialToken = this.#token = token;
    this.#selected = {...selected};
    this.#endpoints = endpoints;
    this.#fetch = request;
    this.#notify = onEvent;
  }

  get state() {
    return {
      busy: Boolean(this.#active),
      phase: this.#active?.phase || "idle",
      canFollowUp: this.#canFollowUp,
      canRetry: this.#failed,
      selected: {...this.#selected},
      choices: this.#choices.map(choice => ({...choice})),
      loadingModels: Boolean(this.#modelsPending),
    };
  }

  #emit(name, data = {}) {
    this.#notify({name, data}, this.state);
  }

  async #exclusive(phase, work) {
    if (this.#active) return;
    const operation = {phase, controller: new AbortController()};
    this.#active = operation;
    this.#emit("state");
    try {
      await work(operation);
    } finally {
      this.#active = null;
      this.#emit("state");
    }
  }

  async #modelRequest(endpoint, body, signal) {
    const response = await this.#fetch(endpoint, {
      method: "POST", credentials: "same-origin", signal,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: this.#initialToken, ...body}),
    });
    const data = await response.json();
    signal?.throwIfAborted();
    if (!response.ok) throw new Error(data.message || "Could not load model settings.");
    return data;
  }

  loadModels() {
    if (!this.#endpoints.models) return Promise.resolve();
    if (this.#modelsPending) return this.#modelsPending;
    // Reserve before notifying callers or starting the request.
    this.#modelsPending = Promise.resolve().then(async () => {
      try {
        const result = await this.#modelRequest(this.#endpoints.models, {});
        this.#choices = result.choices;
        this.#emit("models", result);
      } catch (error) {
        this.#emit("models_error", {message: `${error.message} Using the current model.`});
      } finally {
        this.#modelsPending = null;
        this.#emit("state");
      }
    });
    this.#emit("models_loading");
    return this.#modelsPending;
  }

  async #select(choice, operation) {
    operation.phase = "selecting";
    this.#emit("state");
    const result = await this.#modelRequest(this.#endpoints.select,
      {profile: choice.profile, model: choice.model}, operation.controller.signal);
    if (typeof result.token !== "string" || !result.token) throw new Error("Invalid model selection response.");
    this.#token = result.token;
    this.#selected = {profile: choice.profile, model: choice.model};
    this.#reset();
  }

  #reset() {
    this.#canFollowUp = false;
    this.#failed = false;
    this.#question = undefined;
    this.#emit("reset", {selected: {...this.#selected}});
  }

  start(saved) {
    return this.#exclusive("starting", async operation => {
      const modelsReady = this.loadModels();
      if (saved && (saved.profile !== this.#selected.profile || saved.model !== this.#selected.model)) {
        await modelsReady;
        const choice = this.#choices.find(c => c.available && c.profile === saved.profile && c.model === saved.model);
        if (choice) {
          try { await this.#select(choice, operation); }
          catch (error) {
            operation.controller.signal.throwIfAborted();
            this.#emit("models_error", {message: `${error.message} Using the current model.`});
          }
        }
      }
      await this.#generate(undefined, operation);
    });
  }

  run(question) {
    return this.#exclusive("streaming", operation => this.#generate(question, operation));
  }

  retry() {
    if (!this.#failed) return Promise.resolve();
    return this.run(this.#question);
  }

  restart(choice = this.#selected) {
    return this.#exclusive("selecting", async operation => {
      if (this.#endpoints.select) await this.#select(choice, operation);
      else {
        this.#token = this.#initialToken;
        this.#reset();
      }
      await this.#generate(undefined, operation);
    });
  }

  stop() {
    this.#active?.controller.abort();
  }

  async #generate(question, operation) {
    const signal = operation.controller.signal;
    operation.phase = "streaming";
    this.#question = question;
    this.#failed = false;
    this.#emit("turn_start", {question});
    try {
      for (let attempt = 0; ; attempt++) {
        let receivedContent = false;
        try {
          signal.throwIfAborted();
          operation.phase = "streaming";
          if (attempt) this.#emit("status", {message: "Trying again…"});
          const response = await this.#fetch(this.#endpoints.stream, {
            method: "POST", credentials: "same-origin", signal,
            headers: {"Content-Type": "application/json", "Accept": "text/event-stream"},
            body: JSON.stringify({token: this.#token, ...(question ? {question} : {})}),
          });
          if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
            throw new Error("Could not start the overview. Try again.");
          }
          let complete = false;
          for await (const event of events(response.body)) {
            signal.throwIfAborted();
            if (event.name === "error") {
              throw Object.assign(new Error(event.data.message), {code: event.data.code, status: response.status});
            }
            if (event.name === "done") {
              if (typeof event.data.token !== "string" || !event.data.token) throw new Error("Invalid overview continuation.");
              this.#token = event.data.token;
              this.#canFollowUp = event.data.can_follow_up;
              complete = true;
              break;
            }
            receivedContent = true;
            this.#emit(event.name, event.data);
          }
          if (!complete) throw new Error("The connection ended before the answer was complete.");
          break;
        } catch (error) {
          signal.throwIfAborted();
          // Only retry local admission failures, before the server began any work.
          // Provider limits and interrupted/partial answers must never be replayed.
          if (error.code !== "busy" || error.status !== 429 || receivedContent) throw error;
          const delay = BUSY_RETRY_DELAYS[attempt];
          if (delay === undefined) {
            throw Object.assign(new Error("AI Summary is still busy. Try again in a moment."), {code: "busy"});
          }
          operation.phase = "waiting";
          this.#emit("waiting", {attempt: attempt + 1, maxAttempts: BUSY_RETRY_DELAYS.length, delay});
          await waitForRetry(delay, signal);
        }
      }
      this.#emit("turn_done");
    } catch (error) {
      this.#failed = true;
      const stopped = operation.phase === "waiting"
        ? "Waiting canceled. You can retry when you’re ready."
        : "Stopped. This answer is incomplete.";
      this.#emit("turn_error", {code: error.code, message: error.name === "AbortError" ? stopped : error.message});
    }
  }
}
