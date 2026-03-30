#!/usr/bin/env python3

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import urljoin
from urllib.parse import urlsplit
from urllib.request import Request
from urllib.request import urlopen

from bs4 import BeautifulSoup
from bs4 import Tag


DEFAULT_SOURCE = "https://en.wikipedia.org/wiki/Archery_at_the_2024_Summer_Olympics"
OUTPUT_COLUMNS = ["player_a", "score_a", "player_b", "score_b", "winner"]
INDIVIDUAL_SUBSECTIONS = ("Section 1", "Section 2", "Section 3", "Section 4")
EVENT_ORDER = [
    "men's individual",
    "women's individual",
    "men's team",
    "women's team",
    "mixed team",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract archery match rows from Wikipedia Competition bracket and Finals "
            "sections into player_a,score_a,player_b,score_b,winner format."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=DEFAULT_SOURCE,
        help="Wikipedia overview/event URL or a saved HTML file path.",
    )
    parser.add_argument(
        "--base-url",
        help="Base URL used to resolve relative event links when the source is a local HTML file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("wikipedia_competition_bracket_results.csv"),
        help="CSV path to write.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Number of sample rows to print after saving.",
    )
    return parser


def is_url(value: str) -> bool:
    scheme = urlsplit(value).scheme.lower()
    return scheme in {"http", "https"}


