const byId = (id) => document.getElementById(id);
const history = [];
let tokens = [];
let busy = false;
let detectedText = "";
let detectionVersion = 0;
let detectionTimer;
let detectionInFlight = false;

function acceptedText() {
  return tokens.map(token => token.masked ? token.maskValue : token.text).join("");
}

function updatePreview() {
  const privacy = byId("privacy").checked;
  byId("outgoing-section").hidden = !privacy;
  byId("composer").classList.toggle("privacy-off", !privacy);
  const current = detectedText === byId("prompt").value;
  byId("submit").disabled = busy || (privacy && !current);
  byId("detection-status").hidden = !privacy;
  byId("mask-count").textContent = privacy ? `${current ? tokens.filter(token => token.masked).length : 0} masked` : "Masking off";
  byId("preview").replaceChildren();
  if (!privacy || !current) {
    byId("preview").textContent = byId("prompt").value;
    return;
  }
  tokens.forEach(token => {
    if (!token.maskable) {
      byId("preview").append(document.createTextNode(token.text));
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "token";
    button.disabled = busy;
    button.classList.toggle("suggested", token.suggested);
    const updateButton = () => {
      button.textContent = token.masked ? token.maskValue : token.text;
      button.classList.toggle("masked", token.masked);
      button.setAttribute("aria-pressed", String(token.masked));
      button.title = token.masked ? "Unmask word" : "Mask word";
    };
    updateButton();
    button.addEventListener("click", () => {
      if (busy) return;
      token.masked = !token.masked;
      updateButton();
      byId("mask-count").textContent = `${tokens.filter(token => token.masked).length} masked`;
    });
    byId("preview").append(button);
  });
}

function applyDetection(next) {
  let prefix = 0;
  while (prefix < tokens.length && prefix < next.length && tokens[prefix].text === next[prefix].text) {
    next[prefix].masked = tokens[prefix].masked;
    prefix++;
  }
  let previousEnd = tokens.length - 1;
  let nextEnd = next.length - 1;
  while (previousEnd >= prefix && nextEnd >= prefix && tokens[previousEnd].text === next[nextEnd].text) {
    next[nextEnd--].masked = tokens[previousEnd--].masked;
  }
  tokens = next;
}

async function detectDraft(version) {
  if (detectionInFlight || version !== detectionVersion || !byId("privacy").checked) return;
  const text = byId("prompt").value;
  detectionInFlight = true;
  byId("detection-status").textContent = "Detecting private information...";
  try {
    const response = await fetch("/detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const result = await response.json();
    if (version !== detectionVersion || !byId("privacy").checked) return;
    if (!response.ok) throw new Error(result.error || "Privacy detection failed.");
    if (!Array.isArray(result.tokens) || result.tokens.some(token =>
      !token || typeof token.text !== "string" || typeof token.maskValue !== "string" ||
      typeof token.suggested !== "boolean" || typeof token.maskable !== "boolean"
    ) || result.tokens.map(token => token.text).join("") !== text) {
      throw new Error("Privacy detector returned invalid text segments.");
    }
    applyDetection(result.tokens.map(token => ({ ...token, masked: false })));
    detectedText = text;
    byId("detection-status").textContent = "Detection complete";
    byId("error").textContent = "";
  } catch (error) {
    if (version !== detectionVersion || !byId("privacy").checked) return;
    byId("detection-status").textContent = "Detection failed";
    byId("error").textContent = error.message;
    byId("retry-detection").hidden = false;
  } finally {
    detectionInFlight = false;
    updatePreview();
    if (version !== detectionVersion && byId("privacy").checked && detectedText !== byId("prompt").value) {
      clearTimeout(detectionTimer);
      detectionTimer = setTimeout(() => detectDraft(detectionVersion), 500);
    }
  }
}

function updateReview() {
  detectionVersion++;
  clearTimeout(detectionTimer);
  byId("retry-detection").hidden = true;
  byId("error").textContent = "";
  const text = byId("prompt").value;
  if (!text.trim()) {
    tokens = text ? [{ text, maskValue: "", maskable: false, suggested: false, masked: false }] : [];
    detectedText = text;
  }
  if (byId("privacy").checked && detectedText !== text) {
    byId("detection-status").textContent = "Waiting for detection...";
    const version = detectionVersion;
    detectionTimer = setTimeout(() => detectDraft(version), 500);
  } else {
    byId("detection-status").textContent = text.trim() ? "Detection complete" : "";
  }
  updatePreview();
}

function addMessage(role, content) {
  byId("empty")?.remove();
  const article = document.createElement("article");
  article.className = "message";
  const label = document.createElement("strong");
  label.textContent = role === "user" ? "YOU" : "OLLAMA";
  const paragraph = document.createElement("p");
  paragraph.textContent = content;
  article.append(label, paragraph);
  byId("conversation").append(article);
  article.scrollIntoView({ block: "nearest" });
}

async function sendMessage(content) {
  if (busy) return;
  busy = true;
  const model = byId("model").value.trim();
  const pending = [...history, { role: "user", content }];
  ["submit", "prompt", "privacy", "model", "clear"].forEach(id => byId(id).disabled = true);
  byId("preview").querySelectorAll("button").forEach(button => button.disabled = true);
  byId("error").textContent = "";
  byId("status").textContent = "Ollama is thinking...";
  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages: pending })
    });
    if (response.status === 413) {
      throw new Error("Request exceeds the 1 MiB limit, including chat history. Shorten your message or copy your draft and start a New chat.");
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Request failed.");
    history.push({ role: "user", content }, { role: "assistant", content: result.reply });
    addMessage("user", content);
    addMessage("assistant", result.reply);
    byId("prompt").value = "";
    updateReview();
  } catch (error) {
    byId("error").textContent = `${error.message} Your draft and masking choices have been kept.`;
  } finally {
    busy = false;
    ["submit", "prompt", "privacy", "model", "clear"].forEach(id => byId(id).disabled = false);
    byId("preview").querySelectorAll("button").forEach(button => button.disabled = false);
    byId("status").textContent = "Ready";
    updatePreview();
    byId("prompt").focus();
  }
}

byId("composer").addEventListener("submit", event => {
  event.preventDefault();
  if (busy) return;
  const text = byId("prompt").value;
  if (!text.trim()) return;
  if (byId("privacy").checked && detectedText !== text) return;
  if (!byId("model").value.trim()) { byId("model").focus(); return; }
  const content = byId("privacy").checked ? acceptedText() : text;
  if (!content.trim()) { byId("error").textContent = "The outgoing message is empty."; return; }
  sendMessage(content);
});
byId("prompt").addEventListener("input", updateReview);
byId("privacy").addEventListener("change", updateReview);
byId("retry-detection").addEventListener("click", updateReview);
byId("clear").addEventListener("click", () => window.location.reload());
updateReview();