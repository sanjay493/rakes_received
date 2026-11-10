"""Builds the Excel and PDF downloads of the In-Bound report from app.inbound_data()."""
import io
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = "1F3A5F"
LIGHT = "E8EEF5"
BY_SOURCE_FILL = "F5F8FB"
STABLED_FILL = "FEF3F2"
STABLED_TEXT = "B42318"

NOTES = [
    'Each plant and pellet agent shows all rakes, and how many of them are stabled (status ST). Stabled rakes are included in the rake count.',
    "Km left is the goods distance from the current location to the destination on the Railways' Rates Branch System.",
    '"Unknown" means the distance has not been looked up yet or the site does not know that location.',
    "Source station is the STTN FROM of the rakes; each distance slab lists every source with rakes to any plant or pellet agent.",
]

DETAIL_TITLE = "Rake Details"
ROUTE_TITLE = "Rakes by Commodity, Source, Destination and Loading Date"
ROUTE_NOTE = "Each date column (day-month) counts the rakes loaded that day, from LDNG TIME on FOIS."


# (heading, value for a rake, width in the PDF in points). Values read as on the page.
def km_left(rake):
    return "—" if rake.distance_km is None else round(rake.distance_km)


def status(rake):
    return f"{rake.stts_code} (stabled)" if rake.stabled else rake.stts_code

DETAIL_COLUMNS = [
    ("Rake ID", lambda r: r.rake_id, 80),
    ("Load Name", lambda r: r.load_name, 76),
    ("From", lambda r: r.sttn_from, 38),
    ("To", lambda r: r.sttn_to, 38),
    ("Commodity", lambda r: r.commodity_name, 78),
    ("Units", lambda r: r.totl_unts, 30),
    ("Current Location", lambda r: r.crnt_locn, 48),
    ("Km Left", km_left, 30),
    ("Status", status, 46),
    ("Status Time", lambda r: r.stts_time, 62),
    ("Dept Time", lambda r: r.dept_time, 62),
    ("Transit Time", lambda r: r.transit_time, 40),
    ("Expected Arrival", lambda r: r.expd_arvl_time, 62),
    ("Loco No.", lambda r: r.loco_no, 46),
]


def as_on(data):
    return f"As on {data['imported_at'].strftime('%d-%m-%Y %H:%M')} IST, when the data was received from FOIS"


def title_lines(data):
    title = "Rakes in Transit" + (f" to {data['destination']}" if data["destination"] else "")
    shown = len(data["rakes"])
    summary = f"{as_on(data)}. {shown} rakes to the plants and pellet agents."
    if data["stabled_count"]:
        summary += f" {data['stabled_count']} stabled (status ST)."
    summary += f" Km left is available for {data['rakes_with_distance']} of {shown} rakes."
    return title, summary


# ------------------ EXCEL ------------------

def put_text(sheet, row, column, value):
    """Write FOIS text as text: a value starting with "=" must not become a live formula."""
    cell = sheet.cell(row=row, column=column, value=value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell


def put_count_line(sheet, row, column, line, plants):
    """Write rakes and stabled counts as numbers, two columns per plant, then the totals."""
    for plant in plants:
        sheet.cell(row=row, column=column, value=line["plants"][plant] or None)
        sheet.cell(row=row, column=column + 1, value=line["stabled"][plant] or None)
        column += 2
    sheet.cell(row=row, column=column, value=line["total"])
    sheet.cell(row=row, column=column + 1, value=line["total_stabled"] or None)


def style_row(sheet, row, columns, bold=False, fill=None, color=None):
    for column in range(1, columns + 1):
        cell = sheet.cell(row=row, column=column)
        cell.font = Font(bold=bold, color=color)
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)


