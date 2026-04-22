import csv
import re
from bs4 import BeautifulSoup

INPUT_FILE = "/home/ashish-1221/archery_scrapping/archercy_scrapping/wikipedia_saved_pages/archery_at_the_2024_summer_olympics_-e2-80-93_mixed_team.html"
OUTPUT_FILE = "competition_bracket_mixed_team.csv"


ROUND_HEADERS = (
    "1/8 eliminations",
    "Quarter-finals",
    "Quarterfinals",
    "Semi-finals",
    "Semifinals",
    "Gold medal match",
    "Bronze medal match",
    "Bronze Medal Match",
)


def clean_text(cell):
    if not cell:
        return ""
    return " ".join(cell.get_text(" ", strip=True).split())


def normalize_country(country):
    return re.sub(r'\s*\([A-Za-z0-9]{3}\)$', '', country).strip()


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


def extract_set_point_score(row, start_col, end_col, prefer_last=False):
    scores = [clean_text(cell) for cell in row[start_col + 2:end_col] if clean_text(cell)]
    if not scores:
        return ""
    return scores[-1] if prefer_last else scores[0]


def pick_winner(entry_a, entry_b):
    if score_key(entry_a["score"]) != score_key(entry_b["score"]):
        return entry_a["player"] if score_key(entry_a["score"]) > score_key(entry_b["score"]) else entry_b["player"]
    return ""


def format_athlete(name, country):
    return f"{name} ({country})" if country else name


def format_team(country, archers):
    return " / ".join(archers) if archers else country


def extract_heading_text(node):
    return clean_text(node) if node else ""


def use_last_score_cell(soup):
    heading = clean_text(soup.find("h1")) or clean_text(soup.find("title"))
    return "2022 Asian Games" in heading and soup.find(id="Knockout_round") is not None


def explode_match_rows(matches):
    """Split each mixed team match into individual athlete rows (male + female).
    If the two teams have different squad sizes (e.g. due to reserve archers),
    the shorter list is padded with empty strings so we never crash."""
    exploded = []

    for match in matches:
        player_a_members = match["player_a"].split(" / ")
        player_b_members = match["player_b"].split(" / ")
        winner_members = match["winner"].split(" / ") if match["winner"] else []

        row_count = max(len(player_a_members), len(player_b_members))
        if row_count == 0:
            continue

        # Pad shorter lists with empty strings so indexing never raises
        while len(player_a_members) < row_count:
            player_a_members.append("")
        while len(player_b_members) < row_count:
            player_b_members.append("")
        while winner_members and len(winner_members) < row_count:
            winner_members.append("")

        for idx in range(row_count):
            exploded.append({
                "player_a": player_a_members[idx],
                "player_b": player_b_members[idx],
                "score_a": match["score_a"],
                "score_b": match["score_b"],
                "winner": winner_members[idx] if winner_members else "",
                "round": match["round"],
                "round_name": match["round_name"],
            })

    return exploded


