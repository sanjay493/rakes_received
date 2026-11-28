// The Rake trips page's calculations, kept free of the page and of Chrome so node can check them.
// From and To are yyyy-mm-dd, as date inputs give them; FOIS dates are dd-mm-yyyy.

// A Rake ID in upper case with single spaces, or "" if there isn't one.
function cleanRakeId(text) {
  return String(text || "").replace(/\s+/g, " ").trim().toUpperCase();
}

// The period cut into calendar months: [{ from, to }] as dd-mm-yyyy. Empty if there is no period.
function monthRanges(from, to) {
  if (!from || !to || from > to) return [];
  const fois = (iso) => iso.split("-").reverse().join("-");
  const pad = (number) => String(number).padStart(2, "0");

  const ranges = [];
  let start = from;
  while (start <= to) {
    const [year, month] = start.split("-").map(Number);
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const monthEnd = `${year}-${pad(month)}-${pad(lastDay)}`;
    ranges.push({ from: fois(start), to: fois(monthEnd < to ? monthEnd : to) });
    start = month === 12 ? `${year + 1}-01-01` : `${year}-${pad(month + 1)}-01`;
  }
  return ranges;
}

// "Get RR" rows whose invoice date (the 4th cell) is in the period, both ends included.
function rrRowsInPeriod(rows, from, to) {
  return rows.filter((row) => {
    const date = String(row[3]).split("-").reverse().join("-");
    return date >= from && date <= to;
  });
}

function rakeIdColumn(columns) {
  return columns.findIndex((column) => String(column).toLowerCase().replace(/[\s._]/g, "") === "rakeid");
}

// Rakes Received rows of the chosen rakes (a Set of cleaned IDs), or all of them when ids is null.
function receivedRowsFor(columns, rows, ids) {
  if (!ids) return rows;
  const column = rakeIdColumn(columns);
  return rows.filter((row) => ids.has(cleanRakeId(row[column])));
}

// The Rake IDs in the rows, each once, in the order first seen.
function rakeIdsIn(columns, rows) {
  const column = rakeIdColumn(columns);
  return [...new Set(rows.map((row) => cleanRakeId(row[column])).filter(Boolean))];
}

// Chosen rakes that got no trips, leaving out those whose request failed.
function rakesWithoutTrips(chosen, withTrips, failed) {
  return chosen.filter((id) => !withTrips.has(id) && !failed.has(id));
}

if (typeof module !== "undefined") {
  module.exports = { cleanRakeId, monthRanges, rrRowsInPeriod, receivedRowsFor, rakeIdsIn, rakesWithoutTrips };
}
