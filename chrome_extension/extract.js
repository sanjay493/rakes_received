// Runs inside the open page, so it must not use anything from outside this function.
// Returns the largest known report table in the document, and the column headings of
// every table for the "not found" message.
function extractRakeTable() {
  // The columns that identify each report.
  const REPORTS = {
    received: [
      "sr_no", "received_time", "dispatched_time", "transit_time",
      "sttn_from", "sttn_to", "cmdt", "totl_unts", "rake_type",
    ],
    inbound: ["crnt_locn", "stts_time", "sttn_from", "sttn_to", "rake_id", "expd_arvltime"],
  };

  const cellText = (cell) => {
    const copy = cell.cloneNode(true);
    copy.querySelectorAll("br").forEach((br) => br.replaceWith(" "));
    return copy.textContent.replace(/\s+/g, " ").trim();
  };
  // Headings may be spaced differently, such as "SR. NO." or "SR.NO.", so ignore spacing and dots.
  const headingKey = (text) => text.toLowerCase().replace(/[\s._]/g, "");
  const knownColumns = Object.values(REPORTS).flat();
  const columnName = (cell) => {
    const key = headingKey(cellText(cell));
    return knownColumns.find((column) => headingKey(column) === key) || key;
  };
  const reportFor = (row) => {
    const keys = [...row.cells].map((cell) => headingKey(cellText(cell)));
    return Object.keys(REPORTS).find((report) =>
      REPORTS[report].every((column) => keys.includes(headingKey(column))),
    );
  };

  let best = null;
  const tables = [...document.querySelectorAll("table")];

  for (const table of tables) {
    const rows = [...table.rows];
    const headerIndex = rows.findIndex(reportFor);
    if (headerIndex === -1) continue;

    const columns = [...rows[headerIndex].cells].map(columnName);
    const srNoIndex = columns.indexOf("sr_no");
    const data = rows
      .slice(headerIndex + 1)
      .filter((row) => row.cells.length === columns.length)
      // Skip headings repeated between pages of a report.
      .filter((row) => srNoIndex === -1 || columnName(row.cells[srNoIndex]) !== "sr_no")
      .map((row) => [...row.cells].map((cell) => cellText(cell) || null))
      .filter((cells) => cells.some(Boolean));

    if (!best || data.length > best.rows.length) {
      best = { report: reportFor(rows[headerIndex]), columns, rows: data };
    }
  }

  return {
    table: best,
    tableCount: tables.length,
    headings: tables
      .map((table) => (table.rows[0] ? [...table.rows[0].cells].map(cellText).join(", ") : ""))
      .filter(Boolean)
      .slice(0, 5),
  };
}
