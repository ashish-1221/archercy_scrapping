"""
Archery Elimination Scraper — 37th National Games Goa
======================================================
URL: https://37nationalgamesgoa.in/sports/archery

Confirmed elimination tile structure (individual events):
  div.event-tile.p-3
    div > div.flex.justify-content-between
      div.line-clamp-2    ← "Deepika Kumari(Jharkhand)"
      div.score           ← "6"
    div[style*="border"]  ← divider
    div.position-relative > div.flex.justify-content-between
      div.line-clamp-2    ← "Yumnam Devi(Manipur)"
      div.score           ← "2"

Team event tiles (state name only, no parenthetical):
  div.event-tile.p-3
    same structure but line-clamp-2 = "Manipur", "Jharkhand" etc.

Round headers (gradient divs at top of each column group):
  div.flex.gap-4.m-4 > div > div[style*="gradient"]
  Text = "Quarter Final", "Semi Final", "Final", "Winner", "Bronze"
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
HEADLESS = True
DEBUG_HTML = True

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

KNOWN_ROUND_NAMES = {
    "quarter final",
    "semi final",
    "final",
    "winner",
    "bronze",
    "round of 16",
    "round of 32",
    "pre quarter final",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


async def safe_text(el) -> str:
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ""


def split_player_state(raw: str) -> tuple[str, str]:
    """
    "Deepika Kumari(Jharkhand)" → ("Deepika Kumari", "Jharkhand")
    "Tamanna (Haryana)"         → ("Tamanna", "Haryana")
    "Manipur"                   → ("Manipur", "")
    """
    raw = raw.strip()
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw, ""


def is_team_event(name: str) -> bool:
    n = name.lower()
    return "team" in n or "mixed" in n


def slugify(text: str, max_len: int = 40) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)[:max_len]


def is_valid_round_name(text: str) -> bool:
    """Return True only if text looks like a round label, not tile content."""
    t = text.strip().lower()
    if not t or len(t) > 40:
        return False
    # Must match a known round keyword
    return any(k in t for k in KNOWN_ROUND_NAMES)


# ── Step 1: Discover event cards ──────────────────────────────────────────────


async def discover_events(page) -> list[dict]:
    try:
        await page.wait_for_selector(
            "div.styles_cardMainContainer__rQzdE", timeout=20000
        )
    except PWTimeout:
        print("  ⚠ Timed out waiting for event cards")
        return []

    await page.wait_for_timeout(1500)
    cards = await page.query_selector_all("div.styles_cardMainContainer__rQzdE")
    print(f"  Found {len(cards)} event cards")

    events = []
    for i, card in enumerate(cards):
        p = await card.query_selector("p.defaultHeading")
        event_name = (await safe_text(p)) if p else f"Event {i}"

        has_fixture_btn = any(
            "fixture" in (await safe_text(btn)).lower()
            for btn in await card.query_selector_all("button")
        )
        if has_fixture_btn:
            events.append({"event": event_name, "card_index": i})
            print(f"    [{i:02d}] {event_name}")

    return events


# ── Step 2: Click "View Fixtures" ─────────────────────────────────────────────


async def click_view_fixtures(page, card_index: int) -> bool:
    cards = await page.query_selector_all("div.styles_cardMainContainer__rQzdE")
    if card_index >= len(cards):
        print(f"    ✘ card_index {card_index} out of range ({len(cards)} cards)")
        return False

    card = cards[card_index]
    fixture_btn = None
    for btn in await card.query_selector_all("button"):
        if "fixture" in (await safe_text(btn)).lower():
            fixture_btn = btn
            break

    if not fixture_btn:
        print(f"    ✘ No 'View Fixtures' button in card {card_index}")
        return False

    await fixture_btn.scroll_into_view_if_needed()
    await fixture_btn.click()

    try:
        await page.wait_for_function(
            """() => {
                const ps = document.querySelectorAll('div.cursor-pointer p');
                return Array.from(ps).some(p => p.textContent.trim() === 'LEADERBOARD');
            }""",
            timeout=15000,
        )
        await page.wait_for_timeout(800)
        print("    ✔ Fixture view loaded")
        return True
    except PWTimeout:
        print("    ✘ Fixture view did not render")
        return False


# ── Step 3: Click ELIMINATION tab ────────────────────────────────────────────


async def click_elimination_tab(page) -> bool:
    divs = await page.query_selector_all("div.cursor-pointer")
    for div in divs:
        p = await div.query_selector(":scope > p")
        if p and (await safe_text(p)).upper() == "ELIMINATION":
            await div.scroll_into_view_if_needed()
            await div.click()
            try:
                await page.wait_for_selector("div.event-tile", timeout=8000)
            except PWTimeout:
                pass
            await page.wait_for_timeout(800)
            print("    ✔ Clicked ELIMINATION tab")
            return True

    print("    ⚠ ELIMINATION tab not found")
    return False


# ── Step 4: Return to listing (SPA-safe) ─────────────────────────────────────


async def return_to_listing(page) -> bool:
    """
    FIX: go_back() on this SPA doesn't trigger networkidle.
    Use domcontentloaded + short poll for the card selector.
    Hard reload is the reliable fallback.
    """
    # Try browser back first
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=8000)
        await page.wait_for_timeout(500)
    except Exception:
        pass

    # Check if cards are present (quick non-blocking check)
    try:
        await page.wait_for_selector(
            "div.styles_cardMainContainer__rQzdE", timeout=5000
        )
        await page.wait_for_timeout(500)
        return True
    except PWTimeout:
        pass

    # Hard reload fallback — always works
    print("    ↩ Reloading listing page")
    try:
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        await page.goto(BASE_URL, timeout=20000)

    # Poll for cards instead of blocking wait_for_selector
    for _ in range(20):
        await page.wait_for_timeout(500)
        cards = await page.query_selector_all("div.styles_cardMainContainer__rQzdE")
        if cards:
            return True

    print("    ✘ Could not reload listing page")
    return False


# ── Step 5: Extract round names (tight selector) ──────────────────────────────


async def get_column_round_map(page) -> list[tuple[str, object]]:
    """
    Build (round_name, column_div) pairs.

    Round header rows: div.flex.gap-4.m-4
      Each contains N child divs, each child has ONE gradient div as its
      direct child — that gradient div's OWN text (not descendants) is the label.

    Bracket rows: div.m-4.flex.gap-4
      Each contains N column divs with event-tiles.

    We pair header_row[i] → bracket_row[i] by DOM order.
    """
    # Use JS to extract only the direct text of gradient divs
    # (avoids pulling in tile content from deeper descendants)
    round_labels_per_row: list[list[str]] = await page.evaluate(
        """
        () => {
            const headerRows = document.querySelectorAll('div.flex.gap-4.m-4');
            return Array.from(headerRows).map(row => {
                // Each direct child of headerRow → look for its first gradient div
                const children = Array.from(row.children);
                return children.map(child => {
                    // Find gradient div that is a direct child of this child
                    const gradDiv = child.querySelector(':scope > div[style*="gradient"]');
                    if (!gradDiv) return '';
                    // Get only the direct text node content (not descendants)
                    const text = Array.from(gradDiv.childNodes)
                        .filter(n => n.nodeType === Node.TEXT_NODE)
                        .map(n => n.textContent.trim())
                        .join(' ')
                        .trim();
                    return text || gradDiv.textContent.trim().split('\\n')[0].trim();
                }).filter(t => t.length > 0 && t.length < 50);
            });
        }
    """
    )

    bracket_rows = await page.query_selector_all("div.m-4.flex.gap-4")
    pairs: list[tuple[str, object]] = []

    for row_idx, bracket_row in enumerate(bracket_rows):
        columns = await bracket_row.query_selector_all(":scope > div")
        labels = (
            round_labels_per_row[row_idx] if row_idx < len(round_labels_per_row) else []
        )

        # Validate labels — only keep known round name keywords
        valid_labels = [l for l in labels if is_valid_round_name(l)]

        # Detect Bronze section: header row has single label "Bronze"
        is_bronze = len(valid_labels) == 1 and "bronze" in valid_labels[0].lower()

        for col_idx, col in enumerate(columns):
            if is_bronze:
                round_name = "Bronze"
            elif col_idx < len(valid_labels):
                round_name = valid_labels[col_idx]
            else:
                # Fallback: infer from position
                fallback = ["Quarter Final", "Semi Final", "Final", "Winner"]
                round_name = (
                    fallback[col_idx]
                    if col_idx < len(fallback)
                    else f"Round {col_idx+1}"
                )

            pairs.append((round_name, col))

    return pairs


# ── Step 6: Parse one match tile ─────────────────────────────────────────────


async def parse_tile(
    tile, championship_name: str, event_name: str, round_name: str, seen: set
) -> dict | None:
    try:
        name_divs = await tile.query_selector_all("div.line-clamp-2")
        score_divs = await tile.query_selector_all("div.score")

        raw_a = await safe_text(name_divs[0]) if len(name_divs) > 0 else ""
        raw_b = await safe_text(name_divs[1]) if len(name_divs) > 1 else ""
        score_a = await safe_text(score_divs[0]) if len(score_divs) > 0 else ""
        score_b = await safe_text(score_divs[1]) if len(score_divs) > 1 else ""

        player_a, state_a = split_player_state(raw_a)
        player_b, state_b = split_player_state(raw_b)

        if not player_a and not player_b:
            return None

        fp = f"{player_a}|{player_b}|{score_a}|{score_b}"
        if fp in seen:
            return None
        seen.add(fp)

        winner = ""
        try:
            sa, sb = int(score_a), int(score_b)
            winner = player_a if sa > sb else (player_b if sb > sa else "")
        except ValueError:
            pass

        return {
            "championship_name": championship_name,
            "event": event_name,
            "round": round_name,
            "player_a": player_a,
            "state_a": state_a,
            "score_a": score_a,
            "player_b": player_b,
            "state_b": state_b,
            "score_b": score_b,
            "winner": winner,
        }
    except Exception as e:
        print(f"      parse_tile error: {e}")
        return None


# ── Step 7: Extract all matches ───────────────────────────────────────────────


async def extract_elimination_data(
    page, championship_name: str, event_name: str
) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    col_round_pairs = await get_column_round_map(page)
    print(f"    Rounds: {[r for r, _ in col_round_pairs]}")

    for round_name, col in col_round_pairs:
        tiles = await col.query_selector_all("div.event-tile")
        for tile in tiles:
            row = await parse_tile(
                tile, championship_name, event_name, round_name, seen
            )
            if row:
                rows.append(row)

    return rows


# ── Main ──────────────────────────────────────────────────────────────────────


async def main():
    Path("results/national_games").mkdir(parents=True, exist_ok=True)
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
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)

        if DEBUG_HTML:
            Path("debug_00_listing.html").write_text(
                await page.content(), encoding="utf-8"
            )
            print("  Saved debug_00_listing.html")

        print("Discovering events …")
        events = await discover_events(page)

        if not events:
            print("❌ No events found.")
            await browser.close()
            sys.exit(1)

        print(f"\nFound {len(events)} events. Scraping …\n")

        for item in events:
            event_name = item["event"]
            card_index = item["card_index"]
            print(f"── [{card_index:02d}] {event_name}")

            on_listing = await page.query_selector(
                "div.styles_cardMainContainer__rQzdE"
            )
            if not on_listing:
                print("     Not on listing — returning …")
                if not await return_to_listing(page):
                    print("     ✘ Could not reach listing. Skipping.\n")
                    continue

            ok = await click_view_fixtures(page, card_index)
            if not ok:
                print("     Skipped (fixture did not load)\n")
                await return_to_listing(page)
                continue

            if DEBUG_HTML:
                Path(
                    f"debug_{card_index:02d}_{slugify(event_name)}_lb.html"
                ).write_text(await page.content(), encoding="utf-8")

            elim_ok = await click_elimination_tab(page)
            if not elim_ok:
                print("     Skipped (no elimination tab)\n")
                await return_to_listing(page)
                continue

            if DEBUG_HTML:
                Path(
                    f"debug_{card_index:02d}_{slugify(event_name)}_elim.html"
                ).write_text(await page.content(), encoding="utf-8")

            rows = await extract_elimination_data(page, CHAMPIONSHIP_NAME, event_name)
            print(f"     Extracted {len(rows)} match rows\n")
            all_rows.extend(rows)

            await return_to_listing(page)

        await browser.close()

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
