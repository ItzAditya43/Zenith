const DEFAULT_BASE_URL = "http://localhost:8420";

const statusEl = document.getElementById("status");
const baseUrlEl = document.getElementById("baseUrl");
const sendPageBtn = document.getElementById("sendPage");
const sendSelectionBtn = document.getElementById("sendSelection");

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = kind || "";
}

async function getBaseUrl() {
  const stored = await chrome.storage.local.get("baseUrl");
  return stored.baseUrl || DEFAULT_BASE_URL;
}

baseUrlEl.addEventListener("change", () => {
  const value = baseUrlEl.value.trim().replace(/\/$/, "") || DEFAULT_BASE_URL;
  chrome.storage.local.set({ baseUrl: value });
});

(async () => {
  baseUrlEl.value = await getBaseUrl();
})();

async function sendToZenith(title, message) {
  const baseUrl = await getBaseUrl();
  setStatus("Sending…");
  try {
    const convRes = await fetch(`${baseUrl}/api/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!convRes.ok) throw new Error(`Zenith returned ${convRes.status} creating the conversation`);
    const conv = await convRes.json();

    // Fire the turn and don't wait for the full reply — Zenith's backend
    // keeps generating independently of whether anyone reads the stream
    // (see stream_registry.py), so it's safe to just kick this off and
    // walk away. We only need the response headers to confirm it started.
    const chatRes = await fetch(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conv.id, message, attachment_ids: [] }),
    });
    if (chatRes.body) chatRes.body.cancel();
    if (!chatRes.ok) throw new Error(`Zenith returned ${chatRes.status} starting the reply`);

    setStatus("Sent — open Zenith to see the reply.", "ok");
  } catch (err) {
    setStatus(`Couldn't reach Zenith: ${err.message}`, "error");
  }
}

sendPageBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url) {
    setStatus("No active tab.", "error");
    return;
  }
  await sendToZenith(tab.title || tab.url, `Read and summarize this page: ${tab.url}`);
});

sendSelectionBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    setStatus("No active tab.", "error");
    return;
  }
  let selection = "";
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.getSelection().toString(),
    });
    selection = (result || "").trim();
  } catch (err) {
    setStatus(`Couldn't read the page selection: ${err.message}`, "error");
    return;
  }
  if (!selection) {
    setStatus("Nothing selected on the page.", "error");
    return;
  }
  await sendToZenith(
    `Clip: ${tab.title || tab.url}`,
    `From ${tab.url}:\n\n${selection}`
  );
});
