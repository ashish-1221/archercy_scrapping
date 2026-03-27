#!/usr/bin/env python3

import argparse
import re
import time
from io import StringIO
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ARCHERY_URL = "https://38nguk.in/sports/archery"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "event"


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def wait_for_archery_page(page) -> None:
    page.goto(ARCHERY_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.locator("a, button").filter(has_text=re.compile(r"^\s*fixtures\s*$", re.I)).first.wait_for(
        timeout=30000
    )


def extract_event_label(trigger) -> str:
    label = trigger.evaluate(
        """
        (node) => {
            const card = node.closest('article, section, li, .card, [class*="card"], [class*="event"], [class*="fixture"]') || node.parentElement;
            if (!card) return '';

            const heading = card.querySelector('h1, h2, h3, h4, h5, h6');
            if (heading && heading.textContent) return heading.textContent.trim();

            const textNodes = Array.from(card.querySelectorAll('p, span, div'))
                .map((el) => (el.textContent || '').trim())
                .filter(Boolean)
                .filter((text) => !/^(fixtures|leaderboard|view score|elimination|pool|league)$/i.test(text));

            return textNodes[0] || '';
        }
        """
    )
    return re.sub(r"\s+", " ", label).strip() or "event"


def collect_event_summaries(page) -> list[str]:
    triggers = page.locator("a, button").filter(has_text=re.compile(r"^\s*fixtures\s*$", re.I))
    count = triggers.count()
    labels: list[str] = []

    for index in range(count):
        labels.append(extract_event_label(triggers.nth(index)))

    return labels


def click_fixtures(page, index: int):
    trigger = page.locator("a, button").filter(has_text=re.compile(r"^\s*fixtures\s*$", re.I)).nth(index)
    event_label = extract_event_label(trigger)
    trigger.click()
    page.wait_for_load_state("networkidle")
    return event_label


def open_leaderboard(page) -> None:
    leaderboard = page.locator("a, button").filter(has_text=re.compile(r"^\s*leaderboard\s*$", re.I)).first
    leaderboard.wait_for(timeout=30000)
    leaderboard.click()
    page.wait_for_load_state("networkidle")
    page.locator("table").first.wait_for(timeout=30000)


def save_tables(page, output_dir: Path, event_number: int, event_label: str) -> list[Path]:
    tables = page.locator("table")
    table_count = tables.count()
    saved_paths: list[Path] = []

    if table_count == 0:
        return saved_paths

    for index in range(table_count):
        html = tables.nth(index).evaluate("(table) => table.outerHTML")
        frames = pd.read_html(StringIO(html))

        if not frames:
            continue

        filename = f"{event_number:02d}-{slugify(event_label)}"
        if table_count > 1:
            filename += f"-table-{index + 1}"

        output_path = output_dir / f"{filename}.csv"
        frames[0].to_csv(output_path, index=False)
        saved_paths.append(output_path)

    return saved_paths


def scrape_leaderboards(output_dir: Path, headless: bool, slow_mo: int) -> list[Path]:
    saved_paths: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
        page = browser.new_page()

        try:
            wait_for_archery_page(page)
            event_labels = collect_event_summaries(page)

            if not event_labels:
                raise RuntimeError("No Fixtures buttons were found on the archery page.")

            for index, event_name in enumerate(event_labels):
                wait_for_archery_page(page)
                current_name = click_fixtures(page, index)
                if current_name:
                    event_name = current_name

                try:
                    open_leaderboard(page)
                    event_paths = save_tables(page, output_dir, index + 1, event_name)
                    if not event_paths:
                        print(f"Skipping {event_name}: no leaderboard table found")
                        continue
                    saved_paths.extend(event_paths)
                except PlaywrightTimeoutError:
                    print(f"Skipping {event_name}: leaderboard UI did not load in time")
                    continue
                time.sleep(0.5)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "Timed out while waiting for the Fixtures or Leaderboard UI. "
                "The page structure may have changed."
            ) from error
        finally:
            browser.close()

    return saved_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape all leaderboard tables from the 38th National Games archery page."
    )
    parser.add_argument(
        "--output-dir",
        default="archery_leaderboards",
        help="Directory where leaderboard CSV files will be written.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium with a visible window instead of headless mode.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=250,
        help="Delay in milliseconds between browser actions.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    output_dir = ensure_output_dir(Path(args.output_dir))
    saved_paths = scrape_leaderboards(
        output_dir=output_dir,
        headless=not args.headed,
        slow_mo=args.slow_mo,
    )

    print(f"Saved {len(saved_paths)} file(s) to {output_dir}")
    for path in saved_paths:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
