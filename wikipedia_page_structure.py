#!/usr/bin/env python3

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.request import Request
from urllib.request import urlopen
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4 import Tag


DEFAULT_URL = "https://en.wikipedia.org/wiki/Archery_at_the_2024_Summer_Olympics_%E2%80%93_Women%27s_individual"
DEFAULT_OUTPUT_DIR = Path("wikipedia_saved_pages")


@dataclass
class SectionNode:
    title: str
    level: int
    elements: list[str] = field(default_factory=list)
    children: list["SectionNode"] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download a Wikipedia page, save its HTML, and print a section-by-section "
            "DOM outline from the main article body."
        )
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Wikipedia page URL")
    parser.add_argument(
        "--output-html",
        type=Path,
        help="Path to save the downloaded HTML. Defaults to wikipedia_saved_pages/<slug>.html",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--max-text",
        type=int,
        default=90,
        help="Max preview length for element text snippets",
    )
    return parser


def slug_from_url(url: str) -> str:
    slug = urlsplit(url).path.rsplit("/", 1)[-1].strip()
    slug = slug or "wikipedia-page"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug).strip("-")
    return slug.lower() or "wikipedia-page"


def default_output_path(url: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{slug_from_url(url)}.html"


def fetch_html(url: str, timeout: float) -> str:
    request = Request(
        url,
        headers={"User-Agent": "archery-scraper/1.0 (local utility script)"},
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def save_html(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def build_soup(html: str) -> BeautifulSoup:
    for parser in ("lxml", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    raise RuntimeError("Could not initialize an HTML parser for the downloaded page")


def clean_text(value: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def extract_heading_text(tag: Tag) -> str:
    headline = tag.select_one(".mw-headline")
    text = headline.get_text(" ", strip=True) if headline else tag.get_text(" ", strip=True)
    text = re.sub(r"\[\s*edit\s*\]$", "", text, flags=re.IGNORECASE)
    return text.strip() or "Untitled section"


def direct_child_tags(tag: Tag) -> list[Tag]:
    return [child for child in tag.children if isinstance(child, Tag)]


def summarize_children(tags: Iterable[Tag], limit: int = 6) -> str:
    child_names = [child.name for child in tags if child.name]
    if not child_names:
        return ""

    preview = child_names[:limit]
    suffix = ""
    if len(child_names) > limit:
        suffix = f", +{len(child_names) - limit} more"
    return ", ".join(preview) + suffix


def summarize_tag(tag: Tag, max_text: int) -> str:
    parts = [tag.name]

    tag_id = tag.get("id")
    if tag_id:
        parts.append(f"#{tag_id}")

    classes = [class_name for class_name in tag.get("class", []) if class_name]
    if classes:
        parts.append("." + ".".join(classes[:3]))

    details: list[str] = []

    if tag.name in {"p", "li", "blockquote"}:
        preview = clean_text(tag.get_text(" ", strip=True), max_text)
        if preview:
            details.append(f'text="{preview}"')

    if tag.name in {"ul", "ol"}:
        details.append(f"items={len(tag.find_all('li', recursive=False))}")

    if tag.name == "table":
        caption = tag.find("caption")
        if caption:
            details.append(f'caption="{clean_text(caption.get_text(" ", strip=True), max_text)}"')

    if tag.name == "img":
        alt_text = clean_text(tag.get("alt", ""), max_text)
        if alt_text:
            details.append(f'alt="{alt_text}"')

    child_summary = summarize_children(direct_child_tags(tag))
    if child_summary and tag.name not in {"p", "li"}:
        details.append(f"children=[{child_summary}]")

    detail_suffix = f" ({', '.join(details)})" if details else ""
    return "".join(parts) + detail_suffix


def extract_section_heading(tag: Tag) -> Tag | None:
    if tag.name and re.fullmatch(r"h[2-6]", tag.name):
        return tag

    classes = set(tag.get("class", []))
    if "mw-heading" in classes or any(class_name.startswith("mw-heading") for class_name in classes):
        for child in direct_child_tags(tag):
            if child.name and re.fullmatch(r"h[2-6]", child.name):
                return child

    return None


def build_section_tree(content_root: Tag, max_text: int) -> SectionNode:
    root = SectionNode(title="Lead", level=1)
    stack: list[SectionNode] = [root]

    for child in direct_child_tags(content_root):
        heading_tag = extract_section_heading(child)
        if heading_tag is not None:
            section = SectionNode(title=extract_heading_text(heading_tag), level=int(heading_tag.name[1]))
            while stack and stack[-1].level >= section.level:
                stack.pop()
            stack[-1].children.append(section)
            stack.append(section)
            continue

        if child.name in {"script", "style", "meta", "link"}:
            continue

        stack[-1].elements.append(summarize_tag(child, max_text))

    return root


def print_section_tree(section: SectionNode, indent: int = 0) -> None:
    prefix = "  " * indent
    print(f"{prefix}- {section.title}")

    for element in section.elements:
        print(f"{prefix}  * {element}")

    for child in section.children:
        print_section_tree(child, indent + 1)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    output_path = args.output_html or default_output_path(args.url)
    html = fetch_html(args.url, timeout=args.timeout)
    save_html(output_path, html)

    soup = build_soup(html)
    page_title = soup.select_one("#firstHeading")
    content_root = soup.select_one("#mw-content-text .mw-parser-output")

    if content_root is None:
        raise RuntimeError("Could not find Wikipedia article content root: #mw-content-text .mw-parser-output")

    title_text = page_title.get_text(" ", strip=True) if page_title else "Unknown title"
    section_tree = build_section_tree(content_root, max_text=args.max_text)

    print(f"Page title: {title_text}")
    print(f"Saved HTML: {output_path.resolve()}")
    print("DOM outline:")
    print_section_tree(section_tree)


if __name__ == "__main__":
    main()
