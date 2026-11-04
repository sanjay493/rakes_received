const API_URL = "https://rakes-received.fly.dev/api/rakes";

const statusEl = document.getElementById("status");
const tokenEl = document.getElementById("token");
const sendEl = document.getElementById("send");

let table = null;

function showStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = kind;
}

function updateSendButton() {
  sendEl.disabled = !table || !tokenEl.value.trim();
}

async function findTable() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const frames = await chrome.scripting.executeScript({
    target: { tabId: tab.id, allFrames: true },
    func: extractRakeTable,
  });

  const results = frames.map((frame) => frame.result).filter(Boolean);
  for (const result of results) {
    if (result.table && (!table || result.table.rows.length > table.rows.length)) {
      table = result.table;
    }
  }

  if (table && table.rows.length) {
    showStatus(`Found ${table.rows.length} rows on this page.`);
    return;
  }

  table = null;
  const tableCount = results.reduce((total, result) => total + result.tableCount, 0);
  const headings = results.flatMap((result) => result.headings).slice(0, 3).join(" | ");
  showStatus(
    `No rake table found (checked ${tableCount} tables). ` +
      "Open the report on FOIS first." +
      (headings ? ` Headings seen: ${headings}` : ""),
    "error",
  );
}

async function send() {
  sendEl.disabled = true;
  showStatus("Sending...");

  const token = tokenEl.value.trim();
  await chrome.storage.local.set({ apiToken: token });

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      // Without this, a 401 from the site's login makes Chrome show a password box.
      credentials: "omit",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(table),
    });
    const result = await response.json().catch(() => ({}));

    if (response.status === 401) {
      showStatus("The server rejected the API token.", "error");
    } else if (!response.ok) {
      showStatus(result.error || `Server error (${response.status}).`, "error");
    } else {
      const unusable = result.received - result.inserted - result.skipped;
      showStatus(
        `Sent ${result.received} rows: ${result.inserted} new, ` +
          `${result.skipped} already there, ${unusable} not usable.`,
        "success",
      );
    }
  } catch (error) {
    showStatus(`Could not reach the dashboard: ${error.message}`, "error");
  }

  updateSendButton();
}

async function init() {
  const { apiToken } = await chrome.storage.local.get("apiToken");
  tokenEl.value = apiToken || "";
  tokenEl.addEventListener("input", updateSendButton);
  sendEl.addEventListener("click", send);

  try {
    await findTable();
  } catch (error) {
    showStatus(`Can't read this page: ${error.message}`, "error");
  }
  updateSendButton();
}

init();
