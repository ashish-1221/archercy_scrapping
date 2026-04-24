from bs4 import BeautifulSoup
import json
import re

with open("leaderboard.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Find table rows or divs that might be part of the leaderboard
for div in soup.find_all('div', class_=re.compile('row|item|card|list', re.I)):
    text = div.text.strip()
    if len(text) > 5 and len(text) < 200:
        print(div.get('class'), text)

print("--- ALL TEXT ---")
print(soup.text[:2000])

