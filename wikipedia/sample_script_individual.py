import csv
import re
from bs4 import BeautifulSoup

INPUT_FILE = "/home/ashish-1221/archery_scrapping/archercy_scrapping/wikipedia_saved_pages/archery_at_the_2024_summer_olympics_-e2-80-93_women-27s_individual.html"
OUTPUT_FILE = "competition_bracket.csv"


ROUND_HEADERS = (
    "Round of 64",
    "Round of 32",
    "Round of 16",
    "1/32 eliminations",
    "1/16 eliminations",
    "1/8 eliminations",
    "Quarter-finals",
    "Quarterfinals",
    "Semi-finals",
    "Semifinals",
    "Gold medal match",
    "Bronze medal match",
)


# -------------------------------
# Utility functions
# -------------------------------

def clean_text(cell):
    if not cell:
        return ""
    return " ".join(cell.get_text(" ", strip=True).split())


def normalize_header(text):
    lowered = text.strip().lower()
    return "".join(char for char in lowered if char.isalnum())


def extract_player_name(cell):
    if not cell:
        return ""

    player_link = cell.find("a")
    if player_link:
        return " ".join(player_link.get_text(" ", strip=True).split())

    return clean_text(cell)


def extract_player_key(cell):
    if not cell:
        return ""

    player_link = cell.find("a")
    if player_link:
        return player_link.get("href") or player_link.get("title") or clean_text(player_link)

    return clean_text(cell)


def normalize_player_key(value):
    if not value:
        return ""
    return value.replace(" (page does not exist)", "").strip()


def extract_player_lookup_keys(cell):
    if not cell:
        return []

    keys = []
    player_link = cell.find("a")

    if player_link:
        keys.extend([
            player_link.get("href"),
            player_link.get("title"),
            clean_text(player_link),
        ])

    keys.append(clean_text(cell))

    normalized_keys = []
    for key in keys:
        if not key:
            continue
        normalized_keys.append(key)
        normalized_keys.append(normalize_player_key(key))

    deduped_keys = []
    seen = set()
    for key in normalized_keys:
        if key and key not in seen:
            seen.add(key)
            deduped_keys.append(key)

    return deduped_keys


def format_player(name, country):
    return f"{name} ({country})" if country else name


def extract_heading_text(node):
    return clean_text(node) if node else ""


def use_last_score_cell(soup):
    heading = clean_text(soup.find("h1")) or clean_text(soup.find("title"))
    return "2022 Asian Games" in heading and soup.find(id="Knockout_round") is not None


def render_table_grid(table):
    rows = table.find_all("tr")
    pending = {}
    grid = []

    for row_idx, tr in enumerate(rows):
        row = []
        col_idx = 0

        while (row_idx, col_idx) in pending:
            row.append(pending[(row_idx, col_idx)])
            col_idx += 1

        for cell in tr.find_all(["td", "th"], recursive=False):
            while (row_idx, col_idx) in pending:
                row.append(pending[(row_idx, col_idx)])
                col_idx += 1

            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))

            for _ in range(colspan):
                row.append(cell)
                col_idx += 1

            for next_row in range(row_idx + 1, row_idx + rowspan):
                for next_col in range(col_idx - colspan, col_idx):
                    pending[(next_row, next_col)] = cell

        grid.append(row)

    width = max(len(row) for row in grid)
    for row in grid:
        row.extend([None] * (width - len(row)))

    return grid


def get_round_occurrences(grid):
    seen_cells = set()
    occurrences = []

    for row_idx, row in enumerate(grid):
        for col_idx, cell in enumerate(row):
            if not cell:
                continue

            if id(cell) in seen_cells:
                continue

            seen_cells.add(id(cell))
            label = clean_text(cell)
            if label in ROUND_HEADERS:
                occurrences.append({
                    "round": label,
                    "row": row_idx,
                    "col": col_idx,
                    "span": int(cell.get("colspan", 1)),
                })

    return occurrences


def score_key(score):
    numbers = [int(value) for value in re.findall(r"\d+", score)]
    return tuple(numbers)


def pick_winner(entry_a, entry_b):
    if entry_a["is_winner"] != entry_b["is_winner"]:
        return entry_a["player"] if entry_a["is_winner"] else entry_b["player"]

    if score_key(entry_a["score"]) != score_key(entry_b["score"]):
        return entry_a["player"] if score_key(entry_a["score"]) > score_key(entry_b["score"]) else entry_b["player"]

    return ""