def add_report_sheet(workbook, data):
    sheet = workbook.active
    sheet.title = "Rakes in Transit"
    plants = data["plants"]
    first_count = 5  # After Commodity, Distance Left, Source Station Name and Source Code
    columns = first_count - 1 + 2 * (len(plants) + 1)
    title, summary = title_lines(data)

    put_text(sheet, 1, 1, title).font = Font(bold=True, size=14)
    put_text(sheet, 2, 1, summary)

    # Two header rows: each plant spans its Rakes and ST columns.
    top, sub = 4, 5
    for column, heading in enumerate(("Commodity", "Distance Left", "Source Station Name", "Source Code"), 1):
        sheet.cell(row=top, column=column, value=heading)
        sheet.merge_cells(start_row=top, end_row=sub, start_column=column, end_column=column)
    for index, name in enumerate([*plants, "Total"]):
        column = first_count + 2 * index
        sheet.cell(row=top, column=column, value=name)
        sheet.merge_cells(start_row=top, end_row=top, start_column=column, end_column=column + 1)
        sheet.cell(row=sub, column=column, value="Rakes")
        sheet.cell(row=sub, column=column + 1, value="ST")
    for row in (top, sub):
        style_row(sheet, row, columns, bold=True, fill=NAVY, color="FFFFFF")
        for column in range(1, columns + 1):
            sheet.cell(row=row, column=column).alignment = Alignment(horizontal="center", vertical="center")

    def merge_down(first_row, last_row, column, value, bold=False):
        """Write value once and merge it down the rows it covers, like the page does."""
        cell = put_text(sheet, first_row, column, value)
        cell.font = Font(bold=bold)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        if last_row > first_row:
            sheet.merge_cells(start_row=first_row, end_row=last_row, start_column=column, end_column=column)

    def put_source(row, source):
        put_text(sheet, row, 3, source["name"])
        put_text(sheet, row, 4, source["code"])
        put_count_line(sheet, row, first_count, source, plants)

    row = sub + 1
    for commodity in data["report"]["rows"]:
        merge_down(row, row + commodity["row_count"] - 1, 1, commodity["commodity"], bold=True)
        for slab in commodity["slabs"]:
            merge_down(row, row + len(slab["sources"]) - 1, 2, slab["label"])
            for source in slab["sources"]:
                put_source(row, source)
                row += 1
        merge_down(row, row + len(commodity["by_source"]) - 1, 2, "Enroute by Source", bold=True)
        for source in commodity["by_source"]:
            put_source(row, source)
            for column in range(2, columns + 1):
                sheet.cell(row=row, column=column).fill = PatternFill("solid", fgColor=BY_SOURCE_FILL)
            row += 1
        put_text(sheet, row, 2, "Total")
        sheet.merge_cells(start_row=row, end_row=row, start_column=2, end_column=4)
        put_count_line(sheet, row, first_count, commodity["totals"], plants)
        for column in range(2, columns + 1):
            cell = sheet.cell(row=row, column=column)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor=LIGHT)
        row += 1

    if data["report"]["rows"]:
        put_text(sheet, row, 1, "All commodities")
        put_count_line(sheet, row, first_count, data["report"]["totals"], plants)
        style_row(sheet, row, columns, bold=True, fill=NAVY, color="FFFFFF")
        row += 1

    # Stabled counts stand out, except on the dark totals row where red wouldn't be readable.
    for body_row in range(sub + 1, row - 1):
        for column in range(first_count + 1, columns + 1, 2):
            sheet.cell(row=body_row, column=column).font = Font(
                bold=sheet.cell(row=body_row, column=column).font.bold, color=STABLED_TEXT
            )

    row += 1
    for note in NOTES:
        put_text(sheet, row, 1, note).font = Font(italic=True, color="52606D")
        row += 1

    sheet.column_dimensions["A"].width = 26
    sheet.column_dimensions["B"].width = 15
    sheet.column_dimensions["C"].width = 28
    sheet.column_dimensions["D"].width = 10
    for column in range(first_count, columns + 1):
        sheet.column_dimensions[get_column_letter(column)].width = 7
    sheet.freeze_panes = sheet.cell(row=sub + 1, column=first_count)


