const RBS_URL = "https://rbs.indianrail.gov.in/ShortPath/ShortPathServlet";
const FOIS_STATION_URL = "https://fois.indianrail.gov.in/FOISWebPortal/FWP_SttnHelp";
const DISTANCES_URL = "https://rakes-received.fly.dev/api/distances";
const STATIONS_URL = "https://rakes-received.fly.dev/api/station_names";
const INBOUND_PAGE = "https://rakes-received.fly.dev/inbound";

const DELAY_MS = 1500; // Pause between lookups, to go easy on the Railways' site
const SAVE_EVERY = 10; // Save this often, so closing the tab loses little
const MAX_ERRORS = 3; // Stop after this many failures in a row

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Reads an RBS result page. Returns { km } with km empty when RBS doesn't know the
// station, or null when the page can't be understood.
function parseDistance(html, to) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  if (/Invalid Station Code/i.test(doc.body.textContent)) {
    return { km: null };
  }

  // Match the heading cell exactly: the page's outer layout table also contains this text.
  const isDistanceHeading = (cell) => /^\s*CUMULATIVE DISTANCE\s*$/i.test(cell.textContent);

  for (const table of doc.querySelectorAll("table")) {
    const headerRow = [...table.rows].find((row) => [...row.cells].some(isDistanceHeading));
    if (!headerRow) continue;

    // Headings can span several columns, so work out the column by adding up their widths.
    let column = 0;
    for (const cell of headerRow.cells) {
      if (isDistanceHeading(cell)) break;
      column += cell.colSpan;
    }

    const rows = [...table.tBodies].flatMap((body) => [...body.rows]);
    const last = rows.filter((row) => row.cells.length > column).pop();
    if (!last) return null;

    const distanceText = last.cells[column].textContent.trim();
    const km = Number(distanceText);
    // The last stop must be the destination itself, not a station listing it as a siding.
    const station = [...last.cells].slice(0, column).map((cell) => cell.textContent).join(" ").trim();
    return distanceText && Number.isFinite(km) && new RegExp(`^${to}\\b`).test(station) ? { km } : null;
  }
  return null;
}

async function lookUp({ from, to }) {
  const response = await fetch(RBS_URL, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      srcCode: from,
      destCode: to,
      gaugeType: "S",
      distance: "goods",
      PageName: "ShortPath",
    }),
  });
  if (!response.ok) throw new Error(`The Railways' site returned ${response.status}`);

  const result = parseDistance(await response.text(), to);
  if (!result) throw new Error(`Couldn't read the result for ${from} to ${to}`);
  return { from, to, km: result.km };
}

// Reads a FOIS Station Help result. Its heading reads "BKSC (BOKARO STEEL CITY (IN - T) (OUT - T))".
// Returns { name } with name empty when FOIS doesn't know the code, or null when the page can't be understood.
function parseStationName(html, code) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  if (!/STATION HELP/i.test(html)) return null;

  for (const heading of doc.querySelectorAll(".sttnhead")) {
    const text = heading.textContent.replace(/\s+/g, " ").trim();
    const match = text.match(new RegExp(`^${code} \\((.*)\\)$`));
    if (!match) continue;
    // Drop the "(IN - T) (OUT - T)" that says whether the station is open for traffic.
    const name = match[1].replace(/(\s*\((IN|OUT) - [^)]*\))+\s*$/, "").trim();
    return { name: name || null };
  }
  return { name: null };
}

async function lookUpStation(code) {
  const response = await fetch(FOIS_STATION_URL, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ Qry: "CRT_LOCN", txtSttnCode: code, txtSttnName: "", hidreset: "A" }),
  });
  if (!response.ok) throw new Error(`FOIS returned ${response.status}`);

  const result = parseStationName(await response.text(), code);
  if (!result) throw new Error(`Couldn't read the FOIS result for ${code}`);
  return { code, name: result.name };
}

async function post(url, body, token) {
  const response = await fetch(url, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`The dashboard returned ${response.status}`);
}

async function save(distances, token) {
  if (distances.length) await post(DISTANCES_URL, { distances }, token);
}

async function saveStations(stations, token) {
  if (stations.length) await post(STATIONS_URL, { stations }, token);
}

function showStatus(message, kind = "") {
  const status = document.getElementById("status");
  status.textContent = message;
  status.className = kind;
}

// Looks up each item, saving every SAVE_EVERY results. Returns { found, unknown, failed }.
// Stops with an error after MAX_ERRORS failures in a row, once what it has is saved.
async function lookUpAll(items, { describe, lookUpOne, isUnknown, saveAll }) {
  const progress = document.getElementById("progress");
  progress.value = 0;
  progress.max = items.length || 1;

  let unsaved = [];
  let errors = 0;
  const counts = { found: 0, unknown: 0, failed: 0 };
  try {
    for (const [index, item] of items.entries()) {
      showStatus(`Looking up ${index + 1} of ${items.length}: ${describe(item)}`);
      if (index) await sleep(DELAY_MS);

      try {
        const result = await lookUpOne(item);
        unsaved.push(result);
        counts[isUnknown(result) ? "unknown" : "found"] += 1;
        errors = 0;
      } catch (error) {
        errors += 1;
        counts.failed += 1;
        console.warn(error);
        if (errors >= MAX_ERRORS) throw error;
      }

      progress.value = index + 1;
      if (unsaved.length >= SAVE_EVERY) {
        await saveAll(unsaved);
        unsaved = [];
      }
    }
    await saveAll(unsaved);
  } catch (error) {
    await saveAll(unsaved).catch(() => {});
    throw error;
  }
  return counts;
}

async function run() {
  const { pendingDistances = [], pendingStations = [], apiToken } = await chrome.storage.local.get([
    "pendingDistances",
    "pendingStations",
    "apiToken",
  ]);

  if (!pendingDistances.length && !pendingStations.length) {
    showStatus("Nothing to look up.", "success");
    return;
  }

  const messages = [];
  let anyFailed = false;
  try {
    if (pendingStations.length) {
      const names = await lookUpAll(pendingStations, {
        describe: (code) => `station name for ${code}`,
        lookUpOne: lookUpStation,
        isUnknown: (result) => result.name === null,
        saveAll: (results) => saveStations(results, apiToken),
      });
      await chrome.storage.local.remove("pendingStations");
      anyFailed ||= names.failed > 0;
      messages.push(
        `Found ${names.found} station names` + (names.unknown ? `; FOIS doesn't know ${names.unknown} codes.` : ".") +
          (names.failed ? ` ${names.failed} name lookups failed and will be tried again on the next send.` : ""),
      );
    }

    if (pendingDistances.length) {
      const distances = await lookUpAll(pendingDistances, {
        describe: (pair) => `distance from ${pair.from} to ${pair.to}`,
        lookUpOne: lookUp,
        isUnknown: (result) => result.km === null,
        saveAll: (results) => save(results, apiToken),
      });
      await chrome.storage.local.remove("pendingDistances");
      anyFailed ||= distances.failed > 0;
      messages.push(
        `Found ${distances.found} distances` +
          (distances.unknown ? `; the site doesn't know ${distances.unknown} stations.` : ".") +
          (distances.failed ? ` ${distances.failed} distance lookups failed and will be tried again on the next send.` : ""),
      );
    }

    showStatus(`Done. ${messages.join(" ")} Refresh ${INBOUND_PAGE} to see them.`, anyFailed ? "error" : "success");
  } catch (error) {
    showStatus(`Stopped: ${error.message}. ${messages.join(" ")} Send the report again to look up the rest.`, "error");
  }
}

run();