def extract_player_country_map(soup):
    ranking_round = (
        soup.find(id="Ranking_round_2")
        or soup.find(id="Ranking_round")
        or soup.find(id="Qualification_round")
    )
    if not ranking_round:
        raise ValueError("Ranking or qualification round section not found")

    ranking_heading = ranking_round.find_parent("div", class_="mw-heading") or ranking_round.parent
    ranking_table = None

    for tag in ranking_heading.find_next_siblings():
        if getattr(tag, "name", None) == "table":
            ranking_table = tag
            break

    if ranking_table is None:
        raise ValueError("Ranking round table not found")

    player_country_map = {}
    grid = render_table_grid(ranking_table)
    athlete_col = None
    country_col = None

    for row in grid:
        if any(cell and cell.name == "td" for cell in row):
            break

        for col_idx, cell in enumerate(row):
            normalized = normalize_header(clean_text(cell))
            if normalized in {"athlete", "archer", "archers"} and athlete_col is None:
                athlete_col = col_idx
            if normalized in {"country", "nation", "noc", "team"} and country_col is None:
                country_col = col_idx

    for row in grid:
        if not any(cell and cell.name == "td" for cell in row):
            continue

        if athlete_col is not None and athlete_col < len(row):
            archer_cell = row[athlete_col]
        else:
            archer_cell = next(
                (
                    cell for cell in row
                    if cell
                    and cell.name == "td"
                    and len(clean_text(cell)) > 3
                    and any(char.isalpha() for char in clean_text(cell))
                ),
                None,
            )

        if not archer_cell:
            continue

        country_candidate = ""
        if country_col is not None and country_col < len(row) and row[country_col]:
            country_candidate = clean_text(row[country_col])

        if country_candidate and not any(char.isdigit() for char in country_candidate):
            country = country_candidate
        else:
            match = re.search(r"\(([^)]+)\)", clean_text(archer_cell))
            country = match.group(1).strip() if match else ""

        for key in extract_player_lookup_keys(archer_cell):
            player_country_map[key] = country

    return player_country_map


def extract_score_from_cells(cells, prefer_last=False):
    scores = [clean_text(cell) for cell in cells if clean_text(cell)]
    if not scores:
        return ""
    return scores[-1] if prefer_last else scores[0]


def extract_matches_from_table(table, player_country_map, section_name="", prefer_last_score=False):
    grid = render_table_grid(table)
    round_occurrences = get_round_occurrences(grid)
    matches = []

    for index, occurrence in enumerate(round_occurrences):
        match_round = occurrence["round"]
        start_col = occurrence["col"]
        end_col = start_col + occurrence["span"]
        start_row = occurrence["row"] + 1

        end_row = len(grid)
        for next_occurrence in round_occurrences[index + 1:]:
            if next_occurrence["col"] == start_col:
                end_row = next_occurrence["row"]
                break

        entries = []
        previous_key = None

        for row in grid[start_row:end_row]:
            if start_col + 2 >= len(row):
                continue

            name_cell = row[start_col + 1]
            score_cells = row[start_col + 2:end_col]
            score_cell = row[start_col + 2]

            player_name = extract_player_name(name_cell)
            score = extract_score_from_cells(score_cells, prefer_last=prefer_last_score)

            if not player_name:
                continue

            dedupe_key = (player_name, score)
            if dedupe_key == previous_key:
                continue

            previous_key = dedupe_key
            country = ""
            for key in extract_player_lookup_keys(name_cell):
                if key in player_country_map:
                    country = player_country_map[key]
                    break

            entries.append({
                "player": format_player(player_name, country),
                "score": score,
                "is_winner": bool(
                    (name_cell and name_cell.find("b"))
                    or any(cell and cell.find("b") for cell in score_cells)
                    or (score_cell and score_cell.find("b"))
                ),
            })

        if len(entries) % 2 != 0:
            raise ValueError(f"Uneven number of entries found for {match_round}: {len(entries)}")

        for idx in range(0, len(entries), 2):
            player_a = entries[idx]
            player_b = entries[idx + 1]
            matches.append({
                "player_a": player_a["player"],
                "player_b": player_b["player"],
                "score_a": player_a["score"],
                "score_b": player_b["score"],
                "winner": pick_winner(player_a, player_b),
                "round": match_round,
                "round_name": section_name,
            })

    return matches


# -------------------------------
# Main extraction logic
# -------------------------------

def extract_bracket(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    player_country_map = extract_player_country_map(soup)
    bracket = (
        soup.find(id="Competition_bracket")
        or soup.find(id="Knockout_round")
        or soup.find(id="Elimination_rounds_2")
        or soup.find(id="Elimination_rounds")
    )
    if not bracket:
        raise ValueError("Competition bracket, knockout round, or elimination rounds section not found")

    results = []
    bracket_heading = bracket.find_parent("div", class_="mw-heading") or bracket.parent
    prefer_last_score = use_last_score_cell(soup)

    for tag in bracket_heading.find_next_siblings():
        tag_name = getattr(tag, "name", None)
        if tag_name != "div":
            continue

        heading_h2 = tag.find("h2")
        heading_h3 = tag.find("h3")

        finals_heading = None
        if heading_h2 and heading_h2.get("id") == "Finals":
            finals_heading = heading_h2
        elif heading_h3 and heading_h3.get("id") == "Finals":
            finals_heading = heading_h3

        if finals_heading:
            table = tag.find_next_sibling("table")
            if table:
                results.extend(
                    extract_matches_from_table(
                        table,
                        player_country_map,
                        extract_heading_text(finals_heading),
                        prefer_last_score,
                    )
                )
            break

        if heading_h2:
            break

        section = tag.find("h4")
        if not section:
            continue

        table = tag.find_next_sibling("table")
        if not table:
            continue

        results.extend(
            extract_matches_from_table(
                table,
                player_country_map,
                extract_heading_text(section),
                prefer_last_score,
            )
        )

    return results


# -------------------------------
# Run script
# -------------------------------

if __name__ == "__main__":
    data = extract_bracket(INPUT_FILE)

    print(f"Extracted {len(data)} matches\n")

    # Print sample
    for row in data[:10]:
        print(row)

    # Save CSV
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["player_a", "player_b", "score_a", "score_b", "winner", "round", "round_name"]
        )
        writer.writeheader()
        writer.writerows(data)

    print(f"\nSaved to {OUTPUT_FILE}")