def extract_team_map(soup):
    ranking_round = soup.find(id="Ranking_round") or soup.find(id="Qualification_round")
    if not ranking_round:
        for h in soup.find_all(["h2", "h3"]):
            if "qualification" in h.get_text(strip=True).lower() or "ranking" in h.get_text(strip=True).lower():
                ranking_round = h
                break

    if not ranking_round:
        raise ValueError("Ranking or qualification round section not found")

    ranking_heading = ranking_round if ranking_round.name in ["h2", "h3"] else (ranking_round.find_parent("div", class_="mw-heading") or ranking_round.parent)
    ranking_table = ranking_heading.find_next_sibling("table") or ranking_heading.find_next("table")

    if ranking_table is None:
        raise ValueError("Ranking round table not found")

    team_map = {}
    rows = ranking_table.find_all("tr")
    
    format_a = False
    for row in rows:
        headers = row.find_all("th")
        for th in headers:
            th_text = clean_text(th).lower()
            if "archer" in th_text or "name" in th_text or "athlete" in th_text:
                format_a = True
                break
        if format_a:
            break
            
    current_country = None
    
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
            
        if cells[0].name == "th":
            continue
            
        first_text = clean_text(cells[0])
        raw_second = clean_text(cells[1])
        second_text = normalize_country(raw_second)
        
        if format_a:
            if len(cells) >= 3:
                country = second_text
                
                combined_archers = [text.strip() for text in cells[2].stripped_strings if text.strip()]
                if len(combined_archers) >= 2:
                    archers = combined_archers
                elif len(cells) >= 4 and not any(c.isdigit() for c in clean_text(cells[3])):
                    archers = [clean_text(cells[2]), clean_text(cells[3])]
                    archers = [name for name in archers if name]
                else:
                    archers = combined_archers
                
                if country:
                    team_map[country] = [format_athlete(archer, country) for archer in archers]
        else:
            # Detect if this is a country row: first cell is a rank digit
            first_is_rank = first_text.isdigit()
            # Detect if second cell contains a score (digit-heavy), meaning first cell is the athlete name
            second_has_digits = any(c.isdigit() for c in raw_second)
            
            if first_is_rank:
                # Country row: rank | country | scores...
                current_country = second_text
                if current_country not in team_map:
                    team_map[current_country] = []
            elif not first_text or first_text in ("M", "W", "F"):
                # Archer row with empty, M, W, F gender marker in first col: | gender | name | scores
                if current_country and raw_second and not second_has_digits:
                    team_map[current_country].append(format_athlete(raw_second, current_country))
            elif not second_has_digits and len(cells) >= 2:
                # Archer row where athlete name IS the first cell (no rank/gender prefix)
                # e.g. ['Kim Woo-jin', '339', '336', ...]
                archer_name = first_text
                if current_country and archer_name:
                    team_map[current_country].append(format_athlete(archer_name, current_country))

    return team_map


def extract_matches_from_table(table, team_map, section_name="", prefer_last_score=False):
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

            country = normalize_country(clean_text(row[start_col + 1]))
            score = extract_set_point_score(row, start_col, end_col, prefer_last=prefer_last_score)

            if not country:
                continue

            dedupe_key = (country, score)
            if dedupe_key == previous_key:
                continue

            previous_key = dedupe_key
            entries.append({
                "country": country,
                "player": format_team(country, team_map.get(country, [])),
                "score": score,
            })

        if len(entries) % 2 != 0:
            raise ValueError(f"Uneven number of entries found for {match_round}: {len(entries)}")

        for idx in range(0, len(entries), 2):
            team_a = entries[idx]
            team_b = entries[idx + 1]
            matches.append({
                "player_a": team_a["player"],
                "player_b": team_b["player"],
                "score_a": team_a["score"],
                "score_b": team_b["score"],
                "winner": pick_winner(team_a, team_b),
                "round": match_round,
                "round_name": section_name,
            })

    return matches


def extract_bracket(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    team_map = extract_team_map(soup)
    bracket = soup.find(id="Competition_bracket") or soup.find(id="Knockout_round")
    if not bracket:
        raise ValueError("Competition bracket or knockout round section not found")

    bracket_heading = bracket.find_parent("div", class_="mw-heading") or bracket.parent
    bracket_table = bracket_heading.find_next_sibling("table")
    if bracket_table is None:
        raise ValueError("Competition bracket table not found")

    matches = extract_matches_from_table(
        bracket_table,
        team_map,
        extract_heading_text(bracket),
        use_last_score_cell(soup),
    )
    return explode_match_rows(matches)


if __name__ == "__main__":
    data = extract_bracket(INPUT_FILE)

    print(f"Extracted {len(data)} matches\n")
    for row in data[:10]:
        print(row)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["player_a", "player_b", "score_a", "score_b", "winner", "round", "round_name"],
        )
        writer.writeheader()
        writer.writerows(data)

    print(f"\nSaved to {OUTPUT_FILE}")
