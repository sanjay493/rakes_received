// The Rake trips page: fetches BOBSNM1 rake trips from the open FOIS tab, using foisfetch.js, and
// sends them to the dashboard.
const IDS_URL = "http://127.0.0.1:5000/api/rake_ids";
const TRIPS_URL = "http://127.0.0.1:5000/api/rake_trips";
const FOIS_TABS = "https://fois.indianrail.gov.in/ecbs/*";
const DELAY_MS = 1500; // Pause between requests, to go easy on FOIS
const MAX_ERRORS = 3; // Stop after this many failures in a row
const BAD_TOKEN = "The server rejected the API token.";

const byId = (id) => document.getElementById(id);
const tokenEl = byId("token");
const fromEl = byId("from");
const toEl = byId("to");
const modeAllEl = byId("modeAll");
const modeTickedEl = byId("modeTicked");
const rakesEl = byId("rakes");
const addIdEl = byId("addId");
const addEl = byId("add");
const runEl = byId("run");
const statusEl = byId("status");
const resultsEl = byId("results");

const rakeBoxes = new Map(); // Rake ID -> its checkbox
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Today as yyyy-mm-dd. FOIS takes no later date.
function today() {
  const now = new Date();
  const pad = (number) => String(number).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function showStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = kind;
}

function addLine(text, kind = "") {
  const line = document.createElement("li");
  line.textContent = text;
  line.className = kind;
  resultsEl.append(line);
  return line;
}

// Lists a rake, once. ticked also ticks one that is already listed.
function addRake(id, ticked = false) {
  let box = rakeBoxes.get(id);
  if (!box) {
    box = document.createElement("input");
    box.type = "checkbox";
    box.addEventListener("change", () => {
      if (box.checked) modeTickedEl.checked = true;
    });
    rakeBoxes.set(id, box);
    const label = document.createElement("label");
    label.className = "choice";
    label.append(box, id);
    rakesEl.append(label);
  }
  if (ticked) box.checked = true;
}

const tickedIds = () => [...rakeBoxes].filter(([, box]) => box.checked).map(([id]) => id);

