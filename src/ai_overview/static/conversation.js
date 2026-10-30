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

function questions(value) {
  return Array.isArray(value) ? value.filter(question => typeof question === "string" && question.trim()).slice(0, 3) : [];
}

export class Conversation {
  #initialToken;
  #token;
  #client;
  #selected;
  #endpoints;
  #fetch;
  #notify;
  #active = null;
  #canFollowUp = false;
  #failed = false;
  #question;
  #wantsSuggestions;
  // Next questions the server sends with the latest answer, if any: a promise, as
  // they may follow the answer on its stream; `#suggesting` stops that stream.
  #suggested = null;
  #suggesting = null;
  // Whether the answer being written was asked to bring suggestions with it.
  #askedAhead = false;
  #choices = [];
  #modelsPending = null;

  // `wantsSuggestions()` asks the server to suggest next questions alongside an answer.
  constructor({token, selected, endpoints, onEvent, client, wantsSuggestions = () => false, fetch: request = globalThis.fetch.bind(globalThis)}) {
    this.#initialToken = this.#token = token;
    this.#client = client;
    this.#selected = {...selected};
    this.#endpoints = endpoints;
    this.#fetch = request;
    this.#notify = onEvent;
    this.#wantsSuggestions = wantsSuggestions;
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

  // Optional next questions for the latest completed answer; failures yield none.
  async suggest({signal} = {}) {
    if (!this.#endpoints.suggest || !this.#canFollowUp || this.#active) return [];
    const token = this.#token;
    if (this.#suggested) {
      const sent = await this.#suggested;
      if (token !== this.#token || this.#active) return [];
      // None sent (or none usable): ask for them as usual.
      if (sent.length) return sent;
    }
    const asked = await this.#requestSuggestions(token, signal);
    // A newer answer or restart makes these stale.
    return token !== this.#token || this.#active ? [] : asked;
  }

  // Starts suggestions while a search's first answer is still being written, unless
  // its stream already asked for them; `suggest()` then waits for these.
  suggestAhead() {
    if (!this.#endpoints.suggest || this.#active?.phase !== "streaming" || this.#question !== undefined) return;
    if (this.#askedAhead || this.#suggested) return;
    this.#suggesting = new AbortController();
    this.#suggested = this.#requestSuggestions(this.#token, this.#suggesting.signal);
  }

  async #requestSuggestions(token, signal) {
    try {
      const response = await this.#fetch(this.#endpoints.suggest, {
        method: "POST", credentials: "same-origin", signal,
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token}),
      });
      const data = await response.json();
      return response.ok ? questions(data.questions) : [];
    } catch {
      return [];
    }
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

  #dropSuggestions() {
    this.#suggesting?.abort();
    this.#suggesting = null;
    this.#suggested = null;
  }

  // Reads what follows a finished answer on its stream, up to its suggestions; a
  // newer turn settles it at once with none.
  #suggestionsAfter(stream, signal) {
    const dropped = new Promise(resolve => signal.addEventListener("abort", () => resolve([]), {once: true}));
    return Promise.race([this.#readSuggestions(stream), dropped]);
  }

  async #readSuggestions(stream) {
    try {
      for (let next; !(next = await stream.next()).done;) {
        if (next.value.name === "suggestions") return questions(next.value.data.questions);
      }
    } catch {
      // Aborted by a newer turn, or the connection ended.
    } finally {
      stream.return().catch(() => {});
    }
    return [];
  }

  #reset() {
    this.#dropSuggestions();
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

  // `fresh` bypasses the server's answer cache and replaces its entry.
  restart(choice = this.#selected, {fresh = false} = {}) {
    return this.#exclusive("selecting", async operation => {
      if (this.#endpoints.select) await this.#select(choice, operation);
      else {
        this.#token = this.#initialToken;
        this.#reset();
      }
      await this.#generate(undefined, operation, fresh);
    });
  }

  stop() {
    this.#active?.controller.abort();
  }

  async #generate(question, operation, fresh = false) {
    const signal = operation.controller.signal;
    operation.phase = "streaming";
    this.#question = question;
    this.#failed = false;
    this.#dropSuggestions();
    this.#askedAhead = Boolean(this.#endpoints.suggest && this.#wantsSuggestions());
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
            body: JSON.stringify({
              token: this.#token,
              ...(question ? {question} : {}),
              // Scopes the server's answer cache to this browser.
              ...(this.#client ? {client: this.#client} : {}),
              ...(fresh ? {fresh: true} : {}),
              ...(this.#askedAhead ? {suggest: true} : {}),
            }),
          });
          if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
            throw new Error("Could not start the overview. Try again.");
          }
          let complete = false;
          let handedOff = false;
          const stream = events(response.body);
          try {
            for (let next; !(next = await stream.next()).done;) {
              const event = next.value;
              signal.throwIfAborted();
              if (event.name === "error") {
                throw Object.assign(new Error(event.data.message), {code: event.data.code, status: response.status});
              }
              if (event.name === "suggestions") {
                this.#suggested = Promise.resolve(questions(event.data.questions));
                continue;
              }
              if (event.name === "done") {
                if (typeof event.data.token !== "string" || !event.data.token) throw new Error("Invalid overview continuation.");
                this.#token = event.data.token;
                this.#canFollowUp = event.data.can_follow_up;
                // Suggestions still being written follow the answer on this stream.
                if (event.data.suggesting === true) {
                  this.#suggesting = operation.controller;
                  this.#suggested = this.#suggestionsAfter(stream, operation.controller.signal);
                  handedOff = true;
                }
                complete = true;
                break;
              }
              receivedContent = true;
              this.#emit(event.name, event.data);
            }
          } finally {
            if (!handedOff) await stream.return();
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
