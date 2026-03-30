#!/usr/bin/env python3

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Archery_at_the_2024_Summer_Olympics_%E2%80%93_Women%27s_team"
OUTPUT_COLUMNS = [
    "championship",
    "round_name",
    "country",
    "player_A",
    "player_B",
    "winner",
    "score_A",
    "score_B",
]
INDIVIDUAL_SECTION_ROUNDS = [
    ("Round of 64", 8),
    ("Round of 32", 4),
    ("Round of 16", 2),
    ("Quarter-finals", 1),
]
INDIVIDUAL_FINALS_ROUNDS = [
    ("Semi-finals", 2),
    ("Bronze medal match", 1),
    ("Gold medal match", 1),
]
TEAM_ROUNDS = [
    ("Round of 16", 4),
    ("Quarter-finals", 4),
    ("Semi-finals", 2),
    ("Bronze medal match", 1),
    ("Gold medal match", 1),
]
MIXED_TEAM_ROUNDS = [
    ("Round of 16", 8),
    ("Quarter-finals", 4),
    ("Semi-finals", 2),
    ("Bronze medal match", 1),
    ("Gold medal match", 1),
]


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "archery"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_line(value: str) -> str:
    cleaned = value.replace("\xa0", " ")
    cleaned = re.sub(r"\[[^\]]+\]", "", cleaned)
    return normalize_space(cleaned)


