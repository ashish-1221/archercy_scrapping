"""
Archery Elimination Scraper — 38th National Games Uttarakhand
=============================================================
URL: https://38nguk.in/sports/archery

Exact HTML structure (confirmed from page source):
---------------------------------------------------
Round headers row:
  div.d-flex.gap-4 > div > div.bgColor-gradient-maroon   ← round name text

Match tiles (one column per round, each column is a position-relative div):
  div.event-tile                                          ← one match
    ├── [top half]  player A
    │     div.team > p                                    ← state name
    │     span.elimination-span-fixed-height              ← athlete name
    │     div.score                                       ← score A
    ├── div[style*="border"]                              ← divider
    └── [bottom half] player B
          div.team > p                                    ← state name
          span.elimination-span-fixed-height              ← athlete name
          div.score                                       ← score B

Winner = player with higher score (or first player if only one score shown).

The round name is determined by the column index of the tile's parent container,
matched against the ordered round headers.

Requirements
------------
    pip install playwright
    playwright install chromium
    sudo playwright install-deps
"""

import asyncio
import csv
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "https://37nationalgamesgoa.in/sports/archery"
OUTPUT_CSV = "results/national_games/archery_elimination_2023.csv"
OUTPUT_JSON = "results/national_games/archery_elimination_2023.json"
CHAMPIONSHIP_NAME = "37th National Games Goa"
HEADLESS = False  # set False to watch the browser

FIELDNAMES = [
    "championship_name",
    "event",
    "round",
    "player_a",
    "state_a",
    "score_a",
    "player_b",
    "state_b",
    "score_b",
    "winner",
]


# ── Helper ────────────────────────────────────────────────────────────────────


async def safe_text(el) -> str:
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ""


# ── Main extraction from a fixture page ──────────────────────────────────────


async def extract_elimination_data(
    page, championship_name: str, event_name: str
) -> list[dict]:
    """
    Parse the elimination bracket from the fixture page.

    Layout on page:
      1. Round header row  →  div.d-flex.gap-4 containing round label divs
      2. Match tiles row   →  div.m-5.d-flex.gap-4 containing columns,
                              each column holds multiple div.event-tile elements
    """
    rows = []

    # ── 1. Collect round names from the header row ────────────────────────────
    # Header divs: each child div has an inner div with the round name text
    round_names = []
    header_row = await page.query_selector("div.flex.gap-4.m-4.w-100")
    if header_row:
        header_items = await header_row.query_selector_all(":scope > div")
        for item in header_items:
            text = (await safe_text(item)).strip()
            if text:
                round_names.append(text)
    print(f"    Round names found: {round_names}")

    # ── 2. Collect match columns ──────────────────────────────────────────────
    # The bracket container is the second div.m-5.d-flex.gap-4
    bracket_containers = await page.query_selector_all("div.m-4.flex.gap-4")

    for bracket in bracket_containers:
        # Each direct child is a column (position-relative div)
        columns = await bracket.query_selector_all(
            ":scope > div.position-relative, :scope > div"
        )
        if not columns:
            continue

        for col_index, column in enumerate(columns):
            # Round name: map by column index, fallback to "Round N"
            round_name = (
                round_names[col_index]
                if col_index < len(round_names)
                else f"Round {col_index + 1}"
            )

            # All match tiles in this column
            tiles = await column.query_selector_all("div.event-tile")

            for tile in tiles:
                row = await parse_match_tile(
                    tile, championship_name, event_name, round_name
                )
                if row:
                    rows.append(row)

    # Also check Bronze section (separate bracket below main one)
    # It uses the same structure but with a "Bronze" header
    bronze_header = await page.query_selector("div:has-text('Bronze')")
    if bronze_header:
        # Find the next sibling bracket
        bronze_tiles = await page.query_selector_all(
            "div.m-5.d-flex.gap-4 ~ div.m-5.d-flex.gap-4 div.event-tile, "
            "div.d-flex.gap-4 + div.m-5.d-flex.gap-4 div.event-tile"
        )
        for tile in bronze_tiles:
            row = await parse_match_tile(tile, championship_name, event_name, "Bronze")
            if row:
                rows.append(row)

    return rows


