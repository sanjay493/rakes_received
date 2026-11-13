const REPORTS = {
  received: { label: "Rakes Received", url: "http://127.0.0.1:5000/api/rakes" },
  inbound: { label: "Loaded In-Bound", url: "http://127.0.0.1:5000/api/inbound" },
};
const AUTO_ALARM = "autoSendInbound"; // The alarm background.js sets

const statusEl = document.getElementById("status");
const tokenEl = document.getElementById("token");
const sendEl = document.getElementById("send");
const autoEl = document.getElementById("auto");
const autoStatusEl = document.getElementById("autoStatus");
const runNowEl = document.getElementById("runNow");

let table = null;
let tabId = null;
let origins = []; // Sites of the tab and of the frame holding the table, for automatic sending

function showStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = kind;
}

function updateSendButton() {
  sendEl.disabled = !table || !tokenEl.value.trim();
  // The box can always be unticked; ticking it needs an In-Bound table and a token.
  autoEl.disabled = !autoEl.checked && !(table && table.report === "inbound" && tokenEl.value.trim());
}

const isWebOrigin = (origin) => /^https?:\/\//.test(origin || "");

async function findTable() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab.id;
  const frames = await chrome.scripting.executeScript({
    target: { tabId: tab.id, allFrames: true },
    func: extractRakeTable,
  });

  let tableFrameId = null;
  for (const frame of frames) {
    const result = frame.result;
    if (result && result.table && (!table || result.table.rows.length > table.rows.length)) {
      table = result.table;
      tableFrameId = frame.frameId;
    }
  }
  const results = frames.map((frame) => frame.result).filter(Boolean);

  if (table && table.rows.length) {
    const frameOrigins = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => location.origin,
    });
    const tableFrame = frameOrigins.find((frame) => frame.frameId === tableFrameId);
    const tabOrigin = tab.url ? new URL(tab.url).origin : "";
    origins = [...new Set([tabOrigin, tableFrame && tableFrame.result].filter(isWebOrigin))];
    showStatus(`Found ${table.rows.length} ${REPORTS[table.report].label} rows on this page.`);
    return;
  }

  table = null;
  const tableCount = results.reduce((total, result) => total + result.tableCount, 0);
  const headings = results.flatMap((result) => result.headings).slice(0, 3).join(" | ");
  showStatus(
    `No rake table found (checked ${tableCount} tables). ` +
      "Open the Rakes Received or Loaded In-Bound report on FOIS first." +
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
    const response = await fetch(REPORTS[table.report].url, {
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
    } else if (table.report === "inbound") {
      showStatus(`Sent ${result.inserted} rakes. This is now the latest In-Bound list.`, "success");
      const pendingDistances = result.missing_distances || [];
      const pendingStations = result.missing_stations || [];
      if (pendingDistances.length || pendingStations.length) {
        await chrome.storage.local.set({ pendingDistances, pendingStations });
        await chrome.tabs.create({ url: "lookup.html" });
      }
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

const clock = (time) =>
  new Date(time).toLocaleString("en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

// Shows whether automatic sending is on, when it runs next and how the last run went.
async function showAuto() {
  const { auto, autoLast } = await chrome.storage.local.get(["auto", "autoLast"]);
  const alarm = await chrome.alarms.get(AUTO_ALARM);
  autoEl.checked = Boolean(auto);
  runNowEl.hidden = !auto;

  const lines = [];
  if (auto && alarm) lines.push(`On. Next send about ${clock(alarm.scheduledTime)}.`);
  if (auto && autoLast) lines.push(`Last automatic send, ${clock(autoLast.at)}: ${autoLast.message}`);
  autoStatusEl.textContent = lines.join(" ");
  autoStatusEl.className = auto && autoLast && !autoLast.ok ? "error" : "";
  updateSendButton();
}

async function toggleAuto() {
  if (!autoEl.checked) {
    await chrome.runtime.sendMessage({ type: "autoOff" });
    return showAuto();
  }

  // Chrome must be asked straight away, while this still counts as the click. The popup may close
  // while it asks, so background.js finishes turning sending on from autoPending.
  const auto = { tabId, origins };
  const asked = chrome.permissions.request({ origins: origins.map((origin) => `${origin}/*`) });
  await chrome.storage.local.set({ autoPending: auto, apiToken: tokenEl.value.trim() });

  let granted = false;
  try {
    granted = await asked;
  } catch (error) {
    autoStatusEl.textContent = `Can't send automatically from this page: ${error.message}`;
  }
  if (granted) {
    await chrome.runtime.sendMessage({ type: "autoOn", auto });
  } else {
    await chrome.storage.local.remove("autoPending");
  }
  await showAuto();
}

async function runNow() {
  runNowEl.disabled = true;
  autoStatusEl.className = "";
  autoStatusEl.textContent = "Refreshing the report and sending. This can take a minute or two...";
  await chrome.runtime.sendMessage({ type: "runNow" });
  runNowEl.disabled = false;
  await showAuto();
}

async function init() {
  const { apiToken } = await chrome.storage.local.get("apiToken");
  tokenEl.value = apiToken || "";
  tokenEl.addEventListener("input", updateSendButton);
  sendEl.addEventListener("click", send);
  autoEl.addEventListener("change", toggleAuto);
  runNowEl.addEventListener("click", runNow);

  try {
    await findTable();
  } catch (error) {
    showStatus(`Can't read this page: ${error.message}`, "error");
  }
  await showAuto();
}

init();
