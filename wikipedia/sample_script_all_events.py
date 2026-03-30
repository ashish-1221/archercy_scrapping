import argparse
import csv
import importlib.util
import tempfile
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


DEFAULT_URL = "https://en.wikipedia.org/wiki/Archery_at_the_2024_Summer_Olympics"
DEFAULT_OUTPUT = "competition_results_all_events.csv"
SCRIPT_DIR = Path(__file__).resolve().parent

FIELDNAMES = [
    "championship_name",
    "event",
    "round_name",
    "round",
    "player_a",
    "player_b",
    "score_a",
    "score_b",
    "winner",
]


def clean_text(node):
    if not node:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def fetch_html(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; archery-scraper/1.0)",
        },
    )
    with urlopen(request) as response:
        return response.read().decode("utf-8")


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_supporting_extractors():
    return {
        "individual": load_module(
            "sample_script_individual",
            str(SCRIPT_DIR / "sample_script_individual.py"),
        ),
        "team": load_module(
            "sample_script_team",
            str(SCRIPT_DIR / "sample_script_team.py"),
        ),
        "mixed": load_module(
            "sample_script_mixed_team",
            str(SCRIPT_DIR / "sample_script_mixed_team.py"),
        ),
    }


def normalize_header(text):
    lowered = text.strip().lower()
    return "".join(char for char in lowered if char.isalnum())


def build_table_grid(table):
    rows = []
    spans = {}

    for row_index, tr in enumerate(table.find_all("tr")):
        logical_row = []
        column_index = 0
        direct_cells = tr.find_all(["th", "td"], recursive=False)

        for cell in direct_cells:
            while (row_index, column_index) in spans:
                logical_row.append(spans[(row_index, column_index)])
                column_index += 1

            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))

            for offset in range(colspan):
                logical_row.append(cell)
                for span_offset in range(1, rowspan):
                    spans[(row_index + span_offset, column_index + offset)] = cell

            column_index += colspan

        while (row_index, column_index) in spans:
            logical_row.append(spans[(row_index, column_index)])
            column_index += 1

        rows.append({
            "cells": logical_row,
            "has_data_cells": any(cell.name == "td" for cell in direct_cells),
        })

    return rows


def find_event_column_index(table_rows):
    header_rows = []
    for row in table_rows:
        if row["has_data_cells"]:
            break
        header_rows.append(row["cells"])

    if not header_rows:
        return None

    max_columns = max(len(row) for row in header_rows)
    for column_index in range(max_columns):
        header_text = " ".join(
            clean_text(row[column_index])
            for row in header_rows
            if column_index < len(row)
        )
        normalized = normalize_header(header_text)
        if normalized in {"event", "eventdate", "dateevent"}:
            return column_index

    return None


def is_internal_wiki_link(link):
    href = (link or {}).get("href", "")
    return bool(href) and href.startswith("/wiki/") and not href.startswith("/wiki/Help:")


def is_event_page_link(link):
    if not is_internal_wiki_link(link):
        return False

    href = link.get("href", "").lower()
    title = (link.get("title") or "").lower()
    text = clean_text(link).lower()

    if "archery_at_the" in href or "archery at the" in title:
        return True

    return any(keyword in text for keyword in ("individual", "team", "mixed"))


def extract_event_link_from_row(row_cells, event_column_index):
    preferred_cells = []
    preferred_event_cell_id = None
    if event_column_index is not None and event_column_index < len(row_cells):
        preferred_cell = row_cells[event_column_index]
        preferred_cells.append(preferred_cell)
        preferred_event_cell_id = id(preferred_cell)

    preferred_cells.extend(row_cells)

    seen_cells = set()
    for cell in preferred_cells:
        cell_id = id(cell)
        if cell_id in seen_cells:
            continue
        seen_cells.add(cell_id)

        links = cell.find_all("a")
        if preferred_event_cell_id == cell_id:
            for link in links:
                if is_event_page_link(link):
                    return link

        for link in links:
            title = link.get("title") or ""
            if title.startswith("Archery at the"):
                return link

    return None