def is_team_event(event_name: str) -> bool:
    """Return True for Team or Mixed events (no individual athlete names in HTML)."""
    name_lower = event_name.lower()
    return "team" in name_lower or "mixed" in name_lower


async def parse_match_tile(
    tile, championship_name: str, event_name: str, round_name: str
) -> dict | None:
    """
    Extract one match from a div.event-tile.

    Individual events:
      div.team > p                        → state name
      span.elimination-span-fixed-height  → athlete name
      div.score                           → score

    Team / Mixed events:
      div.team > p                        → team/state name  (NO athlete span)
      div.score                           → score

    Winner = player/team with the higher score.
    """
    try:
        all_spans = await tile.query_selector_all("span.elimination-span-fixed-height")
        all_scores = await tile.query_selector_all("div.score")
        all_teams = await tile.query_selector_all("div.team p")

        team_event = is_team_event(event_name)

        if team_event:
            # For team/mixed events there are no athlete spans —
            # use state/team name as the player identifier.
            state_a = (
                (await safe_text(all_teams[0])).strip() if len(all_teams) > 0 else ""
            )
            state_b = (
                (await safe_text(all_teams[1])).strip() if len(all_teams) > 1 else ""
            )
            player_a = state_a  # team name IS the player for team events
            player_b = state_b
        else:
            # Individual events have athlete spans
            if not all_spans:
                return None
            player_a = (await safe_text(all_spans[0])).strip()
            player_b = (
                (await safe_text(all_spans[1])).strip() if len(all_spans) > 1 else ""
            )
            state_a = (
                (await safe_text(all_teams[0])).strip() if len(all_teams) > 0 else ""
            )
            state_b = (
                (await safe_text(all_teams[1])).strip() if len(all_teams) > 1 else ""
            )

        score_a_raw = (
            (await safe_text(all_scores[0])).strip() if len(all_scores) > 0 else ""
        )
        score_b_raw = (
            (await safe_text(all_scores[1])).strip() if len(all_scores) > 1 else ""
        )

        # Determine winner by score comparison
        winner = ""
        try:
            sa = int(score_a_raw)
            sb = int(score_b_raw)
            if sa > sb:
                winner = player_a
            elif sb > sa:
                winner = player_b
        except ValueError:
            pass

        if not player_a and not player_b:
            return None

        return {
            "championship_name": championship_name,
            "event": event_name,
            "round": round_name,
            "player_a": player_a,
            "state_a": state_a if not team_event else "",
            "score_a": score_a_raw,
            "player_b": player_b,
            "state_b": state_b if not team_event else "",
            "score_b": score_b_raw,
            "winner": winner,
        }

    except Exception as e:
        print(f"      parse_match_tile error: {e}")
        return None


# ── Navigation helpers ────────────────────────────────────────────────────────


async def get_event_cards(page) -> list[dict]:
    await page.wait_for_selector(".styles_card__pM8x0", timeout=20000)
    await page.wait_for_timeout(1500)

    cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")
    print(f"  Found {len(cards)} cards total")

    results = []
    for i, card in enumerate(cards):
        paras = await card.query_selector_all("p.defaultHeading")
        event_name = (await safe_text(paras[0])).strip() if paras else f"Event {i+1}"

        buttons = await card.query_selector_all("button")
        fixture_btn = None
        for btn in buttons:
            if "fixture" in (await safe_text(btn)).lower():
                fixture_btn = btn
                break

        if fixture_btn:
            results.append({"event": event_name, "card_index": i})
            print(f"    [{i:02d}] {event_name}")

    return results

from urllib.parse import urlparse, urlunparse