def add_route_sheet(workbook, data):
    sheet = workbook.create_sheet("Commodity Source Destination")
    routes = data["routes"]
    first_date = 4  # After commodity, source and destination
    columns = first_date + len(routes["dates"])
    headings = ["Commodity", "Source Station (Code)", "Destination Station (Code)"]
    title = ROUTE_TITLE + (f" ({data['destination']})" if data["destination"] else "")
    put_text(sheet, 1, 1, title).font = Font(bold=True, size=14)
    header = 3
    for column, heading in enumerate([*headings, *routes["dates"], "Total"], 1):
        put_text(sheet, header, column, heading)
    style_row(sheet, header, columns, bold=True, fill=NAVY, color="FFFFFF")

    def merge_down(row, count, column, value, bold=False):
        cell = put_text(sheet, row, column, value)
        cell.font = Font(bold=bold)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        if count > 1:
            sheet.merge_cells(start_row=row, end_row=row + count - 1, start_column=column, end_column=column)

    row = header + 1
    for route in routes["rows"]:
        if route["commodity_rows"]:
            merge_down(row, route["commodity_rows"], 1, route["commodity"], bold=True)
        if route["source_rows"]:
            merge_down(row, route["source_rows"], 2, route["source"])
        put_text(sheet, row, 3, route["destination"])
        for column, count in enumerate(route["counts"], first_date):
            sheet.cell(row=row, column=column, value=count or None)
        sheet.cell(row=row, column=columns, value=route["total"]).font = Font(bold=True)
        row += 1

    if routes["rows"]:
        put_text(sheet, row, 1, "All routes")
        for column, count in enumerate(routes["totals"], first_date):
            sheet.cell(row=row, column=column, value=count or None)
        sheet.cell(row=row, column=columns, value=routes["total"])
        style_row(sheet, row, columns, bold=True, fill=NAVY, color="FFFFFF")
        row += 1
    put_text(sheet, row + 1, 1, ROUTE_NOTE).font = Font(italic=True, color="52606D")

    for column, width in enumerate([22, 34, 34], 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for column in range(first_date, columns + 1):
        sheet.column_dimensions[get_column_letter(column)].width = 8
    sheet.freeze_panes = sheet.cell(row=header + 1, column=first_date)


def add_detail_sheet(workbook, data):
    sheet = workbook.create_sheet(DETAIL_TITLE)
    headings = [heading for heading, _, _ in DETAIL_COLUMNS]
    status_column = headings.index("Status") + 1
    put_text(sheet, 1, 1, DETAIL_TITLE).font = Font(bold=True, size=14)
    header = 3
    for column, heading in enumerate(headings, 1):
        put_text(sheet, header, column, heading)
    style_row(sheet, header, len(headings), bold=True, fill=NAVY, color="FFFFFF")

    for row, rake in enumerate(data["rakes"], header + 1):
        for column, (_, value, _) in enumerate(DETAIL_COLUMNS, 1):
            put_text(sheet, row, column, value(rake))
        if rake.stabled:
            # Shaded row, with the status in bold red, as on the page.
            style_row(sheet, row, len(headings), fill=STABLED_FILL)
            sheet.cell(row=row, column=status_column).font = Font(bold=True, color=STABLED_TEXT)

    last_row = header + len(data["rakes"])
    sheet.freeze_panes = sheet.cell(row=header + 1, column=1)
    sheet.auto_filter.ref = f"A{header}:{get_column_letter(len(headings))}{last_row}"
    for column, heading in enumerate(headings, 1):
        longest = max(
            [len(heading)] + [len(str(value)) for value in (
                sheet.cell(row=row, column=column).value for row in range(header + 1, last_row + 1)
            ) if value is not None]
        )
        sheet.column_dimensions[get_column_letter(column)].width = min(longest + 2, 30)


def build_excel(data):
    workbook = Workbook()
    add_report_sheet(workbook, data)
    add_route_sheet(workbook, data)
    add_detail_sheet(workbook, data)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


# ------------------ PDF ------------------

def count_text(rakes, stabled):
    """The same "5 (2 ST)" wording as the page. Blank when there are no rakes."""
    if not rakes:
        return ""
    return f"{rakes} ({stabled} ST)" if stabled else str(rakes)


def pdf_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=15, alignment=0, spaceAfter=4),
        "heading": ParagraphStyle("heading", parent=base["Heading3"], fontSize=11, spaceAfter=4),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=9, leading=12),
        "note": ParagraphStyle("note", parent=base["BodyText"], fontSize=7.5, leading=10,
                               textColor=colors.HexColor("#52606D")),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontSize=7, leading=8.5),
        "cell_heading": ParagraphStyle("cell_heading", parent=base["BodyText"], fontSize=6.5, leading=8,
                                       fontName="Helvetica-Bold", textColor=colors.white),
        "cell_stabled": ParagraphStyle("cell_stabled", parent=base["BodyText"], fontSize=7, leading=8.5,
                                       fontName="Helvetica-Bold", textColor=colors.HexColor(f"#{STABLED_TEXT}")),
        "cell_bold": ParagraphStyle("cell_bold", parent=base["BodyText"], fontSize=8, leading=10,
                                    fontName="Helvetica-Bold"),
    }