def fetch_html(url: str, timeout: float) -> str:
    request = Request(
        url,
        headers={"User-Agent": "archery-scraper/1.0 (local utility script)"},
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def read_html_from_source(source: str, timeout: float) -> tuple[str, str | None]:
    if is_url(source):
        return fetch_html(source, timeout=timeout), source

    path = Path(source)
    return path.read_text(encoding="utf-8"), None


def build_soup(html: str) -> BeautifulSoup:
    for parser in ("lxml", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    raise RuntimeError("Could not initialize an HTML parser")


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def get_page_title(soup: BeautifulSoup) -> str:
    heading = soup.select_one("#firstHeading")
    return clean_space(heading.get_text(" ", strip=True)) if heading else "Unknown title"


def get_canonical_url(soup: BeautifulSoup) -> str | None:
    canonical = soup.select_one("link[rel='canonical']")
    href = canonical.get("href") if canonical else None
    return href or None


def get_content_root(soup: BeautifulSoup) -> Tag:
    root = soup.select_one("#mw-content-text .mw-parser-output")
    if root is None:
        raise RuntimeError("Could not find #mw-content-text .mw-parser-output")
    return root


def direct_child_tags(tag: Tag) -> list[Tag]:
    return [child for child in tag.children if isinstance(child, Tag)]


def extract_section_heading(tag: Tag) -> Tag | None:
    if tag.name and re.fullmatch(r"h[2-6]", tag.name):
        return tag

    classes = set(tag.get("class", []))
    if "mw-heading" in classes or any(class_name.startswith("mw-heading") for class_name in classes):
        for child in direct_child_tags(tag):
            if child.name and re.fullmatch(r"h[2-6]", child.name):
                return child
    return None


def heading_text(tag: Tag) -> str:
    headline = tag.select_one(".mw-headline")
    text = headline.get_text(" ", strip=True) if headline else tag.get_text(" ", strip=True)
    text = re.sub(r"\[\s*edit\s*\]$", "", text, flags=re.IGNORECASE)
    return clean_space(text)


def collect_section_children(content_root: Tag, target_heading: str) -> list[Tag]:
    collected: list[Tag] = []
    active = False
    start_level: int | None = None

    for child in direct_child_tags(content_root):
        heading = extract_section_heading(child)
        if heading is not None:
            current_title = heading_text(heading)
            current_level = int(heading.name[1])

            if active and start_level is not None and current_level <= start_level:
                break

            if current_title == target_heading:
                active = True
                start_level = current_level
                continue

        if active:
            collected.append(child)

    return collected


def collect_event_links_from_overview(soup: BeautifulSoup, base_url: str) -> list[str]:
    content_root = get_content_root(soup)
    links: list[str] = []
    seen: set[str] = set()

    for anchor in content_root.select("a[href]"):
        href = anchor.get("href", "").strip()
        text = clean_space(anchor.get_text(" ", strip=True)).lower()
        absolute = urljoin(base_url, href)

        if "/wiki/Archery_at_the_2024_Summer_Olympics" not in absolute:
            continue
        if absolute == base_url or "#" in absolute:
            continue
        if "qualification" in absolute.lower() or "qualification" in text:
            continue
        if not any(label in absolute.lower() or label in text for label in EVENT_ORDER):
            continue
        if absolute in seen:
            continue

        seen.add(absolute)
        links.append(absolute)

    links.sort(
        key=lambda url: (
            next(
                (index for index, label in enumerate(EVENT_ORDER) if label in url.lower()),
                999,
            ),
            url.lower(),
        )
    )
    return links


def normalize_score_text(value: str) -> str:
    text = clean_space(value)
    if not text:
        return ""

    match = re.match(r"^(\d+)\s+([0-9Xx+*]+)$", text)
    if match:
        return f"{match.group(1)}^{match.group(2).upper()}"

    return text


def parse_score(score: str) -> tuple[int, int]:
    match = re.match(r"^(\d+)(?:\^(.+))?$", normalize_score_text(score))
    if not match:
        return (-1, -1)

    base_score = int(match.group(1))
    tiebreak = match.group(2)
    if not tiebreak:
        return (base_score, -1)

    upper = tiebreak.upper()
    if upper == "X":
        return (base_score, 11)

    digits = re.search(r"\d+", upper)
    if digits:
        return (base_score, int(digits.group()))

    if "+" in upper or "*" in upper:
        return (base_score, 1)

    return (base_score, 0)


def choose_winner(player_a: str, score_a: str, player_b: str, score_b: str) -> str:
    parsed_a = parse_score(score_a)
    parsed_b = parse_score(score_b)

    if parsed_a > parsed_b:
        return player_a
    if parsed_b > parsed_a:
        return player_b
    return player_a


def build_match(entry_a: tuple[str, str], entry_b: tuple[str, str]) -> dict[str, str]:
    player_a, score_a = entry_a
    player_b, score_b = entry_b
    return {
        "player_a": player_a,
        "score_a": score_a,
        "player_b": player_b,
        "score_b": score_b,
        "winner": choose_winner(player_a, score_a, player_b, score_b),
    }


def expand_table_grid(table: Tag) -> list[list[str]]:
    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr", recursive=False)
    grid: list[list[str]] = []
    rowspans: dict[int, tuple[str, int]] = {}

    for row_tag in rows:
        row: list[str] = []
        col = 0

        def fill_rowspans() -> None:
            nonlocal col
            while col in rowspans:
                value, remaining = rowspans[col]
                row.append(value)
                if remaining == 1:
                    del rowspans[col]
                else:
                    rowspans[col] = (value, remaining - 1)
                col += 1

        fill_rowspans()

        for cell in row_tag.find_all(["td", "th"], recursive=False):
            text = clean_space(" ".join(cell.stripped_strings))
            colspan = int(cell.get("colspan", 1))
            rowspan = int(cell.get("rowspan", 1))

            for _ in range(colspan):
                row.append(text)
                if rowspan > 1:
                    rowspans[col] = (text, rowspan - 1)
                col += 1
                fill_rowspans()

        grid.append(row)

    return grid


def row_cell(row: list[str], index: int) -> str:
    if 0 <= index < len(row):
        return row[index]
    return ""


def extract_round_starts(grid: list[list[str]]) -> list[tuple[int, str]]:
    if not grid:
        return []

    starts: list[tuple[int, str]] = []
    header = grid[0]
    previous = ""
    for index, value in enumerate(header):
        if value and value != previous:
            starts.append((index, value))
        previous = value
    return starts


def extract_block_entries(
    grid: list[list[str]],
    start_col: int,
    row_start: int = 1,
    row_end: int | None = None,
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    limit = row_end if row_end is not None else len(grid)

    for row in grid[row_start:limit]:
        seed = row_cell(row, start_col)
        name = clean_space(row_cell(row, start_col + 1))
        score = normalize_score_text(row_cell(row, start_col + 2))

        if not re.match(r"^\d+$", seed):
            continue
        if not name or not score or not re.match(r"^\d", score):
            continue

        entry = (name, score)
        if not entries or entries[-1] != entry:
            entries.append(entry)

    return entries


def build_matches_from_entries(entries: list[tuple[str, str]]) -> list[dict[str, str]]:
    if len(entries) % 2 != 0:
        raise RuntimeError(f"Expected an even number of bracket entries, found {len(entries)}.")

    matches: list[dict[str, str]] = []
    for index in range(0, len(entries), 2):
        matches.append(build_match(entries[index], entries[index + 1]))
    return matches


def extract_rowwise_entries(grid: list[list[str]], row_start: int) -> list[tuple[str, str]]:
    return extract_rowwise_entries_from_column(grid, row_start=row_start, min_col=0)


def extract_rowwise_entries_from_column(
    grid: list[list[str]],
    row_start: int,
    min_col: int,
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []

    for row in grid[row_start:]:
        for col in range(min_col, max(len(row) - 2, min_col)):
            seed = row_cell(row, col)
            name = clean_space(row_cell(row, col + 1))
            score = normalize_score_text(row_cell(row, col + 2))

            if not re.match(r"^\d+$", seed):
                continue
            if not name or not score or not re.match(r"^\d", score):
                continue

            entry = (name, score)
            if not entries or entries[-1] != entry:
                entries.append(entry)

    return entries


def find_label_row(grid: list[list[str]], label: str) -> int | None:
    for row_index, row in enumerate(grid):
        if any(cell == label for cell in row):
            return row_index
    return None


def parse_standard_bracket_table(table: Tag) -> list[dict[str, str]]:
    grid = expand_table_grid(table)
    matches: list[dict[str, str]] = []

    for start_col, _round_name in extract_round_starts(grid):
        entries = extract_block_entries(grid, start_col=start_col, row_start=1)
        matches.extend(build_matches_from_entries(entries))

    return matches


def parse_individual_finals_table(table: Tag) -> list[dict[str, str]]:
    grid = expand_table_grid(table)
    round_starts = extract_round_starts(grid)
    if len(round_starts) < 2:
        raise RuntimeError("Could not identify semi-final and medal-match columns in the Finals table.")

    bronze_row = find_label_row(grid, "Bronze medal match")

    semi_start = round_starts[0][0]
    gold_start = round_starts[1][0]

    semi_entries = extract_block_entries(grid, start_col=semi_start, row_start=1)
    gold_entries = extract_block_entries(
        grid,
        start_col=gold_start,
        row_start=1,
        row_end=bronze_row,
    )

    if bronze_row is None:
        raise RuntimeError("Could not locate the Bronze medal match label in the Finals table.")

    bronze_entries = extract_rowwise_entries_from_column(
        grid,
        row_start=bronze_row + 1,
        min_col=gold_start,
    )

    matches: list[dict[str, str]] = []
    matches.extend(build_matches_from_entries(semi_entries))
    matches.extend(build_matches_from_entries(gold_entries[:2]))
    matches.extend(build_matches_from_entries(bronze_entries[-2:]))
    return matches


def parse_team_bracket_table(table: Tag) -> list[dict[str, str]]:
    grid = expand_table_grid(table)
    round_starts = extract_round_starts(grid)
    if not round_starts:
        raise RuntimeError("Could not identify bracket columns in the team bracket table.")

    bronze_row = find_label_row(grid, "Bronze medal match")
    medal_start = round_starts[-1][0]

    matches: list[dict[str, str]] = []

    for start_col, _round_name in round_starts[:-1]:
        entries = extract_block_entries(grid, start_col=start_col, row_start=1)
        matches.extend(build_matches_from_entries(entries))

    medal_entries = extract_block_entries(
        grid,
        start_col=medal_start,
        row_start=1,
        row_end=bronze_row,
    )
    matches.extend(build_matches_from_entries(medal_entries[:2]))

    if bronze_row is not None:
        bronze_entries = extract_rowwise_entries_from_column(
            grid,
            row_start=bronze_row + 1,
            min_col=medal_start,
        )
        matches.extend(build_matches_from_entries(bronze_entries[-2:]))

    return matches


def parse_individual_event(content_root: Tag) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []

    for subsection in INDIVIDUAL_SUBSECTIONS:
        section_children = collect_section_children(content_root, subsection)
        table = next((child for child in section_children if child.name == "table"), None)
        if table is None:
            raise RuntimeError(f"Missing table for {subsection}.")
        matches.extend(parse_standard_bracket_table(table))

    finals_children = collect_section_children(content_root, "Finals")
    finals_table = next((child for child in finals_children if child.name == "table"), None)
    if finals_table is None:
        raise RuntimeError("Missing Finals table.")

    matches.extend(parse_individual_finals_table(finals_table))
    return matches


def parse_team_event(content_root: Tag) -> list[dict[str, str]]:
    bracket_children = collect_section_children(content_root, "Competition bracket")
    tables = [child for child in bracket_children if child.name == "table"]
    if not tables:
        raise RuntimeError("Missing Competition bracket table.")

    matches: list[dict[str, str]] = []
    for table in tables:
        matches.extend(parse_team_bracket_table(table))
    return matches


def parse_event_page(html: str) -> tuple[str, list[dict[str, str]]]:
    soup = build_soup(html)
    title = get_page_title(soup)
    content_root = get_content_root(soup)
    lowered = title.lower()

    if "individual" in lowered:
        return title, parse_individual_event(content_root)
    if "team" in lowered:
        return title, parse_team_event(content_root)

    raise RuntimeError(f"Unsupported event page: {title}")


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_samples(rows: list[dict[str, str]], sample_size: int) -> None:
    if sample_size <= 0:
        return

    print("Sample rows:")
    for row in rows[:sample_size]:
        print(",".join(row[column] for column in OUTPUT_COLUMNS))


def resolve_base_url(explicit_base_url: str | None, source_url: str | None, soup: BeautifulSoup) -> str | None:
    return explicit_base_url or source_url or get_canonical_url(soup)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    source_html, source_url = read_html_from_source(args.source, timeout=args.timeout)
    source_soup = build_soup(source_html)
    source_title = get_page_title(source_soup)
    base_url = resolve_base_url(args.base_url, source_url, source_soup)

    rows: list[dict[str, str]] = []
    processed_titles: list[str] = []

    if source_title == "Archery at the 2024 Summer Olympics":
        if not base_url:
            raise RuntimeError(
                "Could not determine a base URL for the overview page. Pass --base-url when using a local HTML file."
            )

        event_links = collect_event_links_from_overview(source_soup, base_url=base_url)
        if not event_links:
            raise RuntimeError("No event links were found on the overview page.")

        for event_url in event_links:
            event_html = fetch_html(event_url, timeout=args.timeout)
            event_title, event_rows = parse_event_page(event_html)
            processed_titles.append(event_title)
            rows.extend(event_rows)
    else:
        event_title, event_rows = parse_event_page(source_html)
        processed_titles.append(event_title)
        rows.extend(event_rows)

    write_csv(rows, args.output)

    print(f"Processed {len(processed_titles)} page(s)")
    for title in processed_titles:
        print(f"- {title}")
    print(f"Saved {len(rows)} row(s)")
    print(args.output.resolve())
    print_samples(rows, args.sample_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