def change_to_elimination(current_url: str) -> str:
    parsed = urlparse(current_url)

    # replace the path
    new_path = parsed.path.replace("/leaderboard", "/elimination")

    # rebuild url
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        new_path,
        parsed.params,
        parsed.query,
        parsed.fragment
    ))

    return new_url


async def click_view_fixtures(page, card_index: int) -> bool:
    await page.wait_for_selector(".styles_cardMainContainer__rQzdE", timeout=15000)
    cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")

    if card_index >= len(cards):
        return False

    card = cards[card_index]
    buttons = await card.query_selector_all("button")

    fixture_btn = None
    for btn in buttons:
        if "fixture" in (await safe_text(btn)).lower():
            fixture_btn = btn
            break

    if not fixture_btn:
        return False

    current_url = page.url

    await fixture_btn.scroll_into_view_if_needed()
    await fixture_btn.click()

    try:
        # wait for leaderboard navigation
        await page.wait_for_function(
            f"() => window.location.href !== '{current_url}'",
            timeout=15000,
        )

        await page.wait_for_load_state("networkidle", timeout=15000)

        leaderboard_url = page.url
        print(f"    ✔ Navigated → {leaderboard_url}")

        # convert leaderboard -> elimination
        elimination_url = leaderboard_url.replace("/leaderboard", "/elimination")

        # navigate to elimination page
        await page.goto(elimination_url, wait_until="networkidle")

        print(f"    ✔ Switched → {elimination_url}")

        return True

    except PWTimeout:
        return False

async def click_elimination_tab(page) -> bool:
    """
    On the fixture page the tabs are rendered as:
      div.stages_div > div.stages_div_button   (text = LEADERBOARD / ELIMINATION)
    Click the one whose text contains ELIMINATION.
    """
    # Try the specific class first
    try:
        tab = await page.query_selector(".stages_div_button:has-text('ELIMINATION')")
        if tab:
            await tab.click()
            await page.wait_for_timeout(1500)
            print("    ✔ Clicked ELIMINATION tab")
            return True
    except Exception:
        pass

    # Broad fallbacks
    for sel in [
        "div:has-text('ELIMINATION')",
        "p:has-text('ELIMINATION')",
        "button:has-text('Elimination')",
        "a:has-text('Elimination')",
        "[role='tab']:has-text('Elimination')",
    ]:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(1500)
                print(f"    ✔ Clicked elimination tab via: {sel}")
                return True
        except Exception:
            continue

    print("    ⚠ Elimination tab not found — scraping visible content")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────


async def main():
    all_rows: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"Loading {BASE_URL} …")
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        print("Discovering event cards …")
        event_cards = await get_event_cards(page)

        if not event_cards:
            print("❌ No event cards found.")
            await browser.close()
            sys.exit(1)

        print(f"\nFound {len(event_cards)} events. Starting scrape …\n")

        for item in event_cards:
            event_name = item["event"]
            card_index = item["card_index"]

            print(f"── [{card_index:02d}] {event_name}")


            # Always go back — fixture URLs share base path as prefix so
            # simple `in` check fails. Unconditional goto is the safe fix.
            if page.url.rstrip("/") != BASE_URL.rstrip("/"):
                print(f"     Returning to archery page ...")
                await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

            ok = await click_view_fixtures(page, card_index)
            if not ok:
                print(f"     Skipped (navigation failed)\n")
                continue

            await click_elimination_tab(page)

            html = await page.content()
            with open(f"debug_event_{card_index:02d}.html", "w", encoding="utf-8") as f:
                f.write(html)

            rows = await extract_elimination_data(page, CHAMPIONSHIP_NAME, event_name)
            print(f"     Extracted {len(rows)} match rows\n")
            all_rows.extend(rows)

        await browser.close()

    # ── Save ──────────────────────────────────────────────────────────────────
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2, ensure_ascii=False)

    print(f"✅  Done — {len(all_rows)} total rows")
    print(f"   CSV  → {OUTPUT_CSV}")
    print(f"   JSON → {OUTPUT_JSON}")


if __name__ == "__main__":
    asyncio.run(main())
