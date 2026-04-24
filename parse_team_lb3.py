from bs4 import BeautifulSoup
import re

with open("team_leaderboard.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

rows = soup.find_all("div", class_="row")
for row in rows:
    # If the row has children cols
    cols = row.find_all("div", class_=re.compile("col-sm"))
    if len(cols) >= 5:
        event = cols[1].text.strip()
        player = cols[3].text.strip()
        state = cols[4].text.strip()
        if "Haryana" in state or "Maharashtra" in state:
            print(f"State: {state} | Player: {player}")
