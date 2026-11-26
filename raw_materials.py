"""Rules of the Raw Material Status page: which rakes it shows, what a sub-commodity entry may hold, its
summary, and which rake an entry belongs to after a new In-Bound list."""
import re
from itertools import zip_longest

# (section, the commodity names it takes in), in page order
SECTIONS = (
    ("Iron Ore", ("IRON ORE",)),
    ("Coal", ("COAL", "NON PROGRAMMED COAL")),
    ("Imported Coal", ("IMPORTED COAL",)),
)
SUMMARY_SECTIONS = ("Coal", "Imported Coal", "Iron Ore")  # Order of the summary table
# These sub-commodities lead their plant's rows in the summary, in this order; others follow by name.
SUB_COMMODITY_ORDER = ("PCC", "MCC", "MIDLING", "MIDDLING")
# (plant, section) whose rake list shows each rake's siding: ISP takes imported coal at both IISD and BCME.
SIDING_SHOWN = {("ISP", "Imported Coal")}
NOT_ENTERED = "Not entered"
MAX_NAME = 80
TONNES_PER_WAGON = 70


def section_of(commodity):
    """The section a commodity name belongs to, or None."""
    wanted = (commodity or "").strip().upper()
    return next((section for section, names in SECTIONS if wanted in names), None)


def wagon_count(units):
    """The wagons in a TOTL UNTS value ("58+1" is 58 wagons), or None if it can't be read."""
    match = re.match(r"\s*([0-9]{1,4})\b", units or "")
    return int(match[1]) if match else None


def _text(value):
    """A rake field as trimmed text. A list being imported may hold values that aren't text yet."""
    return str(value or "").strip()


def trip_key(rake):
    """What identifies one loaded trip: Rake ID, source and loading time."""
    return _text(rake.rake_id), _text(rake.sttn_from).upper(), _text(rake.ldng_time)


def check_lines(names, counts, wagons, known):
    """Check the form's sub-commodity and wagon lines against the rake's wagons (None if unknown).
    known are the names already used, whose spelling is reused. Returns (lines, errors)."""
    spellings = {name.casefold(): name for name in known}
    lines, errors, seen = [], [], set()
    for name, count in zip_longest(names, counts, fillvalue=""):
        name = " ".join(name.split())[:MAX_NAME].strip()
        count = count.strip()
        if not name and not count:
            continue
        number = int(count) if re.fullmatch(r"[0-9]{1,4}", count) else 0
        if not name:
            errors.append("Enter a sub-commodity on every line.")
        elif name.casefold() in seen:
            errors.append(f"{name} is entered twice.")
        if number <= 0:
            errors.append("Wagons must be a whole number above 0.")
        seen.add(name.casefold())
        lines.append((spellings.get(name.casefold(), name), number))

    if not lines:
        errors.append("Enter at least one sub-commodity.")
    elif not errors and wagons is not None:
        total = sum(number for _, number in lines)
        if total != wagons:
            errors.append(f"Wagons add up to {total}, but the rake has {wagons}.")
    return lines, list(dict.fromkeys(errors))


def _line_order(line):
    name = line["name"].upper()
    rank = SUB_COMMODITY_ORDER.index(name) if name in SUB_COMMODITY_ORDER else len(SUB_COMMODITY_ORDER)
    return line["name"] == NOT_ENTERED, rank, line["name"].casefold()


def summary(rakes, plants):
    """Rakes, wagons and tonnes of each sub-commodity, by section and then plant. A rake counts under each
    of its sub-commodities as that part's share of its wagons (24 of 58 wagons is 24/58 of a rake), so it
    adds up to one rake in its section's totals. Tonnes are wagons x TONNES_PER_WAGON. section_rows on a
    section's first block is how many table rows the section takes (lines and totals), 0 on the rest."""
    blocks = []
    for section in SUMMARY_SECTIONS:
        first = len(blocks)
        for plant in plants:
            group = [rake for rake in rakes if rake.plant == plant and rake.section == section]
            if not group:
                continue
            lines = {}
            total = 0
            for rake in group:
                entered = sum(count for _, count in rake.parts)
                total += rake.wagons if rake.wagons is not None else entered
                for name, count in rake.parts or [(NOT_ENTERED, rake.wagons or 0)]:
                    line = lines.setdefault(name.casefold(), {"name": name, "rakes": 0, "wagons": 0})
                    # Of the wagons entered, so the shares make one rake even if FOIS has since changed its count.
                    line["rakes"] += count / entered if rake.parts else 1
                    line["wagons"] += count
            ordered = sorted(lines.values(), key=_line_order)
            for line in ordered:
                line["tonnes"] = line["wagons"] * TONNES_PER_WAGON
            blocks.append({"plant": plant, "section": section, "rakes": len(group), "wagons": total,
                           "tonnes": total * TONNES_PER_WAGON, "lines": ordered, "section_rows": 0})
        if len(blocks) > first:
            blocks[first]["section_rows"] = sum(len(block["lines"]) + 1 for block in blocks[first:])
    return blocks


def _route(rake_id, source, destination):
    return _text(rake_id), _text(source).upper(), _text(destination).upper()


def moved_entries(trips, previous, latest):
    """FOIS can revise a rake's loading time while it is still at loading. trips are the saved entries'
    (rake_id, source, destination, loading time); previous and latest are the rakes of the list before
    and the new list. Returns {(rake_id, source, old loading time): new loading time} for the entries
    whose rake had not departed in the list before and now shows another loading time."""
    waiting = {
        (*_route(rake.rake_id, rake.sttn_from, rake.sttn_to), _text(rake.ldng_time))
        for rake in previous if not _text(rake.dept_time)
    }
    listed = {}
    for rake in latest:
        listed.setdefault(_route(rake.rake_id, rake.sttn_from, rake.sttn_to), set()).add(_text(rake.ldng_time))

    moves = {}
    for rake_id, source, destination, loaded in trips:
        times = listed.get((rake_id, source, destination), set())
        if rake_id and (rake_id, source, destination, loaded) in waiting and loaded not in times:
            new_times = sorted(filter(None, times))
            if new_times:
                moves[(rake_id, source, loaded)] = new_times[-1]
    return moves
