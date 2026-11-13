"""Builds the Excel and PDF downloads of the Commodity Analysis page from app.commodity_analysis_data()."""
import io
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from inbound_exports import NAVY, pdf_styles, put_text, style_row, text_cell

TITLE = "Commodity-Wise Transit Time Analysis"
SLOTS = 4  # Periods in each of the months, weeks and days groups
# (heading, average field, rake count field) of the best-period columns.
BEST = [
    ("Best Monthly", "best_monthly", "best_monthly_count"),
    ("Best Fortnightly", "best_fortnightly", "best_fortnightly_count"),
    ("Best Weekly", "best_weekly", "best_weekly_count"),
]
# Light fills marking the column groups, as on the page.
GROUP_FILLS = ["E3F2FD", "E0F2F1", "FFF3E0", "F3E5F5"]
NOTES = [
    "Average transit time is in hours. Months, weeks and days are counted back from yesterday.",
    "Best Monthly is the lowest monthly average in the last 12 months, Best Fortnightly the lowest "
    "fortnightly average in the last 6 months, and Best Weekly the lowest weekly average in the last 3 months.",
]


def period_groups(data):
    """[(group heading, [period labels], field of the rows)] for the months, weeks and days."""
    return [
        ("Last 4 Months", data["header_months"], "months_data"),
        ("Last 4 Weeks", data["header_weeks"], "weeks_data"),
        ("Last 4 Days", data["header_days"], "days_data"),
    ]


def slots(item, field):
    """The row's SLOTS periods as [(average or None, rakes)], padded when the row has fewer."""
    values = [(slot.get("avg"), slot.get("count") or 0) for slot in item[field][:SLOTS]]
    return values + [(None, 0)] * (SLOTS - len(values))


def best(item):
    return [(item[avg] or None, item[count] or 0) for _, avg, count in BEST]


def rows_of(data):
    """Every source row of the report, in the page's order."""
    return [item for items in data["grouped_data"].values() for item in items]


def summary_line(data):
    rows = rows_of(data)
    commodities = len({item["commodity"] for item in rows})
    sources = len({(item["commodity"], item["source"]) for item in rows})
    parts = [f"Generated {data['generated_at'].strftime('%d-%m-%Y %H:%M')} IST."]
    if data["selected_destination"]:
        parts.append(f"Destination {data['selected_destination']}.")
    parts.append(
        f"{commodities} {'commodity' if commodities == 1 else 'commodities'}, "
        f"{sources} commodity-source {'pair' if sources == 1 else 'pairs'}, {len(rows)} rows."
    )
    if data["customised"]:
        parts.append("Customised: only the ticked commodities and sources are included.")
    return " ".join(parts)


# ------------------ EXCEL ------------------