def find_schedule_table(schedule_heading):
    fallback_table = None

    for tag in schedule_heading.find_next_siblings():
        tag_name = getattr(tag, "name", None)

        if tag_name == "div" and tag.find(["h2", "h3"]):
            break

        if tag_name != "table":
            continue

        if fallback_table is None:
            fallback_table = tag

        table_rows = build_table_grid(tag)
        if find_event_column_index(table_rows) is not None:
            return tag

    return fallback_table


def extract_schedule_events(championship_url):
    soup = BeautifulSoup(fetch_html(championship_url), "html.parser")
    championship_name = clean_text(soup.find("h1"))

    schedule = soup.find(id="Competition_schedule") or soup.find(id="Schedule")
    if not schedule:
        raise ValueError("Schedule section not found")

    schedule_heading = schedule.find_parent("div", class_="mw-heading") or schedule.parent
    schedule_table = find_schedule_table(schedule_heading)
    if schedule_table is None:
        raise ValueError("Competition schedule table not found")

    events = []
    seen_titles = set()
    table_rows = build_table_grid(schedule_table)
    event_column_index = find_event_column_index(table_rows)

    for row in table_rows:
        if not row["has_data_cells"]:
            continue

        event_link = extract_event_link_from_row(row["cells"], event_column_index)
        if not event_link:
            continue

        page_title = event_link.get("title")
        event_name = clean_text(event_link)
        if not page_title or page_title in seen_titles:
            continue

        seen_titles.add(page_title)
        events.append({
            "championship_name": championship_name,
            "event": event_name,
            "page_title": page_title,
            "url": urljoin(championship_url, event_link.get("href", "")),
        })

    return events


def choose_extractor(page_title, extractors):
    normalized = page_title.lower()

    if "mixed team" in normalized:
        return extractors["mixed"]
    if "team" in normalized:
        return extractors["team"]
    if "individual" in normalized:
        return extractors["individual"]

    raise ValueError(f"No extractor available for page title: {page_title}")


def write_temp_html(directory, filename, html):
    path = directory / filename
    path.write_text(html, encoding="utf-8")
    return path


def safe_filename(page_title):
    filename = page_title.lower()
    replacements = {
        " ": "_",
        "–": "_",
        "'": "",
        "/": "_",
    }
    for source, target in replacements.items():
        filename = filename.replace(source, target)
    return f"{filename}.html"


def build_rows(championship_url):
    extractors = load_supporting_extractors()
    schedule_events = extract_schedule_events(championship_url)
    rows = []

    with tempfile.TemporaryDirectory(prefix="archery_events_") as tmp_dir:
        temp_dir = Path(tmp_dir)

        for event in schedule_events:
            extractor = choose_extractor(event["page_title"], extractors)
            event_html = fetch_html(event["url"])
            event_file = write_temp_html(temp_dir, safe_filename(event["page_title"]), event_html)
            event_rows = extractor.extract_bracket(str(event_file))

            for row in event_rows:
                rows.append({
                    "championship_name": event["championship_name"],
                    "event": event["event"],
                    "round_name": row.get("round_name", ""),
                    "round": row.get("round", ""),
                    "player_a": row["player_a"],
                    "player_b": row["player_b"],
                    "score_a": row["score_a"],
                    "score_b": row["score_b"],
                    "winner": row["winner"],
                })

    return rows


def write_rows(rows, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch an archery championship page and extract all event results from its Competition Schedule or Schedule section.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_URL,
        help="Wikipedia championship URL to scrape.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help="CSV file to write.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    rows = build_rows(args.url)

    print(f"Extracted {len(rows)} rows\n")
    for row in rows[:10]:
        print(row)

    write_rows(rows, args.output)
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
