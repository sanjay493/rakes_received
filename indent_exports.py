"""Excel and PDF reports of the Pending Indents page, built from indents_data()."""
import io
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from inbound_exports import NAVY, pdf_styles, put_text, style_row, text_cell

TITLE = "Pending Indents"
FLAG_FILL = "FDE8E6"  # A source where SAIL has waited while others were loaded, as on the page


def as_on(data):
    return f"ODR list of {data['imported_at'].strftime('%d-%m-%Y %H:%M')}"


def summary_line(data):
    summary = data["summary"]
    oldest = summary["oldest"]
    parts = [
        f"SAIL rakes pending: {summary['inward_pending']} raw material, {summary['steel_pending']} steel going out",
        f"supplied and under loading: {summary['supplied']}",
        f"part supplied: {summary['part']}",
    ]
    if oldest:
        parts.append(
            f"oldest pending: {oldest['source']}, {oldest['demand_date'].strftime('%d-%m-%Y')} ({oldest['age']} days)"
        )
    return "; ".join(parts) + "."


def dash(value):
    return "—" if value is None else value


def tables(data):
    """The three tables as (sheet name, heading, note, column headings, PDF column widths in mm,
    rows, flagged row numbers). Counts of zero are left blank, as on the page."""
    buckets = data["buckets"]
    bucket_headings = [f"{bucket} days" for bucket in buckets]

    def counts(row):
        return [row["buckets"][bucket] or None for bucket in buckets]

    sources = [
        [
            row["commodity"], row["source"], ", ".join(row["wagon_types"]), row["pending"], *counts(row),
            dash(row["oldest"]), row["supplied"] or None, row["part"] or None,
            ", ".join(f"{party} {pending}" for party, pending in row["others"]) or "—",
            dash(row["loaded_sail"]), dash(row["loaded_others"]),
        ]
        for row in data["sources"]
    ]
    plants = [
        [
            row["plant"], row["commodity"], row["pending"] or None, row["in_transit"] or None,
            dash(row["per_day"]), dash(row["yesterday"]),
        ]
        for row in data["plants"]
    ]
    steel = [
        [row["plant"], row["wagon"], row["pending"], *counts(row), dash(row["oldest"]), row["supplied"] or None]
        for row in data["steel"]
    ]
    loaded = f"Loaded in {data['loaded_days']} days"
    return [
        (
            "Sources", "Pending at each source",
            f"A shaded row is a source where a SAIL indent has waited over 7 days while rakes were loaded there "
            f"for other parties in the last {data['loaded_days']} days. A dash under Loaded means no All-India "
            "In-Bound list was sent in those days.",
            ["Commodity", "Source", "Wagon", "SAIL pending", *bucket_headings, "Oldest (days)", "Supplied",
             "Part supplied", "Others pending", f"{loaded}: SAIL", f"{loaded}: others"],
            [26, 46, 28, 15, 13, 13, 13, 13, 15, 15, 15, 28, 16, 16],
            sources, {number for number, row in enumerate(data["sources"]) if row["flag"]},
        ),
        (
            "Plants", "Pipeline to each plant",
            "A two-point indent counts for its first destination. In transit is from the latest In-Bound list.",
            ["Plant", "Commodity", "Pending indents", "In transit",
             f"Received per day ({data['received_days']} days)", "Received yesterday"],
            [30, 70, 30, 30, 40, 35],
            plants, set(),
        ),
        (
            "Steel", "Steel indents at each plant", "",
            ["Plant", "Wagon", "Pending", *bucket_headings, "Oldest (days)", "Supplied"],
            [80, 40, 20, 18, 18, 18, 18, 25, 20],
            steel, set(),
        ),
    ]


# ------------------ EXCEL ------------------

def build_excel(data):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, heading, note, headings, widths, rows, flagged in tables(data):
        sheet = workbook.create_sheet(name)
        columns = len(headings)
        put_text(sheet, 1, 1, f"{TITLE}: {heading}").font = Font(bold=True, size=14)
        put_text(sheet, 2, 1, as_on(data))
        put_text(sheet, 3, 1, summary_line(data))
        if note:
            put_text(sheet, 4, 1, note).font = Font(italic=True, color="52606D")

        header = 6
        for column, text in enumerate(headings, 1):
            cell = put_text(sheet, header, column, text)
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        style_row(sheet, header, columns, bold=True, fill=NAVY, color="FFFFFF")
        sheet.row_dimensions[header].height = 32

        for number, values in enumerate(rows):
            row = header + 1 + number
            for column, value in enumerate(values, 1):
                if isinstance(value, str):
                    put_text(sheet, row, column, value)
                else:
                    sheet.cell(row=row, column=column, value=value)
            if number in flagged:
                for column in range(1, columns + 1):
                    sheet.cell(row=row, column=column).fill = PatternFill("solid", fgColor=FLAG_FILL)

        sheet.freeze_panes = sheet.cell(row=header + 1, column=1)
        if rows:
            sheet.auto_filter.ref = f"A{header}:{get_column_letter(columns)}{header + len(rows)}"
        for column, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(column)].width = max(width / 2.2, 9)

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


# ------------------ PDF ------------------

def pdf_table(headings, widths, rows, flagged, styles):
    body = [[text_cell(text, styles["cell_heading"]) for text in headings]]
    body.extend([text_cell(value, styles["cell"]) for value in values] for values in rows)
    table = Table(body, colWidths=[width * mm for width in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{NAVY}")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C5CDD6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    style.extend(
        ("BACKGROUND", (0, number + 1), (-1, number + 1), colors.HexColor(f"#{FLAG_FILL}")) for number in flagged
    )
    table.setStyle(TableStyle(style))
    return table


def build_pdf(data):
    styles = pdf_styles()

    def page_number(canvas, doc):
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Page {doc.page}")

    story = [
        Paragraph(escape(TITLE), styles["title"]),
        Paragraph(escape(as_on(data)), styles["body"]),
        Paragraph(escape(summary_line(data)), styles["body"]),
    ]
    for _, heading, note, headings, widths, rows, flagged in tables(data):
        story.extend([Spacer(1, 8), Paragraph(escape(heading), styles["heading"])])
        if rows:
            story.append(pdf_table(headings, widths, rows, flagged, styles))
        else:
            story.append(Paragraph("Nothing to show in this list.", styles["body"]))
        if note:
            story.append(Paragraph(escape(note), styles["note"]))

    output = io.BytesIO()
    SimpleDocTemplate(
        output, pagesize=landscape(A4), title=TITLE, author="Rakes Received",
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
    ).build(story, onFirstPage=page_number, onLaterPages=page_number)
    return output.getvalue()
