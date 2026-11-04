const RBS_URL = "https://rbs.indianrail.gov.in/ShortPath/ShortPathServlet";
const DISTANCES_URL = "https://rakes-received.fly.dev/api/distances";
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

async function save(distances, token) {
  if (!distances.length) return;
  const response = await fetch(DISTANCES_URL, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ distances }),
  });
  if (!response.ok) throw new Error(`The dashboard returned ${response.status}`);
}

function showStatus(message, kind = "") {
  const status = document.getElementById("status");
  status.textContent = message;
  status.className = kind;
}

async function run() {
  const { pendingDistances = [], apiToken } = await chrome.storage.local.get(["pendingDistances", "apiToken"]);
  const progress = document.getElementById("progress");
  progress.max = pendingDistances.length || 1;

  if (!pendingDistances.length) {
    showStatus("Nothing to look up.", "success");
    return;
  }

  let unsaved = [];
  let errors = 0;
  let found = 0;
  let unknown = 0;
  let failed = 0;

  try {
    for (const [index, pair] of pendingDistances.entries()) {
      showStatus(`Looking up ${index + 1} of ${pendingDistances.length}: ${pair.from} to ${pair.to}`);
      if (index) await sleep(DELAY_MS);

      try {
        const result = await lookUp(pair);
        unsaved.push(result);
        if (result.km === null) unknown += 1;
        else found += 1;
        errors = 0;
      } catch (error) {
        errors += 1;
        failed += 1;
        console.warn(error);
        if (errors >= MAX_ERRORS) throw error;
      }

      progress.value = index + 1;
      if (unsaved.length >= SAVE_EVERY) {
        await save(unsaved, apiToken);
        unsaved = [];
      }
    }

    await save(unsaved, apiToken);
    await chrome.storage.local.remove("pendingDistances");
    showStatus(
      `Done. Found ${found} distances` + (unknown ? `; the site doesn't know ${unknown} stations.` : ".") +
        (failed ? ` ${failed} lookups failed and will be tried again on the next send.` : "") +
        ` Refresh ${INBOUND_PAGE} to see them.`,
      failed ? "error" : "success",
    );
  } catch (error) {
    await save(unsaved, apiToken).catch(() => {});
    showStatus(`Stopped: ${error.message}. Send the report again to look up the rest.`, "error");
  }
}

run();
