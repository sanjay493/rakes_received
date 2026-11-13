// Automatic sending: every PERIOD_MINUTES, refresh the Loaded In-Bound report that is open in the
// FOIS tab and send it to the dashboard. Turned on and off from the popup.
importScripts("extract.js");

const INBOUND_URL = "http://127.0.0.1:5000/api/inbound";
const ALARM = "autoSendInbound";
const PERIOD_MINUTES = 300; // 5 hours
const RELOAD_WAIT_MS = 120000; // How long the refreshed report may take to come back
const POLL_MS = 3000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Every frame of the tab that can be read: { frameId, stale, ready, table }. stale marks a document
// from before the refresh; ready means it has finished loading, so its table is whole.
async function readFrames(tabId) {
  // State first: a document that was complete then still has its whole table when it is read next.
  const states = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => ({ stale: Boolean(window.__rakeListStale), ready: document.readyState === "complete" }),
  });
  const tables = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: extractRakeTable,
  });
  return states.map((state) => {
    const found = tables.find((frame) => frame.frameId === state.frameId);
    return { frameId: state.frameId, ...(state.result || {}), table: found && found.result ? found.result.table : null };
  });
}

// The frame with the longest Loaded In-Bound table, or undefined.
function inboundFrame(frames) {
  return frames
    .filter((frame) => frame.table && frame.table.report === "inbound" && frame.table.rows.length)
    .sort((a, b) => b.table.rows.length - a.table.rows.length)[0];
}

// The tab and frame showing the report: the tab the box was ticked on, or failing that (Chrome was
// restarted, say) any open tab of the same site.
async function findReport(auto) {
  const tabIds = [auto.tabId];
  const others = await chrome.tabs.query({ url: auto.origins.map((origin) => `${origin}/*`) }).catch(() => []);
  tabIds.push(...others.map((tab) => tab.id).filter((id) => id !== auto.tabId));

  for (const tabId of tabIds) {
    try {
      const frame = inboundFrame(await readFrames(tabId));
      if (frame) return { tabId, frameId: frame.frameId };
    } catch (error) {
      // The tab is closed or can't be read; try the next one.
    }
  }
  return null;
}

// Reloads the report and returns its table once the new page has finished loading.
async function refreshedTable(auto) {
  const report = await findReport(auto);
  if (!report) {
    throw new Error("The Loaded In-Bound report is not open in a FOIS tab. Open it and tick the box again.");
  }

  await chrome.scripting.executeScript({
    target: { tabId: report.tabId, frameIds: [report.frameId] },
    func: () => {
      window.__rakeListStale = true; // Gone once the page has reloaded
      location.reload();
    },
  });

  const deadline = Date.now() + RELOAD_WAIT_MS;
  while (Date.now() < deadline) {
    await sleep(POLL_MS);
    let frames;
    try {
      frames = await readFrames(report.tabId);
    } catch (error) {
      continue; // Mid-navigation
    }
    const fresh = inboundFrame(frames.filter((frame) => !frame.stale && frame.ready));
    if (fresh) return fresh.table;
  }
  throw new Error(
    "The report did not come back after refreshing it. FOIS may have logged out: log in, open the report and tick the box again.",
  );
}

async function sendTable(table, token) {
  let response;
  try {
    response = await fetch(INBOUND_URL, {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(table),
    });
  } catch (error) {
    throw new Error(`Could not reach the dashboard (is it running?): ${error.message}`);
  }
  const result = await response.json().catch(() => ({}));
  if (response.status === 401) throw new Error("The server rejected the API token.");
  if (!response.ok) throw new Error(result.error || `Server error (${response.status}).`);

  const pendingDistances = result.missing_distances || [];
  const pendingStations = result.missing_stations || [];
  if (pendingDistances.length || pendingStations.length) {
    await chrome.storage.local.set({ pendingDistances, pendingStations });
    await chrome.tabs.create({ url: "lookup.html", active: false });
  }
  return { ok: true, message: `Sent ${result.inserted} rakes.` };
}

async function cycle() {
  const { auto, apiToken } = await chrome.storage.local.get(["auto", "apiToken"]);
  let outcome;
  try {
    if (!auto) throw new Error("Automatic sending is off.");
    if (!apiToken) throw new Error("No API token is saved. Open the extension and enter it.");
    outcome = await sendTable(await refreshedTable(auto), apiToken);
  } catch (error) {
    outcome = { ok: false, message: error.message };
  }
  outcome.at = Date.now();
  await chrome.storage.local.set({ autoLast: outcome });
  // A red "!" on the icon until a send works again.
  await chrome.action.setBadgeBackgroundColor({ color: "#b42318" });
  await chrome.action.setBadgeText({ text: outcome.ok ? "" : "!" });
  return outcome;
}

// One cycle at a time: a second request joins the one already running.
let running = null;
function runAuto() {
  running ??= cycle().finally(() => {
    running = null;
  });
  return running;
}

async function turnOn(auto) {
  await chrome.storage.local.set({ auto });
  await chrome.storage.local.remove("autoPending");
  await chrome.alarms.create(ALARM, { delayInMinutes: PERIOD_MINUTES, periodInMinutes: PERIOD_MINUTES });
}

async function turnOff() {
  await chrome.storage.local.remove(["auto", "autoPending", "autoLast"]);
  await chrome.alarms.clear(ALARM);
  await chrome.action.setBadgeText({ text: "" });
}

// Chrome can drop alarms on an update or restart: put it back while sending is on.
async function ensureAlarm() {
  const { auto } = await chrome.storage.local.get("auto");
  if (auto && !(await chrome.alarms.get(ALARM))) {
    await chrome.alarms.create(ALARM, { delayInMinutes: PERIOD_MINUTES, periodInMinutes: PERIOD_MINUTES });
  }
}

chrome.runtime.onInstalled.addListener(ensureAlarm);
chrome.runtime.onStartup.addListener(ensureAlarm);

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) runAuto();
});

// The popup can close while Chrome asks for access to the FOIS site, so it leaves what it wanted in
// autoPending and the grant itself turns sending on.
chrome.permissions.onAdded.addListener(async () => {
  const { autoPending } = await chrome.storage.local.get("autoPending");
  if (autoPending) await turnOn(autoPending);
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  const actions = { autoOn: () => turnOn(message.auto), autoOff: turnOff, runNow: runAuto };
  const action = actions[message && message.type];
  if (!action) return false;
  action().then(
    (result) => respond(result || { ok: true }),
    (error) => respond({ ok: false, message: error.message }),
  );
  return true; // The answer comes later
});
