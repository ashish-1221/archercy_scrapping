import asyncio
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

BASE_URL = "https://37nationalgamesgoa.in/sports/archery"

OUTPUT_CSV = "results/national_games/archery_elimination_2023.csv"
OUTPUT_JSON = "results/national_games/archery_elimination_2023.json"

CHAMPIONSHIP_NAME = "37th National Games Goa"

HEADLESS = False

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


async def safe_text(el):
    try:
        return (await el.inner_text()).strip()
    except:
        return ""


def change_to_elimination(url: str):
    parsed = urlparse(url)
    new_path = parsed.path.replace("/leaderboard", "/elimination")

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            new_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def split_player_state(text):

    match = re.match(r"(.*?)\s*\((.*?)\)", text)

    if match:
        return match.group(1).strip(), match.group(2).strip()

    return text.strip(), ""


async def parse_match_tile(tile, championship_name, event_name, round_name):

    try:

        # Try player-based layout first
        players = await tile.query_selector_all("div.line-clamp-2")
        scores = await tile.query_selector_all("div.score")

        player_a = ""
        player_b = ""
        state_a = ""
        state_b = ""

        # -------------------------
        # INDIVIDUAL EVENTS
        # -------------------------
        if players and (await safe_text(players[0])):

            player_a_raw = await safe_text(players[0])
            player_b_raw = await safe_text(players[1]) if len(players) > 1 else ""

            player_a, state_a = split_player_state(player_a_raw)
            player_b, state_b = split_player_state(player_b_raw)

        # -------------------------
        # TEAM EVENTS
        # -------------------------
        else:

            teams = await tile.query_selector_all("div.team p")

            if len(teams) >= 2:

                state_a = await safe_text(teams[0])
                state_b = await safe_text(teams[1])

                player_a = state_a
                player_b = state_b

        # -------------------------
        # SCORES
        # -------------------------
        score_a = await safe_text(scores[0]) if len(scores) > 0 else ""
        score_b = await safe_text(scores[1]) if len(scores) > 1 else ""

        # -------------------------
        # WINNER
        # -------------------------
        winner = ""

        try:
            if int(score_a) > int(score_b):
                winner = player_a
            elif int(score_b) > int(score_a):
                winner = player_b
        except:
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
        print("parse error:", e)
        return None

async def extract_elimination_data(page, championship_name, event_name):

    rows = []

    round_names = []
    header_row = await page.query_selector("div.flex.gap-4.m-4.w-100")
    if header_row:
        header_items = await header_row.query_selector_all(":scope > div")
        for item in header_items:
            text = (await safe_text(item)).strip()
            if text:
                round_names.append(text)

    print("    Round names found:", round_names)

    bracket_containers = await page.query_selector_all(
        "div.m-4.flex.gap-4, div.m-5.d-flex.gap-4"
    )

    for bracket in bracket_containers:

        columns = await bracket.query_selector_all(":scope > div.position-relative")

        for col_index, column in enumerate(columns):

            round_name = (
                round_names[col_index]
                if col_index < len(round_names)
                else f"Round {col_index+1}"
            )

            tiles = await column.query_selector_all("div.event-tile")

            for tile in tiles:

                row = await parse_match_tile(
                    tile, championship_name, event_name, round_name
                )

                if row:
                    rows.append(row)

    return rows


async def get_event_cards(page):

    await page.wait_for_selector(".styles_cardMainContainer__rQzdE")

    cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")

    print("  Found", len(cards), "cards total")

    results = []

    for i, card in enumerate(cards):

        event = await safe_text(await card.query_selector("p.defaultHeading"))

        buttons = await card.query_selector_all("button")

        for btn in buttons:

            if "fixture" in (await safe_text(btn)).lower():

                results.append(
                    {
                        "event": event,
                        "card_index": i,
                    }
                )

                print(f"    [{i:02d}] {event}")

                break

    return results


async def click_view_fixtures(page, card_index):

    cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")

    card = cards[card_index]

    buttons = await card.query_selector_all("button")

    for btn in buttons:

        if "fixture" in (await safe_text(btn)).lower():

            current_url = page.url

            await btn.scroll_into_view_if_needed()

            await btn.click()

            await page.wait_for_function(
                f"() => window.location.href !== '{current_url}'"
            )

            await page.wait_for_load_state("networkidle")

            leaderboard_url = page.url

            print("    ✔ Navigated →", leaderboard_url)

            elimination_url = change_to_elimination(leaderboard_url)

            await page.goto(elimination_url, wait_until="networkidle")

            print("    ✔ Switched →", elimination_url)

            return True

    return False


async def main():

    all_rows = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=HEADLESS)

        context = await browser.new_context()

        page = await context.new_page()

        print("Loading", BASE_URL)

        await page.goto(BASE_URL, wait_until="networkidle")

        print("Discovering event cards …")

        event_cards = await get_event_cards(page)

        print("\nFound", len(event_cards), "events\n")

        for item in event_cards:

            event_name = item["event"]
            card_index = item["card_index"]

            print(f"── [{card_index:02d}] {event_name}")

            if page.url.rstrip("/") != BASE_URL.rstrip("/"):

                print("     Returning to archery page ...")

                await page.goto(BASE_URL, wait_until="networkidle")

            ok = await click_view_fixtures(page, card_index)

            if not ok:
                print("     Skipped\n")
                continue

            rows = await extract_elimination_data(
                page, CHAMPIONSHIP_NAME, event_name
            )

            print("     Extracted", len(rows), "match rows\n")

            all_rows.extend(rows)

        await browser.close()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)

        writer.writeheader()

        writer.writerows(all_rows)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:

        json.dump(all_rows, f, indent=2)

    print("\nDone — total rows:", len(all_rows))


if __name__ == "__main__":
    asyncio.run(main())