def text_cell(value, style):
    """FOIS text in a table cell. Escaped because reportlab reads Paragraphs as markup."""
    return Paragraph(escape("" if value is None else str(value)), style)


# A merged PDF cell can't run over a page break, so long merges are made in blocks of this many rows.
# Every row holds the value and only the first of each block shows, so the name is on every page.
MAX_PDF_SPAN = 10


def pieces(count):
    """A run of count rows cut into blocks of at most MAX_PDF_SPAN rows: [10, 10, 3] for 23."""
    return [min(MAX_PDF_SPAN, count - start) for start in range(0, count, MAX_PDF_SPAN)]


def merge_blocks(column, first_row, blocks):
    """reportlab commands merging a column down each block of rows in turn, starting at first_row."""
    commands = []
    for size in blocks:
        last_row = first_row + size - 1
        if size > 1:
            commands.append(("SPAN", (column, first_row), (column, last_row)))
        commands.append(("VALIGN", (column, first_row), (column, last_row), "TOP"))
        first_row = last_row + 1
    return commands


def merged_down(column, first_row, count):
    """reportlab commands merging a column down count rows, like the page does."""
    return merge_blocks(column, first_row, pieces(count))


def commodity_blocks(groups):
    """Blocks for the commodity column from its groups of rows (each slab, the by-source rows, the
    total). Whole pieces of groups are added up to MAX_PDF_SPAN rows, so a block never ends inside a
    merged distance cell; otherwise the table could find no row to break the page at."""
    blocks = []
    for size in (piece for group in groups for piece in pieces(group)):
        if blocks and blocks[-1] + size <= MAX_PDF_SPAN:
            blocks[-1] += size
        else:
            blocks.append(size)
    return blocks


