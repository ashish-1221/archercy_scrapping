#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import time
from io import StringIO
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ARCHERY_URL = "https://38nguk.in/sports/archery"
ROSTER_SEPARATOR = " / "

STATE_COLUMN_TERMS = ("state", "team", "unit", "association")
ATHLETE_COLUMN_TERMS = (
    "name",
    "player",
    "athlete",
    "archer",
    "participant",
    "member",
)
NON_ATHLETE_COLUMN_TERMS = (
    "rank",
    "score",
    "total",
    "points",
    "10",
    "x",
    "position",
    "seed",
    "result",
    "qualification",
    "qualified",
    "status",
    "round",
    "event",
    "medal",
    "remarks",
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "event"


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_lookup_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", str(value).lower().replace("&", " and "))
    key = re.sub(r"\band\b", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def clean_cell(value) -> str:
    if value is None:
        return ""
    if pd is not None:
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text.lower() == "nan" else text


def flatten_column_name(column) -> str:
    if isinstance(column, tuple):
        parts = [
            clean_cell(part)
            for part in column
            if clean_cell(part) and not str(part).lower().startswith("unnamed")
        ]
        return " ".join(parts)
    return clean_cell(column)


def table_html_to_frames(table_html: str) -> list[pd.DataFrame]:
    if pd is None:
        raise RuntimeError(
            "pandas is required to parse leaderboard tables. "
            "Install the project requirements before scraping rosters."
        )
    try:
        return pd.read_html(StringIO(table_html))
    except ImportError:
        return [table_html_to_frame_with_bs4(table_html)]


def unique_headers(headers: list[str], width: int) -> list[str]:
    if not headers:
        headers = [f"column_{index + 1}" for index in range(width)]

    headers = headers[:width] + [
        f"column_{index + 1}" for index in range(len(headers), width)
    ]

    seen: dict[str, int] = {}
    unique: list[str] = []
    for index, header in enumerate(headers):
        header = header or f"column_{index + 1}"
        count = seen.get(header, 0)
        seen[header] = count + 1
        unique.append(header if count == 0 else f"{header}_{count + 1}")
    return unique


def table_html_to_frame_with_bs4(table_html: str) -> pd.DataFrame:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(table_html, "html.parser")
    table = soup.find("table") or soup
    headers: list[str] = []
    rows: list[list[str]] = []

    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        values = [clean_cell(cell.get_text(" ", strip=True)) for cell in cells]
        if not values:
            continue
        if tr.find_all("th") and not headers:
            headers = values
        else:
            rows.append(values)

    width = max([len(headers), *(len(row) for row in rows)], default=0)
    headers = unique_headers(headers, width)
    rows = [row[:width] + [""] * (width - len(row)) for row in rows]

    return pd.DataFrame(rows, columns=headers)


def table_htmls_to_frames(table_htmls: list[str]) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for table_html in table_htmls:
        frames.extend(table_html_to_frames(table_html))
    return frames


def is_state_column(header: str) -> bool:
    key = normalize_lookup_key(header)
    return any(term in key for term in STATE_COLUMN_TERMS)


def state_column_score(header: str) -> int:
    key = normalize_lookup_key(header)
    if "state" in key:
        return 0
    if "unit" in key or "association" in key:
        return 1
    if "team" in key and not any(term in key for term in ATHLETE_COLUMN_TERMS):
        return 2
    if "team" in key:
        return 3
    return 9


def is_athlete_column(header: str) -> bool:
    key = normalize_lookup_key(header)
    if any(term in key for term in NON_ATHLETE_COLUMN_TERMS):
        return False
    return any(term in key for term in ATHLETE_COLUMN_TERMS)


def split_names(value: str) -> list[str]:
    text = clean_cell(value)
    if not text:
        return []
    return [
        clean_cell(part)
        for part in re.split(r"\s*(?:/|\||;|\n|\r)\s*", text)
        if clean_cell(part)
    ]


def looks_like_athlete_name(value: str, state: str) -> bool:
    text = clean_cell(value)
    if not text:
        return False
    value_key = normalize_lookup_key(text)
    state_key = normalize_lookup_key(state)
    if value_key == state_key:
        return False
    if state_key and state_key in value_key and "team" in value_key:
        return False
    if re.fullmatch(r"[\d\s.()+-]+", text):
        return False
    if value_key in {"bye", "na", "n a", "dns", "dnf", "qualified"}:
        return False
    return len(re.findall(r"[A-Za-z]", text)) >= 3


def add_unique(rosters: dict[str, list[str]], state: str, names: list[str]) -> None:
    state = clean_cell(state)
    if not state:
        return
    roster = rosters.setdefault(state, [])
    seen = {normalize_lookup_key(name) for name in roster}
    for name in names:
        name = clean_cell(name)
        if name and normalize_lookup_key(name) not in seen:
            roster.append(name)
            seen.add(normalize_lookup_key(name))


def extract_state_rosters_from_frames(frames: list[pd.DataFrame]) -> dict[str, list[str]]:
    """
    Build a state/team -> athlete-name mapping from leaderboard tables.

    The 38NG site changes table headers across events, so this parser looks for a
    state/team column plus any athlete/member/name-like columns. If explicit name
    columns are absent, it falls back to text columns that are not ranking/score
    metrics.
    """
    rosters: dict[str, list[str]] = {}

    for frame in frames:
        if frame.empty:
            continue

        df = frame.copy()
        df.columns = [flatten_column_name(column) for column in df.columns]
        headers = list(df.columns)

        state_columns = [column for column in headers if is_state_column(column)]
        if not state_columns:
            continue

        state_column = sorted(state_columns, key=state_column_score)[0]
        athlete_columns = [
            column
            for column in headers
            if column != state_column and is_athlete_column(column)
        ]

        if not athlete_columns:
            athlete_columns = [
                column
                for column in headers
                if column != state_column
                and not any(
                    term in normalize_lookup_key(column)
                    for term in NON_ATHLETE_COLUMN_TERMS
                )
            ]

        for _, row in df.iterrows():
            state = clean_cell(row.get(state_column, ""))
            names: list[str] = []

            for column in athlete_columns:
                for name in split_names(row.get(column, "")):
                    if looks_like_athlete_name(name, state):
                        names.append(name)

            add_unique(rosters, state, names)

    return {state: names for state, names in rosters.items() if names}


def extract_state_rosters_from_table_htmls(table_htmls: list[str]) -> dict[str, list[str]]:
    return extract_state_rosters_from_frames(table_htmls_to_frames(table_htmls))


def format_roster(names: list[str]) -> str:
    return ROSTER_SEPARATOR.join(names)


def wait_for_archery_page(page) -> None:
    page.goto(ARCHERY_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.locator("a, button").filter(has_text=re.compile(r"^\s*fixtures\s*$", re.I)).first.wait_for(
        timeout=30000
    )


def extract_event_label(trigger) -> str:
    label = trigger.evaluate(
        """
        (node) => {
            const card = node.closest('article, section, li, .card, [class*="card"], [class*="event"], [class*="fixture"]') || node.parentElement;
            if (!card) return '';

            const heading = card.querySelector('h1, h2, h3, h4, h5, h6');
            if (heading && heading.textContent) return heading.textContent.trim();

            const textNodes = Array.from(card.querySelectorAll('p, span, div'))
                .map((el) => (el.textContent || '').trim())
                .filter(Boolean)
                .filter((text) => !/^(fixtures|leaderboard|view score|elimination|pool|league)$/i.test(text));

            return textNodes[0] || '';
        }
        """
    )
    return re.sub(r"\s+", " ", label).strip() or "event"


def collect_event_summaries(page) -> list[str]:
    triggers = page.locator("a, button").filter(has_text=re.compile(r"^\s*fixtures\s*$", re.I))
    count = triggers.count()
    labels: list[str] = []

    for index in range(count):
        labels.append(extract_event_label(triggers.nth(index)))

    return labels


def click_fixtures(page, index: int):
    trigger = page.locator("a, button").filter(has_text=re.compile(r"^\s*fixtures\s*$", re.I)).nth(index)
    event_label = extract_event_label(trigger)
    trigger.click()
    page.wait_for_load_state("networkidle")
    return event_label


def open_leaderboard(page) -> None:
    leaderboard = page.locator("a, button").filter(has_text=re.compile(r"^\s*leaderboard\s*$", re.I)).first
    leaderboard.wait_for(timeout=30000)
    leaderboard.click()
    page.wait_for_load_state("networkidle")
    page.locator("table").first.wait_for(timeout=30000)


def save_tables(page, output_dir: Path, event_number: int, event_label: str) -> list[Path]:
    tables = page.locator("table")
    table_count = tables.count()
    saved_paths: list[Path] = []

    if table_count == 0:
        return saved_paths

    for index in range(table_count):
        html = tables.nth(index).evaluate("(table) => table.outerHTML")
        frames = table_html_to_frames(html)

        if not frames:
            continue

        filename = f"{event_number:02d}-{slugify(event_label)}"
        if table_count > 1:
            filename += f"-table-{index + 1}"

        output_path = output_dir / f"{filename}.csv"
        frames[0].to_csv(output_path, index=False)
        saved_paths.append(output_path)

    return saved_paths


def scrape_leaderboards(output_dir: Path, headless: bool, slow_mo: int) -> list[Path]:
    saved_paths: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
        page = browser.new_page()

        try:
            wait_for_archery_page(page)
            event_labels = collect_event_summaries(page)

            if not event_labels:
                raise RuntimeError("No Fixtures buttons were found on the archery page.")

            for index, event_name in enumerate(event_labels):
                wait_for_archery_page(page)
                current_name = click_fixtures(page, index)
                if current_name:
                    event_name = current_name

                try:
                    open_leaderboard(page)
                    event_paths = save_tables(page, output_dir, index + 1, event_name)
                    if not event_paths:
                        print(f"Skipping {event_name}: no leaderboard table found")
                        continue
                    saved_paths.extend(event_paths)
                except PlaywrightTimeoutError:
                    print(f"Skipping {event_name}: leaderboard UI did not load in time")
                    continue
                time.sleep(0.5)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Timed out while waiting for the Fixtures or Leaderboard UI. "
                "The page structure may have changed."
            ) from error
        finally:
            browser.close()

    return saved_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape all leaderboard tables from the 38th National Games archery page."
    )
    parser.add_argument(
        "--output-dir",
        default="archery_leaderboards",
        help="Directory where leaderboard CSV files will be written.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium with a visible window instead of headless mode.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=250,
        help="Delay in milliseconds between browser actions.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    output_dir = ensure_output_dir(Path(args.output_dir))
    saved_paths = scrape_leaderboards(
        output_dir=output_dir,
        headless=not args.headed,
        slow_mo=args.slow_mo,
    )

    print(f"Saved {len(saved_paths)} file(s) to {output_dir}")
    for path in saved_paths:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
