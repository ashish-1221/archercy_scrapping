import asyncio
import csv
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

from playwright.async_api import async_playwright

BASE_URL = "https://37nationalgamesgoa.in/sports/archery"
HEADLESS = False

OUTPUT_CSV = "archery_elimination_2023.csv"
OUTPUT_JSON = "archery_elimination_2023.json"

FIELDNAMES = [
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


async def safe_text(el):
    try:
        return (await el.inner_text()).strip()
    except:
        return ""


def force_elimination(url):
    """Add stage=elimination to the URL."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    qs["stage"] = ["elimination"]

    new_query = urlencode(qs, doseq=True)

    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"


async def get_event_cards(page):
    """Discover event cards on the archery page."""
    await page.wait_for_selector(".styles_cardMainContainer__rQzdE")

    cards = page.locator(".styles_cardMainContainer__rQzdE")

    results = []

    count = await cards.count()

    for i in range(count):
        card = cards.nth(i)

        event = await safe_text(card.locator("p.defaultHeading"))

        buttons = card.locator("button")

        btn_count = await buttons.count()

        for j in range(btn_count):
            txt = (await safe_text(buttons.nth(j))).lower()

            if "fixture" in txt:
                results.append(
                    {
                        "event": event,
                        "card_index": i,
                    }
                )

    return results


async def open_fixture(page, card_index):
    """Click 'View Fixtures'."""
    cards = page.locator(".styles_cardMainContainer__rQzdE")
    card = cards.nth(card_index)

    buttons = card.locator("button")

    btn_count = await buttons.count()

    for j in range(btn_count):
        txt = (await safe_text(buttons.nth(j))).lower()

        if "fixture" in txt:
            await buttons.nth(j).click()
            await page.wait_for_load_state("networkidle")
            return page.url

    return None


async def parse_match(tile, event_name, round_name):

    teams = tile.locator("div.team p")
    spans = tile.locator("span.elimination-span-fixed-height")
    scores = tile.locator("div.score")

    state_a = await safe_text(teams.nth(0))
    state_b = await safe_text(teams.nth(1))

    player_a = await safe_text(spans.nth(0))
    player_b = await safe_text(spans.nth(1))

    score_a = await safe_text(scores.nth(0))
    score_b = await safe_text(scores.nth(1))

    winner = ""

    try:
        if int(score_a) > int(score_b):
            winner = player_a
        elif int(score_b) > int(score_a):
            winner = player_b
    except:
        pass

    return {
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


async def extract_bracket(page, event_name):
    rows = []

    # round headers
    headers = page.locator("div.bgColor-gradient-maroon")
    header_count = await headers.count()

    round_names = []

    for i in range(header_count):
        round_names.append(await safe_text(headers.nth(i)))

    print("    rounds:", round_names)

    # columns
    columns = page.locator("div.position-relative")

    col_count = await columns.count()

    for i in range(col_count):

        round_name = (
            round_names[i] if i < len(round_names) else f"Round {i+1}"
        )

        tiles = columns.nth(i).locator("div.event-tile")

        tile_count = await tiles.count()

        for j in range(tile_count):

            row = await parse_match(
                tiles.nth(j),
                event_name,
                round_name,
            )

            rows.append(row)

    return rows


async def main():

    all_rows = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=HEADLESS)

        context = await browser.new_context()

        page = await context.new_page()

        print("Loading archery page...")
        await page.goto(BASE_URL)

        events = await get_event_cards(page)

        print(f"Found {len(events)} events")

        for item in events:

            event = item["event"]
            idx = item["card_index"]

            print(f"\n── {event}")

            await page.goto(BASE_URL)

            fixture_url = await open_fixture(page, idx)

            if not fixture_url:
                print("   skipped")
                continue

            elimination_url = force_elimination(fixture_url)

            event_page = await context.new_page()

            await event_page.goto(elimination_url)

            await event_page.wait_for_selector("div.event-tile", timeout=20000)

            rows = await extract_bracket(event_page, event)

            print(f"   matches: {len(rows)}")

            all_rows.extend(rows)

            await event_page.close()

        await browser.close()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)

        writer.writeheader()

        writer.writerows(all_rows)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:

        json.dump(all_rows, f, indent=2)

    print("\nDone")
    print("rows:", len(all_rows))


if __name__ == "__main__":
    asyncio.run(main())