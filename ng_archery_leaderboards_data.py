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
SCORE_COLUMN_TERMS = ("score", "total", "points", "result")


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
        # Use StringIO to avoid DeprecationWarning for literal HTML
        return pd.read_html(StringIO(table_html))
    except Exception:
        return []


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


def is_score_column(header: str) -> bool:
    key = normalize_lookup_key(header)
    return any(term in key for term in SCORE_COLUMN_TERMS)


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


def extract_flattened_data(frames: list[pd.DataFrame], event_name: str) -> list[dict]:
    results = []
    for frame in frames:
        if frame.empty:
            continue

        df = frame.copy()
        df.columns = [flatten_column_name(column) for column in df.columns]
        headers = list(df.columns)

        state_cols = [c for c in headers if is_state_column(c)]
        if not state_cols:
            continue
        state_col = sorted(state_cols, key=state_column_score)[0]

        athlete_cols = [
            c for c in headers if c != state_col and is_athlete_column(c)
        ]
        if not athlete_cols:
            athlete_cols = [
                c
                for c in headers
                if c != state_col
                and not any(
                    term in normalize_lookup_key(c)
                    for term in NON_ATHLETE_COLUMN_TERMS
                )
            ]

        score_cols = [c for c in headers if is_score_column(c)]
        # Prefer "Score" or "Total" if available
        score_col = None
        if score_cols:
            # Try to find 'score' or 'total' specifically
            for sc in score_cols:
                if "score" in normalize_lookup_key(sc) or "total" in normalize_lookup_key(sc):
                    score_col = sc
                    break
            if not score_col:
                score_col = score_cols[0]

        for _, row in df.iterrows():
            state = clean_cell(row.get(state_col, ""))
            score = clean_cell(row.get(score_col, "")) if score_col else ""

            names = []
            for col in athlete_cols:
                for name in split_names(row.get(col, "")):
                    if looks_like_athlete_name(name, state):
                        names.append(name)

            # If no names found but state is present, maybe it's a team row without explicit names
            if not names and state:
                results.append({
                    "event_name": event_name,
                    "state_name": state,
                    "player_name": "",
                    "score": score
                })
            else:
                for name in names:
                    results.append({
                        "event_name": event_name,
                        "state_name": state,
                        "player_name": name,
                        "score": score
                    })

    return results


def wait_for_archery_page(page) -> None:
    page.goto(ARCHERY_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".styles_cardMainContainer__rQzdE", timeout=30000)


def collect_event_summaries(page) -> list[dict]:
    cards = page.locator(".styles_cardMainContainer__rQzdE")
    count = cards.count()
    results = []
    
    for i in range(count):
        card = cards.nth(i)
        buttons = card.locator("button")
        btn_count = buttons.count()
        for b in range(btn_count):
            if "fixture" in buttons.nth(b).inner_text().lower():
                event_name = card.locator("p.sport_event_Card_para").first.inner_text().strip()
                results.append({"event": event_name, "card_index": i})
                break

    return results


def click_fixtures(page, card_index: int):
    cards = page.locator(".styles_cardMainContainer__rQzdE")
    card = cards.nth(card_index)
    buttons = card.locator("button")
    btn_count = buttons.count()
    
    for b in range(btn_count):
        btn = buttons.nth(b)
        if "fixture" in btn.inner_text().lower():
            current_url = page.url
            btn.scroll_into_view_if_needed()
            btn.click()
            try:
                page.wait_for_function(f"() => window.location.href !== '{current_url}'", timeout=10000)
            except Exception:
                pass
            page.wait_for_load_state("networkidle")
            return True
            
    return False


def open_leaderboard(page) -> None:
    try:
        leaderboard = page.locator("a, button, div").filter(has_text=re.compile(r"^\s*leaderboard\s*$", re.I)).first
        leaderboard.wait_for(timeout=10000)
        leaderboard.click()
        page.wait_for_load_state("networkidle")
    except Exception:
        pass
    
    try:
        page.locator("table").first.wait_for(timeout=10000)
    except Exception:
        pass


def scrape_and_flatten(output_path: Path, headless: bool, slow_mo: int):
    all_data = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
        page = browser.new_page()

        try:
            wait_for_archery_page(page)
            event_cards = collect_event_summaries(page)

            if not event_cards:
                raise RuntimeError("No Fixtures buttons were found on the archery page.")

            for item in event_cards:
                event_name = item["event"]
                card_index = item["card_index"]
                
                print(f"Processing event: {event_name}")
                wait_for_archery_page(page)
                
                ok = click_fixtures(page, card_index)
                if not ok:
                    print(f"  Skipping {event_name}: could not click fixtures")
                    continue

                try:
                    open_leaderboard(page)
                    tables = page.locator("table")
                    table_count = tables.count()
                    
                    if table_count == 0:
                        print(f"  No tables found for {event_name}")
                        continue

                    table_htmls = []
                    for t_idx in range(table_count):
                        table_htmls.append(tables.nth(t_idx).evaluate("(table) => table.outerHTML"))
                    
                    frames = []
                    for html in table_htmls:
                        frames.extend(table_html_to_frames(html))
                    
                    event_data = extract_flattened_data(frames, event_name)
                    all_data.extend(event_data)
                    print(f"  Extracted {len(event_data)} rows")

                except PlaywrightTimeoutError:
                    print(f"  Skipping {event_name}: leaderboard UI did not load in time")
                    continue
                time.sleep(0.5)
        except PlaywrightTimeoutError as error:
            print(f"Error: {error}")
        finally:
            browser.close()

    if all_data:
        df = pd.DataFrame(all_data)
        # Ensure requested columns are present and in order
        cols = ["event_name", "state_name", "player_name", "score"]
        for col in cols:
            if col not in df.columns:
                df[col] = ""
        
        df = df[cols]
        df.to_csv(output_path, index=False)
        print(f"Saved consolidated data to {output_path}")
    else:
        print("No data extracted.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape archery leaderboard values into state_name, player_name, score format."
    )
    parser.add_argument(
        "--output",
        default="archery_leaderboard_data.csv",
        help="Output CSV file path.",
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

    scrape_and_flatten(
        output_path=Path(args.output),
        headless=not args.headed,
        slow_mo=args.slow_mo,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
