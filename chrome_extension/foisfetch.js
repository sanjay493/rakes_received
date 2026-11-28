// Requests the Rake trips page runs inside the open FOIS tab, so they use its login. Each function is
// injected on its own, so it must not use anything from outside its body. Neither changes the page on
// screen, and both answer { ok: false, error } instead of throwing.

// The Rakes Received report for BOBSNM1 rakes, loaded and empty, arriving at any of the login's
// stations from from to to (dd-mm-yyyy). Returns { ok: true, columns, rows }.
async function foisReceived(from, to) {
  const failed = {
    ok: false,
    error: "FOIS did not return the Rakes Received report. Check that FOIS is logged in.",
  };
  const cellText = (cell) => {
    const copy = cell.cloneNode(true);
    copy.querySelectorAll("br").forEach((br) => br.replaceWith(" "));
    return copy.textContent.replace(/\s+/g, " ").trim();
  };
  const load = async (url, options) => {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    return response.ok ? new DOMParser().parseFromString(await response.text(), "text/html") : null;
  };

  try {
    // The query form lists the login's stations; its ALL entry covers every one of them.
    const form = await load("/ecbs/JSP/RcvdRakes.jsp");
    const select = form && form.querySelector("select[name=txtSttnTo]");
    const all = select && [...select.options].find((option) => option.textContent.trim() === "ALL");
    if (!all) return failed;

    const page = await load("/ecbs/RouterServlet", {
      method: "POST",
      body: new URLSearchParams({
        operation: "query", suboperation: "rcvdrakes", zonesttnflag: "S",
        txtSttnTo: all.value, txtLocn: all.innerHTML, // Without txtLocn no table comes back
        optSelect: "P", txtDate: from, txtDateTo: to,
        txtSttnFr: "on", txtSttnFrom: "", txtCmdt: "", txtRakeType: "BOBSNM1", optLE: "A",
      }),
    });
    if (!page) return failed;

    const report = page.querySelector("table#example");
    if (report) {
      const [header = [], ...rows] = [...report.rows].map((row) => [...row.cells].map(cellText));
      // A changed layout must be an error: dropping rows would read as "no trips".
      const known = header.some((heading) => heading.toLowerCase().replace(/[\s._]/g, "") === "rakeid");
      if (!known || rows.some((cells) => cells.length !== header.length)) {
        return { ok: false, error: "The Rakes Received report layout was not recognised." };
      }
      return { ok: true, columns: header, rows };
    }
    const none = [...page.querySelectorAll("table")].some(
      (table) => table.rows[0] && cellText(table.rows[0]) === "NO RECORDS FOUND",
    );
    return none ? { ok: true, columns: [], rows: [] } : failed;
  } catch (error) {
    return { ok: false, error: `Could not reach FOIS: ${error.message}` };
  }
}

// "Get RR" for one rake with the agreement left blank: its whole history, 17 cells a trip.
// Returns { ok: true, rows }.
async function foisRR(rakeId) {
  const failed = { ok: false, error: "FOIS did not return the RR report. Check that FOIS is logged in." };
  const clean = (element) => element.textContent.replace(/\s+/g, " ").trim();

  try {
    const response = await fetch("/ecbs/RouterServlet", {
      method: "POST",
      credentials: "same-origin",
      body: new URLSearchParams({
        operation: "query", suboperation: "gwisgfr", txtTrxnFlag: "A", txtCntrId: "", txtRakeId: rakeId,
        txtPerd: "", txtCust: "SAIL", txtAgreDtls: "", txtRprtFlag: "R", txtDateFrom: "", txtDateTo: "",
      }),
    });
    if (!response.ok) return failed;

    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    const text = clean(page.body);
    if (!text.includes("RR DETAILS")) return failed;
    if (text.includes("NO RECORDS FOUND FOR RR")) return { ok: true, rows: [] };

    const report = [...page.querySelectorAll("table")].pop();
    const rows = [...(report ? report.rows : [])]
      .map((row) => [...row.cells].map(clean))
      .filter((cells) => cells.length === 17 && /^\d\d-\d\d-\d{4}$/.test(cells[3]));
    return rows.length ? { ok: true, rows } : { ok: false, error: "The RR report layout was not recognised." };
  } catch (error) {
    return { ok: false, error: `Could not reach FOIS: ${error.message}` };
  }
}
