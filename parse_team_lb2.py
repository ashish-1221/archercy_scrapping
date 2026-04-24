from bs4 import BeautifulSoup

with open("team_leaderboard.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

import re
state_el = soup.find(string=re.compile("Haryana", re.I))
if state_el:
    # Go up to the row-like container
    # let's look at the parent's parent
    parent_div = state_el.parent.parent
    row = parent_div.parent
    print("Row class:", row.get("class"))
    
    # print all text in this row
    print("Row text:", row.text.strip())
    
    # Let's see the structure inside the row
    for child in row.children:
        if child.name:
            print("Child:", child.name, child.get("class"))
            print("Text:", child.text.strip()[:100])
            print("---")
