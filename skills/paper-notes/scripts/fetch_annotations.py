#!/usr/bin/env python3
"""Fetch PDF annotations + notes for a Zotero paper.

This fills a gap in the companion `zotero` skill, whose `children`/`get`
commands do not parse the Zotero 6+ `annotation` itemType. Annotations live
two levels below the paper: paper -> PDF attachment -> annotations.

Usage:
    python3 fetch_annotations.py <PAPER_KEY>                 # JSON to stdout
    python3 fetch_annotations.py <PAPER_KEY> --output out.json
    python3 fetch_annotations.py --keys K1 K2 K3            # batch: {"papers":[...]}
    python3 fetch_annotations.py <PAPER_KEY> --include-raw   # keep raw annotation data

Output JSON (single paper):
    {
      "zotero_key": "VNPN6FHT",
      "pdf_attachment_key": "WXYZ1234",
      "has_pdf": true,
      "has_annotations": true,
      "annotation_count": 23,
      "annotation_summary": {"highlight": 18, "note": 3, "image": 1, "ink": 1},
      "annotations": [ {type,text,comment,color,color_category,page_label,
                        sort_index,date_added,date_modified}, ... ],
      "notes": [ {key,text,date_added,date_modified}, ... ]
    }

Zero dependencies — stdlib only. Reuses _common for config/HTTP/pagination.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import _common


# Zotero's 6 default annotation colors mapped to categories.
# Display-only; the skill does not impose semantic meaning on colors.
_COLOR_MAP = {
    "#ffd400": "yellow",
    "#ff6666": "red",
    "#5fb236": "green",
    "#2ea8e5": "blue",
    "#a28ae5": "purple",
    "#e56eee": "magenta",
}


def _color_category(hex_color):
    """Map a hex color to a category name, falling back to 'other'.

    Only Zotero's 6 default colors are mapped; any custom color is bucketed as
    'other' (display-only, no semantic meaning imposed).
    """
    if not hex_color:
        return "other"
    return _COLOR_MAP.get(hex_color.lower().strip(), "other")


def _iso_to_date(iso_str):
    """Extract YYYY-MM-DD from a Zotero ISO timestamp (UTC)."""
    if not iso_str:
        return None
    try:
        # Zotero timestamps look like "2026-07-03T14:20:00Z".
        dt = datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_iso_dt(iso_str):
    """Parse a Zotero ISO timestamp into an aware datetime (UTC), or None."""
    if not iso_str:
        return None
    try:
        dt = datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def derive_reading_time(annotations):
    """Estimate reading time from inter-annotation gaps within sessions.

    NOTE: Zotero's Web API does NOT expose true reading duration. This is an
    approximation:
    - Consecutive annotations within 10 min of each other form a reading session.
    - A session's duration is the time span between its first and last annotation.
    - A single isolated annotation (no neighbour within 10 min) counts as 5 min.
    - No per-annotation overhead — time comes from actual inter-annotation gaps.

    Returns {reading_time_minutes: int, reading_by_day: [{date, minutes}]}.
    """
    timed = []
    for ann in annotations:
        dt = _parse_iso_dt(ann.get("date_added"))
        if dt is None:
            continue
        timed.append(dt)
    if not timed:
        return {"reading_time_minutes": 0, "reading_by_day": []}

    timed.sort()

    SESSION_GAP = 10 * 60      # 10 min gap -> new session
    ISOLATED_MINUTES = 5       # minutes for a single isolated annotation

    total_minutes = 0
    by_day = {}

    session_start = timed[0]
    session_last = timed[0]
    session_count = [1]

    def record_duration(start, end, minutes):
        """Add integer session minutes to each UTC day it spans."""
        if start.date() == end.date() or end <= start:
            day = start.strftime("%Y-%m-%d")
            by_day[day] = by_day.get(day, 0) + minutes
            return

        total_seconds = (end - start).total_seconds()
        segments = []
        cursor = start
        while cursor.date() < end.date():
            next_day = (cursor + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            segments.append((cursor.strftime("%Y-%m-%d"),
                             (next_day - cursor).total_seconds()))
            cursor = next_day
        segments.append((end.strftime("%Y-%m-%d"),
                         (end - cursor).total_seconds()))

        allocations = [int(round(minutes * seconds / total_seconds))
                       for _, seconds in segments]
        allocations[-1] += minutes - sum(allocations)
        for (day, _), allocation in zip(segments, allocations):
            by_day[day] = by_day.get(day, 0) + allocation

    def close_session():
        nonlocal total_minutes
        if session_count[0] == 1:
            # Single isolated annotation: fixed 5 min.
            dur = ISOLATED_MINUTES
        else:
            # Multi-annotation session: time span between first and last.
            span_min = (session_last - session_start).total_seconds() / 60.0
            dur = max(1.0, span_min)
        duration_minutes = int(round(dur))
        total_minutes += duration_minutes
        record_duration(session_start, session_last, duration_minutes)

    for dt in timed[1:]:
        gap = (dt - session_last).total_seconds()
        if gap > SESSION_GAP:
            close_session()
            session_start = dt
            session_last = dt
            session_count[0] = 1
        else:
            session_last = dt
            session_count[0] += 1
    close_session()

    reading_by_day = [{"date": d, "minutes": m} for d, m in sorted(by_day.items())]
    return {"reading_time_minutes": total_minutes, "reading_by_day": reading_by_day}


def _parse_annotation(item):
    """Convert a Zotero annotation item dict to a normalized record."""
    d = item.get("data", item)
    atype = d.get("annotationType", "highlight")
    text = d.get("annotationText", "") or ""
    comment = d.get("annotationComment", "") or ""
    # note-type annotations carry their text in annotationComment.
    if atype == "note" and not text and comment:
        text, comment = comment, ""
    color = d.get("annotationColor", "") or ""
    return {
        "key": item.get("key", ""),
        "type": atype,
        "text": text,
        "comment": comment,
        "color": color,
        "color_category": _color_category(color),
        "page_label": d.get("annotationPageLabel", "") or "",
        "sort_index": d.get("annotationSortIndex", "") or "",
        "date_added": d.get("dateAdded", "") or "",
        "date_modified": d.get("dateModified", "") or "",
        "date_added_day": _iso_to_date(d.get("dateAdded")),
    }


def _parse_note(item):
    """Convert a Zotero note item to a normalized record."""
    d = item.get("data", item)
    # Notes carry HTML in 'note'.
    html = d.get("note", "") or ""
    # Strip tags for a plain-text preview (kept short).
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "key": item.get("key", ""),
        "html": html,
        "text": text[:500],
        "date_added": d.get("dateAdded", "") or "",
        "date_modified": d.get("dateModified", "") or "",
        "date_added_day": _iso_to_date(d.get("dateAdded")),
    }


def find_pdf_attachment(paper_key, api_key, prefix):
    """Find the PDF attachment child of a paper. Returns attachment key or None."""
    children = _common.paginate_all(prefix + "/items/" + paper_key + "/children", api_key)
    for child in children:
        d = child.get("data", child)
        if (d.get("itemType") == "attachment"
                and d.get("contentType") == "application/pdf"
                and d.get("linkMode") in ("linked_file", "imported_file",
                                          "imported_url", "linked_url")):
            return child.get("key")
    return None


def fetch_for_paper(paper_key, api_key, prefix, include_raw=False):
    """Fetch annotations + notes for a single paper. Returns the output dict."""
    result = {
        "zotero_key": paper_key,
        "pdf_attachment_key": None,
        "has_pdf": False,
        "has_annotations": False,
        "annotation_count": 0,
        "annotation_summary": {},
        "annotations": [],
        "notes": [],
    }

    pdf_key = find_pdf_attachment(paper_key, api_key, prefix)
    if not pdf_key:
        # No PDF: still try the paper's direct children for standalone notes.
        paper_children = _common.paginate_all(
            prefix + "/items/" + paper_key + "/children", api_key
        )
        for child in paper_children:
            d = child.get("data", child)
            if d.get("itemType") == "note":
                result["notes"].append(_parse_note(child))
        return result

    result["pdf_attachment_key"] = pdf_key
    result["has_pdf"] = True

    # Annotations + notes are children of the PDF attachment.
    ann_children = _common.paginate_all(
        prefix + "/items/" + pdf_key + "/children", api_key
    )

    summary = {}
    for child in ann_children:
        d = child.get("data", child)
        itype = d.get("itemType", "")
        if itype == "annotation":
            rec = _parse_annotation(child)
            if include_raw:
                rec["_raw"] = d
            result["annotations"].append(rec)
            t = rec["type"]
            summary[t] = summary.get(t, 0) + 1
        elif itype == "note":
            result["notes"].append(_parse_note(child))

    # Sort annotations by sort_index (reading order) when present.
    result["annotations"].sort(key=lambda a: a.get("sort_index") or "")
    result["annotation_count"] = len(result["annotations"])
    result["annotation_summary"] = summary
    result["has_annotations"] = result["annotation_count"] > 0

    # Derive estimated reading time from annotation timestamps (session-based).
    rt = derive_reading_time(result["annotations"])
    result["reading_time_minutes"] = rt["reading_time_minutes"]
    result["reading_by_day"] = rt["reading_by_day"]
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Fetch PDF annotations + notes for Zotero papers."
    )
    ap.add_argument("paper_key", nargs="?", help="Zotero item key of the paper")
    ap.add_argument("--keys", nargs="+", help="Multiple paper keys (batch mode)")
    ap.add_argument("--output", "-o", help="Write JSON to this file instead of stdout")
    ap.add_argument(
        "--include-raw", action="store_true",
        help="Keep the raw Zotero annotation data in output",
    )
    args = ap.parse_args()

    keys = []
    if args.keys:
        keys = args.keys
    elif args.paper_key:
        keys = [args.paper_key]
    else:
        ap.error("Provide a paper key or use --keys.")

    api_key, prefix = _common.get_zotero_config()

    if len(keys) == 1:
        out = fetch_for_paper(keys[0], api_key, prefix, args.include_raw)
    else:
        out = {"papers": []}
        for i, k in enumerate(keys):
            if i > 0:
                import time as _t
                _t.sleep(0.5)  # be polite between papers
            try:
                out["papers"].append(
                    fetch_for_paper(k, api_key, prefix, args.include_raw)
                )
            except Exception as e:
                out["papers"].append(
                    {"zotero_key": k, "error": str(e),
                     "has_pdf": False, "has_annotations": False,
                     "annotations": [], "notes": []}
                )

    payload = json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(payload, encoding="utf-8")
        sys.stderr.write("Wrote %s\n" % args.output)
    else:
        sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()