def report_table(data, styles):
    plants = data["plants"]
    rows = [["Commodity", "Distance Left", "Source Station Name", "Code", *plants, "Total"]]
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{NAVY}")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD2D9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]

    def add_line(first, second, line, *style, name="", code=""):
        rows.append([first, second, text_cell(name, styles["cell"]), code,
                     *[count_text(line["plants"][p], line["stabled"][p]) for p in plants],
                     count_text(line["total"], line["total_stabled"])])
        for command in style:
            commands.append((command[0], (0, len(rows) - 1), (-1, len(rows) - 1), *command[1:]))

    for commodity in data["report"]["rows"]:
        first_row = len(rows)
        name = text_cell(commodity["commodity"], styles["cell_bold"])
        groups = [len(slab["sources"]) for slab in commodity["slabs"]] + [len(commodity["by_source"]), 1]
        commands += merge_blocks(0, first_row, commodity_blocks(groups))
        for slab in commodity["slabs"]:
            commands += merged_down(1, len(rows), len(slab["sources"]))
            for source in slab["sources"]:
                add_line(name, slab["label"], source, name=source["name"], code=source["code"])
        commands += merged_down(1, len(rows), len(commodity["by_source"]))
        for source in commodity["by_source"]:
            add_line(name, text_cell("Enroute by Source", styles["cell_bold"]), source,
                     name=source["name"], code=source["code"])
            commands.append(("BACKGROUND", (1, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor(f"#{BY_SOURCE_FILL}")))
        add_line(name, "Total", commodity["totals"])
        last = len(rows) - 1
        commands += [
            ("SPAN", (1, last), (3, last)),
            ("BACKGROUND", (1, last), (-1, last), colors.HexColor(f"#{LIGHT}")),
            ("FONTNAME", (1, last), (-1, last), "Helvetica-Bold"),
            ("LINEBELOW", (0, last), (-1, last), 0.75, colors.HexColor(f"#{NAVY}")),
        ]

    add_line("All commodities", "", data["report"]["totals"],
             ("BACKGROUND", colors.HexColor(f"#{NAVY}")), ("TEXTCOLOR", colors.white), ("FONTNAME", "Helvetica-Bold"))

    # Fits the 762 points inside the landscape A4 page frame; Total is wider for its bold figures.
    table = Table(rows, colWidths=[86, 56, 110, 34] + [420 / len(plants)] * len(plants) + [56], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(commands))
    return table


def route_table(data, styles):
    routes = data["routes"]
    rows = [[text_cell(heading, styles["cell_heading"]) for heading in
             ["Commodity", "Source Station (Code)", "Destination Station (Code)"]] + [*routes["dates"], "Total"]]
    spans = []
    for index, route in enumerate(routes["rows"]):
        # Every row holds the commodity and source; merging shows them once. Commodity blocks are built
        # from whole source pieces, so the table can always break the page between blocks.
        if route["commodity_rows"]:
            commodity_cell = text_cell(route["commodity"], styles["cell_bold"])
            group = routes["rows"][index:index + route["commodity_rows"]]
            sources = [row["source_rows"] for row in group if row["source_rows"]]
            spans += merge_blocks(0, len(rows), commodity_blocks(sources))
        if route["source_rows"]:
            source_cell = text_cell(route["source"], styles["cell"])
            spans += merged_down(1, len(rows), route["source_rows"])
        rows.append([commodity_cell, source_cell, text_cell(route["destination"], styles["cell"]),
                     *[count or "" for count in route["counts"]], route["total"]])
        if route["commodity_rows"]:
            spans.append(("LINEABOVE", (0, len(rows) - 1), (-1, len(rows) - 1), 0.75, colors.HexColor(f"#{NAVY}")))
    rows.append(["All routes", "", "", *[count or "" for count in routes["totals"]], routes["total"]])
    # Date columns share what is left of the 762 points inside the page frame.
    date_width = min(45, 412 / len(routes["dates"]))
    table = Table(rows, colWidths=[80, 135, 135] + [date_width] * len(routes["dates"]) + [40],
                  repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(spans + [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{NAVY}")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD2D9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("FONTNAME", (-1, 1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(f"#{NAVY}")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    return table


def detail_table(data, styles):
    # Paragraphs, so long headings wrap inside their column.
    rows = [[text_cell(heading, styles["cell_heading"]) for heading, _, _ in DETAIL_COLUMNS]]
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{NAVY}")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD2D9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for rake in data["rakes"]:
        cells = []
        for heading, value, _ in DETAIL_COLUMNS:
            style = styles["cell_stabled"] if heading == "Status" and rake.stabled else styles["cell"]
            cells.append(text_cell(value(rake), style))
        rows.append(cells)
        if rake.stabled:
            commands.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor(f"#{STABLED_FILL}")))

    table = Table(rows, colWidths=[width for _, _, width in DETAIL_COLUMNS], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(commands))
    return table


def build_pdf(data):
    styles = pdf_styles()
    title, summary = title_lines(data)

    def page_number(canvas, doc):
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Page {doc.page}")

    story = [Paragraph(escape(title), styles["title"]), Paragraph(escape(summary), styles["body"]), Spacer(1, 8)]
    if data["report"]["rows"]:
        story.append(report_table(data, styles))
    else:
        story.append(Paragraph("No rakes in this list are going to the plants or pellet agents.", styles["body"]))
    story.append(Spacer(1, 6))
    story.extend(Paragraph(escape(note), styles["note"]) for note in NOTES)
    if data["routes"]["rows"]:
        story.extend([
            PageBreak(),
            Paragraph(escape(ROUTE_TITLE + (f" ({data['destination']})" if data["destination"] else "")), styles["heading"]),
            route_table(data, styles),
            Spacer(1, 6),
            Paragraph(escape(ROUTE_NOTE), styles["note"]),
        ])
    story.extend([PageBreak(), Paragraph(DETAIL_TITLE, styles["heading"])])
    story.append(detail_table(data, styles))

    output = io.BytesIO()
    SimpleDocTemplate(
        output, pagesize=landscape(A4), title=title, author="Rakes Received",
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
    ).build(story, onFirstPage=page_number, onLaterPages=page_number)
    return output.getvalue()