def wait_for_page(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.locator("#firstHeading").wait_for(timeout=30000)


def collect_event_links(page) -> list[dict[str, str]]:
    links = page.evaluate(
        """
        (baseUrl) => {
            const normalize = (value) => value.replace(/\\s+/g, ' ').trim();
            const collected = [];
            const seen = new Set();
            const eventPatterns = [
                /men's individual/i,
                /women's individual/i,
                /men's team/i,
                /women's team/i,
                /mixed team/i,
            ];

            const isEventLink = (anchor) => {
                const href = anchor.getAttribute('href') || '';
                const text = normalize(anchor.textContent || '');
                const absolute = new URL(href, baseUrl).href;

                if (!text) {
                    return null;
                }
                if (!absolute.includes('/wiki/Archery_at_the_2024_Summer_Olympics')) {
                    return null;
                }
                if (absolute === baseUrl || absolute.includes('#')) {
                    return null;
                }
                if (/qualification/i.test(text) || /qualification/i.test(absolute)) {
                    return null;
                }
                if (!eventPatterns.some((pattern) => pattern.test(text) || pattern.test(absolute))) {
                    return null;
                }
                if (seen.has(absolute)) {
                    return null;
                }

                seen.add(absolute);
                return { label: text, url: absolute };
            };

            const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'));
            const heading = headings.find((node) => normalize(node.textContent).toLowerCase().includes('competition schedule'));

            if (heading) {
                let cursor = heading.nextElementSibling;

                while (cursor && !/^H[1-6]$/.test(cursor.tagName)) {
                    for (const anchor of cursor.querySelectorAll('a[href]')) {
                        const eventLink = isEventLink(anchor);
                        if (eventLink) {
                            collected.push(eventLink);
                        }
                    }
                    cursor = cursor.nextElementSibling;
                }
            }

            if (collected.length === 0) {
                for (const anchor of document.querySelectorAll('a[href]')) {
                    const eventLink = isEventLink(anchor);
                    if (eventLink) {
                        collected.push(eventLink);
                    }
                }
            }

            const order = [
                "men's individual",
                "women's individual",
                "men's team",
                "women's team",
                "mixed team",
            ];

            collected.sort((a, b) => {
                const aText = normalize(a.label).toLowerCase();
                const bText = normalize(b.label).toLowerCase();
                const aIndex = order.findIndex((value) => aText.includes(value));
                const bIndex = order.findIndex((value) => bText.includes(value));

                if (aIndex !== bIndex) {
                    return (aIndex === -1 ? 999 : aIndex) - (bIndex === -1 ? 999 : bIndex);
                }
                return aText.localeCompare(bText);
            });

            return collected;
        }
        """,
        WIKIPEDIA_URL,
    )
    return [link for link in links if isinstance(link, dict) and link.get("url")]


def get_page_title(page) -> str:
    return clean_line(page.locator("#firstHeading").inner_text())


def extract_section_text(page, heading_text: str) -> str:
    text = page.evaluate(
        """
        (targetHeading) => {
            const normalize = (value) => value.replace(/\\s+/g, ' ').trim().toLowerCase();
            const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'));
            const heading = headings.find((node) => normalize(node.textContent) === normalize(targetHeading));

            if (!heading) {
                return '';
            }

            const level = Number(heading.tagName.slice(1));
            const parts = [];
            let cursor = heading.nextElementSibling;

            while (cursor) {
                if (/^H[1-6]$/.test(cursor.tagName)) {
                    const nextLevel = Number(cursor.tagName.slice(1));
                    if (nextLevel <= level) {
                        break;
                    }
                }

                if (cursor.innerText) {
                    parts.push(cursor.innerText);
                }
                cursor = cursor.nextElementSibling;
            }

            return parts.join('\\n');
        }
        """,
        heading_text,
    )
    return text or ""


def preprocess_section_lines(text: str) -> list[str]:
    lines: list[str] = []

    for raw_line in text.splitlines():
        split_lines = re.split(r"\s{2,}(?=\d+\s)", raw_line)
        for part in split_lines:
            cleaned = clean_line(part)
            if not cleaned:
                continue
            if cleaned.lower() in {
                "round of 64",
                "round of 32",
                "round of 16",
                "quarter-finals",
                "quarterfinals",
                "semi-finals",
                "semifinals",
                "bronze medal match",
                "gold medal match",
                "competition bracket",
                "finals",
                "section 1",
                "section 2",
                "section 3",
                "section 4",
            }:
                continue
            if cleaned.startswith("The figure in italics"):
                continue
            lines.append(cleaned)

    return lines


def parse_individual_entry(line: str) -> dict[str, Any] | None:
    match = re.match(r"^(\d+)\s+(.+?)\s+\(([A-Z]{3})\)\s+(.+)$", line)
    if not match:
        return None

    rest_tokens = match.group(4).split()
    if not rest_tokens:
        return None

    return {
        "seed": int(match.group(1)),
        "name": clean_line(match.group(2)),
        "country": match.group(3),
        "score": rest_tokens[0],
        "tail": rest_tokens[1:],
    }


def parse_team_entry(line: str) -> dict[str, Any] | None:
    match = re.match(r"^(\d+)\s+(.+?)\s+([0-9]+(?:[+*])?)\s+(.+)$", line)
    if not match:
        return None

    return {
        "seed": int(match.group(1)),
        "name": clean_line(match.group(2)),
        "country": clean_line(match.group(2)),
        "score": match.group(3),
        "tail": match.group(4).split(),
    }


def parse_score_value(score: str) -> int:
    match = re.search(r"\d+", score)
    return int(match.group()) if match else -1


def parse_tiebreak_value(entry: dict[str, Any]) -> tuple[int, int]:
    score = entry["score"]
    if "+" in score:
        return (parse_score_value(score), 1)
    if "*" in score:
        return (parse_score_value(score), 1)

    for token in entry.get("tail", []):
        if "+" in token or "*" in token:
            return (parse_score_value(token), 1)

    return (-1, 0)


def select_winner(entry_a: dict[str, Any], entry_b: dict[str, Any]) -> dict[str, Any]:
    score_a = parse_score_value(entry_a["score"])
    score_b = parse_score_value(entry_b["score"])
    if score_a > score_b:
        return entry_a
    if score_b > score_a:
        return entry_b

    tie_a = parse_tiebreak_value(entry_a)
    tie_b = parse_tiebreak_value(entry_b)
    if tie_a > tie_b:
        return entry_a
    if tie_b > tie_a:
        return entry_b

    return entry_a


def build_match_record(
    championship: str,
    round_name: str,
    entry_a: dict[str, Any],
    entry_b: dict[str, Any],
) -> dict[str, str]:
    winner = select_winner(entry_a, entry_b)
    return {
        "championship": championship,
        "round_name": round_name,
        "country": winner["country"],
        "player_A": entry_a["name"],
        "player_B": entry_b["name"],
        "winner": winner["name"],
        "score_A": entry_a["score"],
        "score_B": entry_b["score"],
    }


def build_round_matches(
    championship: str,
    entries: list[dict[str, Any]],
    round_plan: list[tuple[str, int]],
) -> list[dict[str, str]]:
    expected_entries = sum(match_count * 2 for _, match_count in round_plan)
    if len(entries) < expected_entries:
        raise RuntimeError(
            f"{championship}: expected at least {expected_entries} bracket entries, found {len(entries)}."
        )

    results: list[dict[str, str]] = []
    cursor = 0
    for round_name, match_count in round_plan:
        for _ in range(match_count):
            entry_a = entries[cursor]
            entry_b = entries[cursor + 1]
            results.append(build_match_record(championship, round_name, entry_a, entry_b))
            cursor += 2
    return results


def parse_individual_event(page, championship: str) -> list[dict[str, str]]:
    all_matches: list[dict[str, str]] = []

    for heading in ("Section 1", "Section 2", "Section 3", "Section 4"):
        section_text = extract_section_text(page, heading)
        if not section_text:
            raise RuntimeError(f"{championship}: missing {heading} section.")
        entries = [entry for line in preprocess_section_lines(section_text) if (entry := parse_individual_entry(line))]
        all_matches.extend(build_round_matches(championship, entries, INDIVIDUAL_SECTION_ROUNDS))

    finals_text = extract_section_text(page, "Finals")
    if not finals_text:
        raise RuntimeError(f"{championship}: missing Finals section.")
    finals_entries = [
        entry for line in preprocess_section_lines(finals_text) if (entry := parse_individual_entry(line))
    ]
    all_matches.extend(build_round_matches(championship, finals_entries, INDIVIDUAL_FINALS_ROUNDS))
    return all_matches


def parse_team_event(page, championship: str, round_plan: list[tuple[str, int]]) -> list[dict[str, str]]:
    bracket_text = extract_section_text(page, "Competition bracket")
    if not bracket_text:
        raise RuntimeError(f"{championship}: missing Competition bracket section.")

    entries = [entry for line in preprocess_section_lines(bracket_text) if (entry := parse_team_entry(line))]
    return build_round_matches(championship, entries, round_plan)


def parse_event(page, event_url: str) -> list[dict[str, str]]:
    wait_for_page(page, event_url)
    championship = get_page_title(page)
    lowered = championship.lower()

    if "mixed team" in lowered:
        return parse_team_event(page, championship, MIXED_TEAM_ROUNDS)
    if "team" in lowered:
        return parse_team_event(page, championship, TEAM_ROUNDS)
    return parse_individual_event(page, championship)


def save_json(records: list[dict[str, str]], path: Path) -> None:
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_csv(records: list[dict[str, str]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def print_sample_records(records: list[dict[str, str]], sample_size: int) -> None:
    print(f"Sample output ({min(sample_size, len(records))} row(s)):")
    for record in records[:sample_size]:
        print(json.dumps(record, ensure_ascii=False))


def scrape_olympic_archery_brackets(headless: bool, slow_mo: int) -> list[dict[str, str]]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
        page = browser.new_page()

        try:
            wait_for_page(page, WIKIPEDIA_URL)
            event_links = collect_event_links(page)
            if not event_links:
                raise RuntimeError("No event links were found in the Competition schedule section.")

            records: list[dict[str, str]] = []
            for event in event_links:
                absolute_url = urljoin(WIKIPEDIA_URL, event["url"])
                records.extend(parse_event(page, absolute_url))

            return records
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Timed out while loading Wikipedia pages. The page structure may have changed."
            ) from error
        finally:
            browser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape match results from the competition brackets on Wikipedia's 2024 Olympic archery pages."
    )
    parser.add_argument(
        "--output-dir",
        default="wikipedia_archery_2024",
        help="Directory where the bracket JSON and CSV files will be written.",
    )
    parser.add_argument(
        "--output-name",
        default="archery_2024_olympics_brackets",
        help="Base filename to use for the generated JSON and CSV files.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium with a visible window instead of headless mode.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=150,
        help="Delay in milliseconds between browser actions.",
    )
    parser.add_argument(
        "--sample-output",
        action="store_true",
        help="Print a small sample of scraped rows to stdout after saving the files.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Number of sample rows to print when --sample-output is used.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    output_dir = ensure_output_dir(Path(args.output_dir))
    records = scrape_olympic_archery_brackets(
        headless=not args.headed,
        slow_mo=args.slow_mo,
    )

    base_name = slugify(args.output_name)
    json_path = output_dir / f"{base_name}.json"
    csv_path = output_dir / f"{base_name}.csv"

    save_json(records, json_path)
    save_csv(records, csv_path)

    print(f"Saved {len(records)} bracket row(s)")
    print(json_path)
    print(csv_path)
    if args.sample_output:
        print_sample_records(records, max(args.sample_size, 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
