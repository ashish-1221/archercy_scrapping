from bs4 import BeautifulSoup

with open("team_leaderboard.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Find table, div.table, or anything that looks like a table/row
print("Looking for tables:")
for table in soup.find_all("table"):
    print(table.get("class"))
    # print headers
    th = table.find_all("th")
    print("Headers:", [t.text.strip() for t in th])
    
    # print first 2 rows
    for tr in table.find_all("tr")[:3]:
        tds = tr.find_all("td")
        if tds:
            print("Row:", [t.text.strip() for t in tds])
    print("---")

print("If no table, looking for elements containing 'HARYANA' or 'MAHARASHTRA':")
import re
for state in ["HARYANA", "MAHARASHTRA", "Haryana", "Maharashtra"]:
    for el in soup.find_all(string=re.compile(state, re.I)):
        print(f"Found {state} in tag: {el.parent.name}, class: {el.parent.get('class')}")
        print("Text:", el.parent.text.strip())
        print("Parent tag:", el.parent.parent.name, "class:", el.parent.parent.get('class'))
        print("Parent text snippet:", el.parent.parent.text.strip()[:100])
        print("-")
        break