def build_excel(data):
    """One filterable table: a row per commodity, destination and source, with the average hours and
    the rake count of each period in their own columns so they stay numbers."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Commodity Analysis"
    groups = period_groups(data)
    keys = ["Commodity", "Destination", "Source Station"]
    first_value = len(keys) + 1
    columns = len(keys) + 2 * (SLOTS * len(groups) + len(BEST))

    put_text(sheet, 1, 1, TITLE).font = Font(bold=True, size=14)
    put_text(sheet, 2, 1, summary_line(data))
    for offset, note in enumerate(NOTES):
        put_text(sheet, 3 + offset, 1, note).font = Font(italic=True, color="52606D")

    group_row = 3 + len(NOTES) + 1
    period_row, header = group_row + 1, group_row + 2
    for row in (group_row, period_row, header):
        style_row(sheet, row, columns, bold=True, fill=NAVY, color="FFFFFF")
    for column, heading in enumerate(keys, 1):
        put_text(sheet, header, column, heading)

    centre = Alignment(horizontal="center", vertical="center", wrap_text=True)
    edge = Side(style="thin", color="FFFFFF")
    column = first_value
    group_starts = []
    for heading, labels, _ in groups:
        group_starts.append(column)
        put_text(sheet, group_row, column, heading).alignment = centre
        sheet.merge_cells(start_row=group_row, start_column=column, end_row=group_row, end_column=column + 2 * SLOTS - 1)
        for label in (list(labels) + ["—"] * SLOTS)[:SLOTS]:
            put_text(sheet, period_row, column, label).alignment = centre
            sheet.merge_cells(start_row=period_row, start_column=column, end_row=period_row, end_column=column + 1)
            column += 2
    group_starts.append(column)
    put_text(sheet, group_row, column, "Best Periods").alignment = centre
    sheet.merge_cells(start_row=group_row, start_column=column, end_row=group_row, end_column=column + 2 * len(BEST) - 1)
    for heading, _, _ in BEST:
        put_text(sheet, period_row, column, heading).alignment = centre
        sheet.merge_cells(start_row=period_row, start_column=column, end_row=period_row, end_column=column + 1)
        column += 2
    for column in range(first_value, columns + 1, 2):
        put_text(sheet, header, column, "Avg Hrs").alignment = centre
        put_text(sheet, header, column + 1, "Rakes").alignment = centre
        for row in (group_row, period_row, header):
            sheet.cell(row=row, column=column).border = Border(left=edge)

    def fill_for(column):
        index = sum(column >= start for start in group_starts) - 1
        return PatternFill("solid", fgColor=GROUP_FILLS[index])

    row = header
    for item in rows_of(data):
        row += 1
        put_text(sheet, row, 1, item["commodity"])
        put_text(sheet, row, 2, item["destination"])
        put_text(sheet, row, 3, item["source"]).font = Font(bold=True)
        values = [pair for _, _, field in groups for pair in slots(item, field)] + best(item)
        for index, (average, rakes) in enumerate(values):
            column = first_value + 2 * index
            average_cell = sheet.cell(row=row, column=column, value=average)
            average_cell.number_format = "0.00"
            average_cell.font = Font(bold=True)
            rakes_cell = sheet.cell(row=row, column=column + 1, value=rakes if average is not None else None)
            average_cell.fill = rakes_cell.fill = fill_for(column)

    sheet.freeze_panes = sheet.cell(row=header + 1, column=first_value)
    sheet.auto_filter.ref = f"A{header}:{get_column_letter(columns)}{row}"
    for column, width in enumerate([22, 12, 34], 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for column in range(first_value, columns + 1):
        sheet.column_dimensions[get_column_letter(column)].width = 8.5
    sheet.row_dimensions[period_row].height = 30

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


# ------------------ PDF ------------------

def cell_text(average, rakes):
    """ "45.2 (12)": average hours with the rakes in brackets. Blank when the period has no rakes."""
    return "" if average is None else f"{average:g} ({rakes})"


def block_table(data, items, styles):
    """The table of one commodity and destination: a row per source."""
    groups = period_groups(data)
    top = [text_cell("Source Station", styles["cell_heading"])]
    labels_row = [""]
    for heading, labels, _ in groups:
        top += [text_cell(heading, styles["cell_heading"])] + [""] * (SLOTS - 1)
        labels_row += [text_cell(label, styles["cell_heading"]) for label in (list(labels) + ["—"] * SLOTS)[:SLOTS]]
    for heading, _, _ in BEST:
        top.append(text_cell(heading, styles["cell_heading"]))
        labels_row.append("")
    rows = [top, labels_row]
    for item in items:
        values = [pair for _, _, field in groups for pair in slots(item, field)] + best(item)
        rows.append(
            [text_cell(item["source"], styles["cell_bold"])]
            + [text_cell(cell_text(average, rakes), styles["cell"]) for average, rakes in values]
        )

    navy = colors.HexColor(f"#{NAVY}")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 1), navy),
        ("SPAN", (0, 0), (0, 1)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, 1), 0.4, colors.white),
        ("LINEBELOW", (0, 2), (-1, -1), 0.25, colors.HexColor("#CBD2D9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    column = 1
    for index in range(len(groups)):
        commands.append(("SPAN", (column, 0), (column + SLOTS - 1, 0)))
        if len(rows) > 2:
            commands.append(("BACKGROUND", (column, 2), (column + SLOTS - 1, -1), colors.HexColor(f"#{GROUP_FILLS[index]}")))
        column += SLOTS
    for offset in range(len(BEST)):
        commands.append(("SPAN", (column + offset, 0), (column + offset, 1)))
    if len(rows) > 2:
        commands.append(("BACKGROUND", (column, 2), (-1, -1), colors.HexColor(f"#{GROUP_FILLS[-1]}")))

    # 773 points fit inside the margins of a landscape A4 page.
    table = Table(rows, colWidths=[122] + [43] * (SLOTS * len(groups)) + [45] * len(BEST), repeatRows=2, hAlign="LEFT")
    table.setStyle(TableStyle(commands))
    return table


def build_pdf(data):
    styles = pdf_styles()
    styles["cell_bold"].fontSize, styles["cell_bold"].leading = 7, 8.5
    styles["heading"].keepWithNext = 1

    def page_number(canvas, doc):
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Page {doc.page}")

    story = [
        Paragraph(escape(TITLE), styles["title"]),
        Paragraph(escape(summary_line(data)), styles["body"]),
        Paragraph("Each cell shows the average transit time in hours, with the number of rakes in brackets.", styles["note"]),
    ]
    story.extend(Paragraph(escape(note), styles["note"]) for note in NOTES)
    for (commodity, destination), items in data["grouped_data"].items():
        story.extend([
            Spacer(1, 8),
            Paragraph(escape(f"{commodity} to {destination}"), styles["heading"]),
            block_table(data, items, styles),
        ])

    output = io.BytesIO()
    SimpleDocTemplate(
        output, pagesize=landscape(A4), title=TITLE, author="Rakes Received",
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
    ).build(story, onFirstPage=page_number, onLaterPages=page_number)
    return output.getvalue()
