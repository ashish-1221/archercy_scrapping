import asyncio
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

BASE_URL = "https://38nguk.in/sports/archery"

OUTPUT_CSV = "results/national_games/archery_elimination_2025.csv"
OUTPUT_JSON = "results/national_games/archery_elimination_2025.json"

CHAMPIONSHIP_NAME = "38th National Games Uttarakhand"

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
    "winner_state",
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


# ---------------------------------------------------------------------------
# Static fallback rosters – used when the website leaderboard is empty.
# Keys are normalised event name fragments (lowercase).
# ---------------------------------------------------------------------------
STATIC_ROSTERS: dict[str, dict[str, list[str]]] = {
    "compound women team": {
        "Rajasthan": ["SONALI NATH", "POONAM CHAUDHARY", "PRIYA GURJAR"],
        "Punjab": ["MUSKAN KIRAR", "HARPREET KAUR", "SIMRANPREET KAUR BRAR"],
        "Maharashtra": ["JYOTHI SUREKHA VENNAM", "ADITI SWAMI", "BHAJAN KAUR"],
        "Madhya Pradesh": ["PROMILA DAIMARY", "PALLAVI DEVI", "ANKITA BHAKAT"],
        "Uttar Pradesh": ["TRISHA DEY", "NIKITA", "PRAJAKTA"],
        "Gujarat": ["MANVI SINGLA", "SWAPNA", "SUMATI BAINIWAL"],
        "Andhra Pradesh": ["SUREKHA", "LAXMI", "BHAVANI"],
        "Goa": ["RISHA SHETGAONKAR", "SHIVANI", "DIKSHA GURAV"],
    },
}


def get_static_roster(event_name: str) -> dict[str, list[str]]:
    """Return a static roster for *event_name* if one exists, else {}."""
    norm = re.sub(r"[^a-z0-9 ]+", " ", event_name.lower()).strip()
    for key, roster in STATIC_ROSTERS.items():
        if key in norm:
            return roster
    return {}


def get_event_category(event_name):
    name = event_name.lower()
    weapon = ""
    if "compound" in name:
        weapon = "compound"
    elif "recurve" in name or "recureve" in name:
        weapon = "recurve"
    elif "indian" in name or "inidan" in name:
        weapon = "indian round"

    gender = ""
    if "women" in name:
        gender = "women"
    elif "men" in name:
        gender = "men"
    elif "mixed" in name:
        gender = "mixed"

    return f"{weapon} {gender}".strip()


def split_player_state(text):

    match = re.match(r"(.*?)\s*\((.*?)\)", text)

    if match:
        return match.group(1).strip(), match.group(2).strip()

    return text.strip(), ""


async def parse_match_tile(
    tile, championship_name, event_name, round_name, state_to_players=None
):

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

                # Normalize keys for lookup
                normalized_map = {}
                if state_to_players:
                    normalized_map = {
                        re.sub(r"[^a-z0-9]+", " ", k.lower()).strip(): v
                        for k, v in state_to_players.items()
                    }

                norm_a = re.sub(r"[^a-z0-9]+", " ", state_a.lower()).strip()
                if state_to_players and norm_a in normalized_map:
                    player_a = " / ".join(normalized_map[norm_a])
                else:
                    player_a = state_a

                norm_b = re.sub(r"[^a-z0-9]+", " ", state_b.lower()).strip()
                if state_to_players and norm_b in normalized_map:
                    player_b = " / ".join(normalized_map[norm_b])
                else:
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


async def extract_elimination_data(
    page, championship_name, event_name, global_rosters=None
):

    rows = []

    round_names = []
    header_row = await page.query_selector("div.d-flex.gap-4.m-5.w-100")
    if header_row:
        header_items = await header_row.query_selector_all(":scope > div")
        print("header_items", header_items)
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

                # Get the relevant state_to_players for this category
                category = get_event_category(event_name)
                state_to_players = (
                    global_rosters.get(category, {}) if global_rosters else {}
                )

                row = await parse_match_tile(
                    tile, championship_name, event_name, round_name, state_to_players
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

        event = await safe_text(await card.query_selector("p.sport_event_Card_para"))

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


async def click_view_fixtures(page, card_index, event_name):

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

            # Always try to extract players from the leaderboard
            try:
                await page.wait_for_selector("div.row", timeout=5000)
                await page.wait_for_timeout(1000)
            except Exception:
                pass

            state_to_players = await page.evaluate(
                """() => {
                const map = {};
                document.querySelectorAll("div.row").forEach(row => {
                    const cols = row.querySelectorAll("div[class*='col-sm']");
                    // Individual events: try col indices [3]=player, [4]=state
                    // Some pages use [2]=player, [3]=state — try both layouts
                    const layouts = [{p: 3, s: 4}, {p: 2, s: 3}];
                    for (const {p, s} of layouts) {
                        if (cols.length > s) {
                            const player = cols[p].innerText.trim();
                            const state  = cols[s].innerText.trim();
                            if (player && state && !/^\\d+$/.test(player)) {
                                if (!map[state]) map[state] = [];
                                if (!map[state].includes(player)) map[state].push(player);
                                break;
                            }
                        }
                    }
                });
                return map;
            }"""
            )

            elimination_url = change_to_elimination(leaderboard_url)

            await page.goto(elimination_url, wait_until="networkidle")

            print("    ✔ Switched →", elimination_url)

            return True, state_to_players

    return False, {}


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

        global_rosters = {}
        for item in event_cards:

            event_name = item["event"]
            card_index = item["card_index"]
            category = get_event_category(event_name)

            print(f"── [{card_index:02d}] {event_name}")

            if page.url.rstrip("/") != BASE_URL.rstrip("/"):

                print("     Returning to archery page ...")

                await page.goto(BASE_URL, wait_until="networkidle")

            ok, state_to_players = await click_view_fixtures(
                page, card_index, event_name
            )

            if not ok:
                print("     Skipped\n")
                continue

            if category not in global_rosters:
                global_rosters[category] = {}

            for state, players in state_to_players.items():
                if state not in global_rosters[category]:
                    global_rosters[category][state] = []
                for p in players:
                    if p not in global_rosters[category][state]:
                        global_rosters[category][state].append(p)

            # For team/mixed events the leaderboard page has no individual player
            # columns, so state_to_players is always empty — that's expected.
            # Only warn/fall back when the category roster is genuinely missing.
            is_team = "team" in event_name.lower() or "mixed" in event_name.lower()
            category_has_data = bool(global_rosters.get(category))
            if is_team and not category_has_data:
                static = get_static_roster(event_name)
                if static:
                    print(
                        f"     ⚠  No live leaderboard data — using static fallback for '{event_name}'"
                    )
                    for state, players in static.items():
                        if state not in global_rosters[category]:
                            global_rosters[category][state] = []
                        for p in players:
                            if p not in global_rosters[category][state]:
                                global_rosters[category][state].append(p)
                else:
                    print(
                        f"     ⚠  No roster data found for '{event_name}' — state names will be used"
                    )
            elif is_team and category_has_data:
                print(
                    f"     ✔  Using {len(global_rosters[category])} states from global roster for '{event_name}'"
                )

            rows = await extract_elimination_data(
                page, CHAMPIONSHIP_NAME, event_name, global_rosters
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