// A dashboard request. Throws BAD_TOKEN on a 401, so the run can stop at once.
async function dashboard(url, token, body) {
  const options = { credentials: "omit", headers: { Authorization: `Bearer ${token}` } };
  if (body) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error("Could not reach the dashboard (is it running?)");
  }
  if (response.status === 401) throw new Error(BAD_TOKEN);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Server error (${response.status}).`);
  return result;
}

async function loadRakes(token) {
  const { rake_ids: ids } = await dashboard(IDS_URL, token);
  ids.forEach((id) => addRake(id));
}

async function inFois(tabId, func, args) {
  const [frame] = await chrome.scripting.executeScript({ target: { tabId }, func, args });
  const result = frame && frame.result;
  if (!result) throw new Error("The FOIS tab did not answer.");
  if (!result.ok) throw new Error(result.error);
  return result;
}

// Sends rows to the dashboard and says what became of them. saved counts the trips stored.
async function send(token, body) {
  const result = await dashboard(TRIPS_URL, token, body);
  return {
    saved: result.new + result.updated,
    message: `${result.new} new, ${result.updated} updated`,
    unreadable: result.unreadable,
  };
}

// Fetches every month and then every rake. Returns the closing status.
async function fetchAndSend(token, months, from, to, ticked) {
  await loadRakes(token);
  await chrome.storage.local.set({ apiToken: token });

  const [tab] = await chrome.tabs.query({ url: FOIS_TABS }).then(
    (tabs) => [...tabs].sort((a, b) => Number(a.discarded || false) - Number(b.discarded || false)),
  );
  if (!tab) throw new Error("Open FOIS e-Customer in a tab and log in first.");

  const wanted = ticked && new Set(ticked); // null means every rake
  const withTrips = new Set();
  const failed = new Set();
  const failedMonths = [];
  const reached = [];
  let errors = 0; // Failures in a row
  let started = false;

  // Runs one month or rake and shows its result. False when it failed.
  async function attempt(label, work) {
    if (started) await sleep(DELAY_MS);
    started = true;
    showStatus(`Fetching ${label}...`);
    try {
      const { message, unreadable } = await work();
      const line = addLine(`${label}: ${message}`);
      if (unreadable) {
        const warning = document.createElement("span");
        warning.className = "error";
        warning.textContent = `, ${unreadable} unreadable`;
        line.append(warning);
      }
      errors = 0;
      return true;
    } catch (error) {
      if (error.message === BAD_TOKEN) throw error;
      addLine(`${label}: ${error.message}`, "error");
      errors += 1;
      return false;
    }
  }

  for (const month of months) {
    if (errors >= MAX_ERRORS) break;
    const label = `Rakes Received ${month.from} to ${month.to}`;
    const done = await attempt(label, async () => {
      const report = await inFois(tab.id, foisReceived, [month.from, month.to]);
      const rows = receivedRowsFor(report.columns, report.rows, wanted);
      if (!rows.length) return { message: "no trips" };
      const result = await send(token, { source: "received", columns: report.columns, rows });
      const found = rakeIdsIn(report.columns, rows);
      if (result.saved) found.forEach((id) => withTrips.add(id));
      if (!wanted) found.forEach((id) => addRake(id));
      return result;
    });
    if (!done) failedMonths.push(label);
  }

  const chosen = ticked || [...rakeBoxes.keys()];
  for (const id of chosen) {
    if (errors >= MAX_ERRORS) break;
    reached.push(id);
    const done = await attempt(`Get RR ${id}`, async () => {
      const report = await inFois(tab.id, foisRR, [id]);
      const rows = rrRowsInPeriod(report.rows, from, to);
      if (!rows.length) return { message: "no trips" };
      const result = await send(token, { source: "rr", rake_id: id, rows });
      if (result.saved) withTrips.add(id);
      return result;
    });
    if (!done) failed.add(id);
  }

  const failures = [...failedMonths, ...failed];
  if (failures.length) addLine(`Failed: ${failures.join(", ")}`, "error");
  const notReached = chosen.slice(reached.length);
  if (notReached.length) addLine(`Not reached: ${notReached.join(", ")}`, "error");
  const without = rakesWithoutTrips(reached, withTrips, failed);
  if (without.length) {
    const heading = failedMonths.length
      ? "No trips found (some Rakes Received months failed)"
      : "No trips from either source";
    addLine(`${heading}: ${without.join(", ")}`);
  }

  if (errors >= MAX_ERRORS) return { message: `Stopped after ${MAX_ERRORS} failures in a row.`, kind: "error" };
  return failures.length ? { message: "Done, with failures.", kind: "error" } : { message: "Done.", kind: "success" };
}

async function run() {
  const token = tokenEl.value.trim();
  const from = fromEl.value;
  const to = toEl.value;
  const months = monthRanges(from, to);
  const ticked = modeAllEl.checked ? null : tickedIds();

  if (!token) return showStatus("Enter the API token.", "error");
  if (!months.length) return showStatus("Choose a From date on or before the To date.", "error");
  if (to > today()) return showStatus("The To date can't be after today.", "error");
  if (ticked && !ticked.length) return showStatus("Tick at least one Rake ID.", "error");

  runEl.disabled = true;
  resultsEl.replaceChildren();
  showStatus("Starting...");
  try {
    const outcome = await fetchAndSend(token, months, from, to, ticked);
    showStatus(outcome.message, outcome.kind);
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    runEl.disabled = false;
  }
}

function addTypedRake() {
  const id = cleanRakeId(addIdEl.value);
  if (!id) return;
  addRake(id, true);
  modeTickedEl.checked = true;
  addIdEl.value = "";
}

async function showRakes() {
  const token = tokenEl.value.trim();
  if (!token) return;
  try {
    await loadRakes(token);
    showStatus("");
  } catch (error) {
    showStatus(error.message, "error");
  }
}

async function init() {
  toEl.max = fromEl.max = today();
  runEl.addEventListener("click", run);
  addEl.addEventListener("click", addTypedRake);
  addIdEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") addTypedRake();
  });
  tokenEl.addEventListener("change", showRakes);

  const { apiToken } = await chrome.storage.local.get("apiToken");
  tokenEl.value = apiToken || "";
  await showRakes();
}

init();
