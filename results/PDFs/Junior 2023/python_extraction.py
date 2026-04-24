import pdfplumber
import pandas as pd

rows = []
event = None

with pdfplumber.open("junior_2023_player_info_3.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        lines = text.split("\n")

        for line in lines:
            if "RECURVE MEN" in line:
                event = "RECURVE MEN"
            elif "RECURVE WOMEN" in line:
                event = "RECURVE WOMEN"
            elif "COMPOUND MEN" in line:
                event = "COMPOUND MEN"
            elif "COMPOUND WOMEN" in line:
                event = "COMPOUND WOMEN"
            elif "INDIAN ROUND MEN" in line:
                event = "INDIAN ROUND MEN"
            elif "INDIAN ROUND WOMEN" in line:
                event = "INDIAN ROUND WOMEN"

            parts = line.split()
            if len(parts) > 5 and "." in line:
                try:
                    name = " ".join(parts[2:-5])
                    dob = parts[-5]
                    state = parts[-3]
                    rows.append([event, name, dob, state])
                except:
                    pass

df = pd.DataFrame(rows, columns=["event_name", "name", "dob", "state/unit"])
df.to_csv("junior_2023_player_info_3.csv", index=False)
