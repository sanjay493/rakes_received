// Runs inside the open page, so it must not use anything from outside this function.
// Returns the largest rake table in the document, and the column headings of every
// table for the "not found" message.
function extractRakeTable() {
  const REQUIRED_COLUMNS = [
    "sr_no", "received_time", "dispatched_time", "transit_time",
    "sttn_from", "sttn_to", "cmdt", "totl_unts", "rake_type",
  ];

  const cellText = (cell) => {
    const copy = cell.cloneNode(true);
    copy.querySelectorAll("br").forEach((br) => br.replaceWith(" "));
    return copy.textContent.replace(/\s+/g, " ").trim();
  };
  // Headings may be spaced differently, such as "SR. NO." or "SR.NO.", so ignore spacing and dots.
  const headingKey = (text) => text.toLowerCase().replace(/[\s._]/g, "");
  const columnName = (cell) => {
    const key = headingKey(cellText(cell));
    return REQUIRED_COLUMNS.find((column) => headingKey(column) === key) || key;
  };

  let best = null;
  const tables = [...document.querySelectorAll("table")];

  for (const table of tables) {
    const rows = [...table.rows];
    const headerIndex = rows.findIndex((row) => {
      const names = [...row.cells].map(columnName);
      return REQUIRED_COLUMNS.every((column) => names.includes(column));
    });
    if (headerIndex === -1) continue;

    const columns = [...rows[headerIndex].cells].map(columnName);
    const srNoIndex = columns.indexOf("sr_no");
    const data = rows
      .slice(headerIndex + 1)
      .filter((row) => row.cells.length === columns.length)
      // Skip headings repeated between pages of a report.
      .filter((row) => columnName(row.cells[srNoIndex]) !== "sr_no")
      .map((row) => [...row.cells].map((cell) => cellText(cell) || null))
      .filter((cells) => cells.some(Boolean));

    if (!best || data.length > best.rows.length) {
      best = { columns, rows: data };
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
