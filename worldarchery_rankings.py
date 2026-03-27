#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


API_ROOT_V3 = "http://api.worldarchery.org/v3"
LEGACY_BASE_URL = "http://api.worldarchery.org/"
MAX_ITEMS_PER_PAGE = 100
ENDPOINT_CHOICES = {
    "world-rankings": "WORLDRANKINGS",
    "individual-qualifications": "INDIVIDUALQUALIFICATIONS",
    "individual-matches": "INDIVIDUALMATCHES",
    "team-matches": "TEAMMATCHES",
}
SAVE_FORMAT_CHOICES = ("json", "csv")


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def log_status(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[status] {message}", file=sys.stderr)


def build_base_url(endpoint: str, use_legacy_endpoint: bool) -> str:
    if use_legacy_endpoint:
        return LEGACY_BASE_URL
    return f"{API_ROOT_V3}/{ENDPOINT_CHOICES[endpoint]}/"


def build_params(args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {}

    field_map = {
        "comp_id": "CompId",
        "cat_id": "CatId",
        "cat_code": "CatCode",
        "date": "Date",
        "item_id": "Id",
        "noc": "Noc",
        "phase_id": "PhaseId",
        "number": "Number",
        "live": "Live",
        "empty_matches": "EmptyMatches",
        "data_type": "Type",
        "team": "Team",
        "detailed": "Detailed",
        "rank": "Rank",
        "rank_max": "RankMax",
        "f_text": "fText",
        "sort_by": "SortBy",
        "rbp": "RBP",
        "page": "Page",
    }

    for arg_name, api_name in field_map.items():
        value = getattr(args, arg_name)
        if value is not None:
            params[api_name] = value

    if args.use_legacy_endpoint:
        params["v"] = 3
        params["content"] = ENDPOINT_CHOICES[args.endpoint]

    return params


def build_url(base_url: str, params: dict[str, Any]) -> str:
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url


def fetch_json(url: str, timeout: int, verbose: bool = False) -> Any:
    log_status(verbose, f"Fetching URL: {url}")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "worldarchery-rankings-script/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        payload = json.loads(response.read().decode(charset))
        log_status(verbose, "Received API response")
        return payload


def flatten_records(records: list[Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []

    for record in records:
        if isinstance(record, dict) and any(isinstance(value, list) for value in record.values()):
            scalar_fields = {
                key: value for key, value in record.items() if not isinstance(value, list)
            }
            expanded = False
            for key, value in record.items():
                if not isinstance(value, list):
                    continue
                if not value:
                    flattened.append({**scalar_fields, key: None})
                    expanded = True
                    continue
                if all(isinstance(item, dict) for item in value):
                    for item in value:
                        flattened.append({**scalar_fields, **item, "_group": key})
                else:
                    for item in value:
                        flattened.append({**scalar_fields, key: item})
                expanded = True
            if expanded:
                continue

        if isinstance(record, dict):
            flattened.append(record)
        else:
            flattened.append({"value": record})

    return flattened


def fetch_pages(
    base_url: str,
    params: dict[str, Any],
    timeout: int,
    all_pages: bool,
    verbose: bool = False,
) -> list[Any]:
    if not all_pages:
        return [fetch_json(build_url(base_url, params), timeout, verbose)]

    page = int(params.get("Page", 1))
    responses: list[Any] = []

    while True:
        current_params = dict(params)
        current_params["Page"] = page
        log_status(verbose, f"Fetching page {page}")
        payload = fetch_json(build_url(base_url, current_params), timeout, verbose)
        responses.append(payload)
        record_count = len(extract_records(payload))
        log_status(verbose, f"Page {page} returned {record_count} record(s)")

        if not payload:
            log_status(verbose, "Stopping pagination because payload was empty")
            break
        if record_count == 0:
            log_status(verbose, "Stopping pagination because the page returned no records")
            break
        if isinstance(payload, list) and len(payload) == 0:
            log_status(verbose, "Stopping pagination because payload list was empty")
            break

        page += 1

    return responses


def extract_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return [payload]

    preferred_keys = ("Items", "items", "Results", "results", "Data", "data")
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value

    list_values = [value for value in payload.values() if isinstance(value, list)]
    if len(list_values) == 1:
        return list_values[0]

    return [payload]


def collect_records(data: Any) -> list[Any]:
    if isinstance(data, list):
        records: list[Any] = []
        for item in data:
            records.extend(extract_records(item))
        return records

    return extract_records(data)


def normalize_to_dataframe(data: Any, verbose: bool = False) -> "pd.DataFrame":
    if pd is None:
        raise RuntimeError(
            "pandas is required for DataFrame normalization. Install it with: pip install pandas"
        )

    records = flatten_records(collect_records(data))
    if not records:
        log_status(verbose, "No records found to normalize")
        return pd.DataFrame()
    dataframe = pd.json_normalize(records, sep=".")
    log_status(verbose, f"Normalized {len(dataframe)} row(s) into a DataFrame")
    return dataframe


def save_csv_output(data: Any, output_path: str, verbose: bool = False) -> None:
    dataframe = normalize_to_dataframe(data, verbose)
    path = Path(output_path)
    log_status(verbose, f"Writing CSV file: {path}")
    dataframe.to_csv(path, index=False)
    print(f"Saved normalized CSV to {path}")


def save_output(data: Any, output_path: Optional[str], verbose: bool = False) -> None:
    serialized = json.dumps(data, indent=2, ensure_ascii=False)
    if output_path:
        path = Path(output_path)
        log_status(verbose, f"Writing JSON file: {path}")
        path.write_text(serialized + "\n", encoding="utf-8")
        print(f"Saved response to {path}")
        return

    print(serialized)


def resolve_save_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []

    if args.save_format or args.save_path:
        if not args.save_format or not args.save_path:
            raise ValueError("Both --save-format and --save-path are required together.")
        targets.append((args.save_format, args.save_path))

    if args.output:
        targets.append(("json", args.output))
    if args.csv_output:
        targets.append(("csv", args.csv_output))

    return targets


def should_fetch_all_pages(args: argparse.Namespace) -> bool:
    if args.all_pages:
        return True
    if args.endpoint == "individual-matches" and args.page is None:
        return True
    return False


def apply_endpoint_defaults(args: argparse.Namespace, params: dict[str, Any]) -> None:
    if args.endpoint == "individual-matches" and args.rbp is None:
        params["RBP"] = MAX_ITEMS_PER_PAGE


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch World Archery data from the public API and export normalized JSON/CSV."
    )
    parser.add_argument(
        "--endpoint",
        choices=sorted(ENDPOINT_CHOICES),
        default="team-matches",
        help="API endpoint to query",
    )
    parser.add_argument("--comp-id", type=int, help="Competition ID")
    parser.add_argument("--cat-id", help="Category ID or multiple IDs separated by |")
    parser.add_argument("--cat-code", help="Category code")
    parser.add_argument("--date", help="Date in API-supported format, for example 2024-01-01")
    parser.add_argument("--item-id", help="Athlete WA ID")
    parser.add_argument("--noc", help="NOC code, for example IND or USA")
    parser.add_argument("--phase-id", type=int, help="Phase ID")
    parser.add_argument("--number", help="Match number or multiple numbers separated by |")
    parser.add_argument("--live", type=parse_bool, help="true or false")
    parser.add_argument("--empty-matches", type=parse_bool, help="true or false")
    parser.add_argument("--data-type", help="Data type")
    parser.add_argument("--team", type=parse_bool, help="true or false")
    parser.add_argument("--detailed", type=parse_bool, help="true or false")
    parser.add_argument("--rank", type=int, help="Exact rank")
    parser.add_argument("--rank-max", type=int, help="Maximum rank to return")
    parser.add_argument("--f-text", help="Free-text search")
    parser.add_argument("--sort-by", help="API sort field")
    parser.add_argument("--rbp", type=int, help="Records per page")
    parser.add_argument("--page", type=int, help="Page number")
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="Fetch pages until the API returns an empty response",
    )
    parser.add_argument(
        "--use-legacy-endpoint",
        action="store_true",
        help="Use http://api.worldarchery.org/?v=3&content=INDIVIDUALQUALIFICATIONS...",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument(
        "--save-format",
        choices=SAVE_FORMAT_CHOICES,
        help="Save response as json or csv",
    )
    parser.add_argument(
        "--save-path",
        help="Destination file path used with --save-format",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print step-by-step status messages to stderr while the script runs",
    )
    parser.add_argument("--output", help="Write JSON output to a file")
    parser.add_argument(
        "--csv-output",
        help="Write normalized tabular output to a CSV file",
    )
    parser.add_argument(
        "--dataframe-head",
        type=int,
        metavar="N",
        help="Print the first N rows of the normalized pandas DataFrame",
    )
    args = parser.parse_args()
    if args.cat_id and args.cat_code:
        parser.error("Use either --cat-id or --cat-code, not both.")

    base_url = build_base_url(args.endpoint, args.use_legacy_endpoint)
    params = build_params(args)
    apply_endpoint_defaults(args, params)
    fetch_all_pages = should_fetch_all_pages(args)

    try:
        save_targets = resolve_save_targets(args)
        log_status(
            args.verbose,
            f"Starting request for endpoint '{args.endpoint}' using "
            f"{'legacy' if args.use_legacy_endpoint else 'v3'} API",
        )
        if params.get("RBP") == MAX_ITEMS_PER_PAGE:
            log_status(args.verbose, f"Using max records per page setting: {MAX_ITEMS_PER_PAGE}")
        if fetch_all_pages:
            log_status(args.verbose, "Auto-pagination enabled; will stop when a page returns no records")
        data = fetch_pages(base_url, params, args.timeout, fetch_all_pages, args.verbose)
        if not fetch_all_pages:
            data = data[0]
        log_status(args.verbose, f"Collected {len(collect_records(data))} record(s) from the API")

        for save_format, save_path in save_targets:
            if save_format == "json":
                save_output(data, save_path, args.verbose)
            else:
                save_csv_output(data, save_path, args.verbose)

        if args.dataframe_head is not None:
            dataframe = normalize_to_dataframe(data, args.verbose)
            print(dataframe.head(args.dataframe_head).to_string(index=False))
        if not save_targets and args.dataframe_head is None:
            save_output(data, None, args.verbose)
        log_status(args.verbose, "Completed successfully")
        return 0
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
