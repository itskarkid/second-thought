const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");

function element() {
  const value = {
    value: "", checked: true, hidden: false, disabled: false,
    children: [], handlers: {}, classes: new Set(),
    get textContent() { return this.children.map(child => child.textContent).join(""); },
    set textContent(text) { this.children = [{ textContent: text }]; },
    replaceChildren() { this.children = []; },
    append(...children) { this.children.push(...children); },
    setAttribute(name, text) { this[name] = text; },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    querySelectorAll() { return this.children.filter(child => child.handlers); },
    focus() {}, remove() {}, scrollIntoView() {}
  };
  value.classList = { toggle(name, on) { value.classes[on ? "add" : "delete"](name); } };
  return value;
}

const html = fs.readFileSync(path.join(__dirname, "templates/index.html"), "utf8");
const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], element()]));
const calls = [];
const timers = new Map();
let timerId = 0;
const context = vm.createContext({
  document: {
    getElementById: id => elements.get(id),
    createElement: element,
    createTextNode: text => ({ textContent: text })
  },
  setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
  clearTimeout(id) { timers.delete(id); },
  fetch(url, options) {
    return new Promise(resolve => calls.push({ url, body: JSON.parse(options.body), resolve }));
  }
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "static/chat.js"), "utf8"), context);
const input = elements.get("prompt");
const privacy = elements.get("privacy");
const preview = elements.get("preview");
const type = text => { input.value = text; input.handlers.input(); };
const flush = () => {
  const callbacks = [...timers.values()];
  timers.clear();
  callbacks.forEach(callback => callback());
};
const settle = () => new Promise(resolve => setImmediate(resolve));
const token = text => ({ text, suggested: true, maskable: true, maskValue: "[PRIVATE]", label: "private_person" });
const answer = (index, tokens) => calls[index].resolve({ ok: true, json: async () => ({ tokens }) });
const submit = () => elements.get("composer").handlers.submit({ preventDefault() {} });

async function test() {
  elements.get("model").value = "llama3.2:3b";
  type("Alice");
  assert(elements.get("submit").disabled);
  flush();
  assert.equal(calls[0].url, "/detect");
  type("Bob");
  flush();
  assert.equal(calls.length, 1);
  answer(0, [token("Alice")]);
  await settle();
  assert(elements.get("submit").disabled);
  flush();
  assert.equal(calls[1].body.text, "Bob");
  answer(1, [token("Bob")]);
  await settle();
  assert(!elements.get("submit").disabled);
  preview.querySelectorAll()[0].handlers.click();
  assert.equal(preview.textContent, "[PRIVATE]");
  privacy.checked = false;
  privacy.handlers.change();
  assert(!elements.get("submit").disabled);
  privacy.checked = true;
  privacy.handlers.change();
  assert.equal(preview.textContent, "[PRIVATE]");
  submit();
  submit();
  assert.equal(calls.length, 3);
  assert.equal(calls[2].url, "/chat");
  assert.equal(calls[2].body.messages[0].content, "[PRIVATE]");
  calls[2].resolve({ ok: false, json: async () => ({ error: "chat failed" }) });
  await settle();
  assert.equal(preview.textContent, "[PRIVATE]");
  for (const htmlResponse of [false, true]) {
    submit();
    const oversized = calls.at(-1);
    assert.equal(oversized.body.messages.length, 1);
    assert.equal(oversized.body.messages[0].content, "[PRIVATE]");
    let parsed = false;
    oversized.resolve({
      ok: false, status: 413,
      json: async () => {
        parsed = true;
        if (htmlResponse) throw new SyntaxError("Unexpected token '<'");
        return { error: "Request too large" };
      }
    });
    await settle();
    assert.equal(parsed, false);
    assert.equal(input.value, "Bob");
    assert.equal(preview.textContent, "[PRIVATE]");
    assert(!elements.get("submit").disabled);
    assert(!input.disabled);
    assert(!elements.get("clear").disabled);
    assert.match(elements.get("error").textContent, /1 MiB.*chat history.*Shorten.*New chat/);
    assert.match(elements.get("error").textContent, /draft and masking choices have been kept/);
  }
  const detectionStart = calls.length;
  type("Charlie");
  flush();
  calls[detectionStart].resolve({ ok: false, json: async () => ({ error: "detector unavailable" }) });
  await settle();
  assert(elements.get("submit").disabled);
  assert(!elements.get("retry-detection").hidden);
  submit();
  assert.equal(calls.length, detectionStart + 1);
  elements.get("retry-detection").handlers.click();
  flush();
  answer(detectionStart + 1, [token("Wrong")]);
  await settle();
  assert(elements.get("submit").disabled);
  elements.get("retry-detection").handlers.click();
  flush();
  privacy.checked = false;
  privacy.handlers.change();
  answer(detectionStart + 2, [token("Charlie")]);
  await settle();
  assert(!elements.get("submit").disabled);
  assert.equal(elements.get("outgoing-section").hidden, true);
  const count = calls.length;
  type("No detection while off");
  flush();
  assert.equal(calls.length, count);
  submit();
  assert.equal(calls.at(-1).body.messages.at(-1).content, "No detection while off");
  calls.at(-1).resolve({ ok: true, json: async () => ({ reply: "OK" }) });
  await settle();
  assert.equal(input.value, "");
  type("Next message");
  submit();
  assert.equal(calls.at(-1).body.messages.length, 3);
  calls.at(-1).resolve({
    ok: false, status: 413,
    json: async () => { throw new SyntaxError("Unexpected token '<'"); }
  });
  await settle();
  assert.equal(input.value, "Next message");
  assert.match(elements.get("error").textContent, /chat history.*New chat/);
  console.log("PASS: detection timing, stale results, errors, retry, manual masks, privacy toggle, send payloads, and oversized requests");
}

test().catch(error => { console.error(error); process.exitCode = 1; });