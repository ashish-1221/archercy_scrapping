from bs4 import BeautifulSoup
import json
import re

with open("leaderboard.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

print("Just looking for a known state e.g. HARYANA")
for el in soup.find_all(string=re.compile("HARYANA", re.I)):
    parent = el.parent
    print("HARYANA found in tag:", parent.name, parent.get('class'))
    gp = parent.parent
    if gp:
        print("Grandparent tag:", gp.name, gp.get('class'))
        print("Grandparent text:", gp.text.strip()[:100])
        ggp = gp.parent
        if ggp:
            print("Great-grandparent class:", ggp.get('class'))
            print("Great-grandparent text:", ggp.text.strip())
            print("---")
