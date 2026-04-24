#!/usr/bin/env python3

from __future__ import annotations

import re
from pathlib import Path
from io import StringIO

import pandas as pd
from playwright.sync_api import sync_playwright

ARCHERY_URL = "https://38nguk.in/sports/archery"


# ==============================
# 🔹 Browser Layer
# ==============================

def init_browser(headless=True):
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=headless)
    page = browser.new_page()
    return p, browser, page


def load_page(page):
    page.goto(ARCHERY_URL)
    page.wait_for_load_state("networkidle")


# ==============================
# 🔹 Event Navigation
# ==============================

def get_events(page):
    buttons = page.locator("a, button").filter(
        has_text=re.compile(r"^\s*fixtures\s*$", re.I)
    )
    return [buttons.nth(i).inner_text() for i in range(buttons.count())]


def open_event(page, index):
    buttons = page.locator("a, button").filter(
        has_text=re.compile(r"^\s*fixtures\s*$", re.I)
    )

    buttons.nth(index).click()
    page.wait_for_load_state("networkidle")

    # open leaderboard
    page.locator("a, button").filter(
        has_text=re.compile(r"leaderboard", re.I)
    ).first.click()

    page.wait_for_selector("table")


# ==============================
# 🔹 Table Extraction
# ==============================

def get_table_htmls(page):
    tables = page.locator("table")
    return [
        tables.nth(i).evaluate("(el) => el.outerHTML")
        for i in range(tables.count())
    ]


# ==============================
# 🔹 HTML → DataFrame
# ==============================

def htmls_to_frames(table_htmls):
    frames = []

    for html in table_htmls:
        try:
            dfs = pd.read_html(StringIO(html))
            frames.extend(dfs)
        except Exception:
            continue

    return frames


# ==============================
# 🔹 Cleaning / Normalization
# ==============================

def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def clean(val):
    if pd.isna(val):
        return ""
    return str(val).strip()


# ==============================
# 🔹 Column Detection
# ==============================

def find_column(headers, keywords):
    for h in headers:
        key = normalize(h)
        if any(k in key for k in keywords):
            return h
    return None


def split_players(value):
    text = clean(value)
    if not text:
        return []

    return [
        p.strip()
        for p in re.split(r"/|\||,|\n", text)
        if p.strip()
    ]


# ==============================
# 🔹 Core Extraction Logic
# ==============================

def extract_state_player_score(frames):
    results = []

    for df in frames:
        if df.empty:
            continue

        df.columns = [clean(c) for c in df.columns]
        headers = list(df.columns)

        state_col = find_column(headers, ["state", "team", "unit"])
        player_col = find_column(headers, ["name", "player", "athlete", "archer"])
        score_col = find_column(headers, ["score", "points", "total"])

        if not (state_col and player_col and score_col):
            continue

        for _, row in df.iterrows():
            state = clean(row[state_col])
            score = clean(row[score_col])

            players = split_players(row[player_col])

            for player in players:
                results.append({
                    "state": state,
                    "player": player,
                    "score": score
                })

    return results


# ==============================
# 🔹 Pipeline
# ==============================

def run_pipeline(page, output_dir: Path):
    all_records = []

    events = get_events(page)

    if not events:
        raise RuntimeError("No events found (Fixtures buttons missing)")

    for idx, event in enumerate(events):
        print(f"[INFO] Processing event {idx + 1}: {event}")

        open_event(page, idx)

        table_htmls = get_table_htmls(page)
        frames = htmls_to_frames(table_htmls)

        records = extract_state_player_score(frames)

        for r in records:
            r["event"] = event

        all_records.extend(records)

        # Go back to main page
        load_page(page)

    df = pd.DataFrame(all_records)

    output_file = output_dir / "archery_results.csv"
    df.to_csv(output_file, index=False)

    print(f"[DONE] Saved: {output_file}")
    return df


# ==============================
# 🔹 Main
# ==============================

def main():
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    p, browser, page = init_browser(headless=True)

    try:
        load_page(page)
        df = run_pipeline(page, output_dir)

        print("\nSample Output:")
        print(df.head())

    finally:
        browser.close()
        p.stop()


if __name__ == "__main__":
    main()