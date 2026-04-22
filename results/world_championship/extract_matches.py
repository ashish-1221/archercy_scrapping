import json
import os
import csv
import glob
import re

def get_athlete_name(athlete):
    if not athlete:
        return ""
    gname = athlete.get("GName") or ""
    fname = athlete.get("FName") or ""
    if gname and fname:
        return f"{gname} {fname}"
    return gname or fname or ""

EVENT_NAMES = {
    "RM": "Recurve Men",
    "RW": "Recurve Women",
    "RX": "Recurve Mixed Team",
    "CM": "Compound Men",
    "CW": "Compound Women",
    "CX": "Compound Mixed Team"
}

ROUND_NAMES = {
    0: "Gold Medal Match",
    1: "Bronze Medal Match",
    2: "Semifinals",
    4: "Quarterfinals",
    8: "1/8 Eliminations",
    12: "1/12 Eliminations",
    16: "1/16 Eliminations",
    24: "1/24 Eliminations",
    32: "1/32 Eliminations",
    48: "1/48 Eliminations",
    64: "1/64 Eliminations"
}

def process_files(input_dir, output_csv):
    files = glob.glob(os.path.join(input_dir, 'world_*.json'))
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['winner', 'event_name', 'country', 'score_a', 'player_b', 'player_a', 'championship_name', 'score_b', 'round_name'])
        
        for file in files:
            filename = os.path.basename(file)
            
            # Extract year from filename like world_2021_team.json
            match = re.search(r'world_(\d{4})', filename)
            year = match.group(1) if match else ''
            championship_name = f"World Archery Championship {year}" if year else filename.replace('.json', '')
            
            is_team = 'team' in filename
            
            with open(file, 'r', encoding='utf-8') as json_file:
                try:
                    data_pages = json.load(json_file)
                except Exception as e:
                    print(f"Error reading {file}: {e}")
                    continue
                
                for page in data_pages:
                    for item in page.get('items', []):
                        event_name = item.get('Code', '')
                        
                        for match in item.get('Matches', []):
                            comp1 = match.get('Competitor1', {})
                            comp2 = match.get('Competitor2', {})
                            
                            score_a = comp1.get('Score', '')
                            score_b = comp2.get('Score', '')
                            round_phase = match.get('Phase', '')
                            
                            full_event_name = EVENT_NAMES.get(event_name, event_name)
                            full_round_name = ROUND_NAMES.get(round_phase, str(round_phase))
                            
                            if is_team:
                                members_a = comp1.get('Members', [])
                                members_b = comp2.get('Members', [])
                                player_a = ", ".join(filter(bool, [get_athlete_name(m) for m in members_a])) if members_a else comp1.get('Name', '')
                                player_b = ", ".join(filter(bool, [get_athlete_name(m) for m in members_b])) if members_b else comp2.get('Name', '')
                                winner_name_a = player_a
                                winner_name_b = player_b
                                noc_a = comp1.get('NOC', '') or ''
                                noc_b = comp2.get('NOC', '') or ''
                            else:
                                ath1 = comp1.get('Athlete', {})
                                ath2 = comp2.get('Athlete', {})
                                player_a = get_athlete_name(ath1)
                                player_b = get_athlete_name(ath2)
                                winner_name_a = player_a
                                winner_name_b = player_b
                                noc_a = ath1.get('NOC', '') if isinstance(ath1, dict) else ''
                                noc_b = ath2.get('NOC', '') if isinstance(ath2, dict) else ''
                                
                            # Determine winner
                            winner = ''
                            country = ''
                            
                            # Filter empty/dummy matches
                            if not player_a and not player_b:
                                continue
                                
                            if comp1.get('WinLose') == True:
                                winner = winner_name_a
                                country = noc_a
                            elif comp2.get('WinLose') == True:
                                winner = winner_name_b
                                country = noc_b
                            
                            writer.writerow([winner, full_event_name, country, score_a, player_b, player_a, championship_name, score_b, full_round_name])

if __name__ == '__main__':
    input_dir = '/home/ashish-1221/archery_scrapping/archercy_scrapping/results/world_championship/results'
    output_csv = '/home/ashish-1221/archery_scrapping/archercy_scrapping/results/world_championship/extracted_matches.csv'
    process_files(input_dir, output_csv)
    print(f"Extraction complete. Data saved to {output_csv}")
