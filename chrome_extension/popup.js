const REPORTS = {
  received: { label: "Rakes Received", url: "https://rakes-received.fly.dev/api/rakes" },
  inbound: { label: "Loaded In-Bound", url: "https://rakes-received.fly.dev/api/inbound" },
  // The all-India list has the same columns as the Loaded In-Bound report, so the user picks where it goes.
  enroute: { label: "All-India", url: "https://rakes-received.fly.dev/api/enroute" },
};

const statusEl = document.getElementById("status");
const tokenEl = document.getElementById("token");
const sendEl = document.getElementById("send");
const sendEnrouteEl = document.getElementById("send-enroute");

let table = null;

function showStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = kind;
}

function updateSendButton() {
  sendEl.disabled = sendEnrouteEl.disabled = !table || !tokenEl.value.trim();
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
    showStatus(`Found ${table.rows.length} ${REPORTS[table.report].label} rows on this page.`);
    if (table.report === "inbound") {
      // SAIL plant lists go to the In-Bound page, the all-India list only to the All-India page.
      sendEl.textContent = "Send to In-Bound (SAIL)";
      sendEnrouteEl.hidden = false;
    }
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

async function send(target) {
  sendEl.disabled = sendEnrouteEl.disabled = true;
  showStatus("Sending...");

  const token = tokenEl.value.trim();
  await chrome.storage.local.set({ apiToken: token });

  try {
    const response = await fetch(REPORTS[target].url, {
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
    } else if (target === "enroute") {
      showStatus(`Sent ${result.inserted} rakes. This is now the latest All-India list.`, "success");
    } else if (target === "inbound") {
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

async function init() {
  const { apiToken } = await chrome.storage.local.get("apiToken");
  tokenEl.value = apiToken || "";
  tokenEl.addEventListener("input", updateSendButton);
  sendEl.addEventListener("click", () => send(table.report));
  sendEnrouteEl.addEventListener("click", () => send("enroute"));

  try {
    await findTable();
  } catch (error) {
    showStatus(`Can't read this page: ${error.message}`, "error");
  }
  updateSendButton();
}

init();
