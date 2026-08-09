#!/usr/bin/env python3
"""Bundled read-only Zotero CLI used by paper-notes.

This intentionally supports only the two operations required by the reading
workflow: searching for library items and fetching one item's metadata. All
requests use GET through the shared stdlib-only Zotero Web API client.
"""

import argparse
import json
import re
import sys

import _common


COMMANDS = ("search", "get")


def _item_data(item):
    return item.get("data", item) if isinstance(item, dict) else {}


def _format_creators(creators):
    names = []
    for creator in creators[:3]:
        names.append(creator.get("lastName") or creator.get("name") or "?")
    if len(creators) > 3:
        names.append("et al.")
    return ", ".join(names)


def _format_item(item):
    year_match = re.match(r"(\d{4})", str(item.get("date", "")))
    year = year_match.group(1) if year_match else ""
    return "[%s] %s (%s) %s [%s]" % (
        item.get("key", "?"),
        _format_creators(item.get("creators", [])),
        year,
        item.get("title", "untitled"),
        item.get("itemType", "?"),
    )


def cmd_search(args):
    api_key, prefix = _common.get_zotero_config()
    params = {"q": args.query, "limit": str(args.limit)}
    if args.sort != "relevance":
        params["sort"] = args.sort
    if args.type:
        params["itemType"] = args.type
    raw_items, headers = _common.api_get_json(prefix + "/items", api_key, params)
    items = [
        _item_data(item) for item in (raw_items or [])
        if _item_data(item).get("itemType") != "attachment"
    ]
    total = headers.get("Total-Results", len(items))
    if args.json:
        print(json.dumps({"total": total, "items": items}, ensure_ascii=False, indent=2))
        return
    print("Found %d results (of %s total matches)\n" % (len(items), total))
    for item in items:
        print(_format_item(item))


def cmd_get(args):
    _common.validate_paper_key(args.key)
    api_key, prefix = _common.get_zotero_config()
    raw_item, _ = _common.api_get_json(prefix + "/items/" + args.key, api_key)
    item = _item_data(raw_item)
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
        return
    print(_format_item(item))
    if item.get("DOI"):
        print("DOI: " + item["DOI"])
    if item.get("url"):
        print("URL: " + item["url"])


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read-only Zotero CLI bundled with paper-notes"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search library items")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=25)
    search.add_argument("--sort", default="relevance")
    search.add_argument("--type")
    search.set_defaults(handler=cmd_search)

    get = subparsers.add_parser("get", help="Get one item's metadata")
    get.add_argument("key")
    get.set_defaults(handler=cmd_get)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
        else:
            print("Zotero request failed: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
