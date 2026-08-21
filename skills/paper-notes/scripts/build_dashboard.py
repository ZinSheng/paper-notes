#!/usr/bin/env python3
"""Aggregate the reading manifest into a dashboard HTML.

Reads reading-list.json, computes collection groups, the weekly reading
calendar buckets, and summary stats, then injects them into
assets/dashboard_template.html via __PLACEHOLDER__ replacement.

Usage:
    python3 build_dashboard.py
    python3 build_dashboard.py --include-archived
    python3 build_dashboard.py --stdout

Zero dependencies — stdlib only.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import _common

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE.parent / "assets" / "dashboard_template.html"
RESEARCH_TEMPLATE_PATH = HERE.parent / "assets" / "research_template.html"

DASHBOARD_PLACEHOLDER_REGISTRY = [
    "__PAPERS_JSON__", "__GROUPS_JSON__",
    "__RESEARCH_JSON__",
    "__CALENDAR_JSON__", "__STATS_JSON__", "__TOTAL_PAPERS__",
    "__FIRST_PAPER_PATH__", "__GENERATED_AT__",
    # First-call config (injected from litreader.config.json)
    "__DEFAULT_ACCENT__", "__ZOTERO_MODE__",
]


def _format_authors_short(creators):
    """First author, with ``et al.`` when applicable, for the dashboard."""
    names = []
    for c in creators or []:
        if c.get("creatorType") and c["creatorType"] not in ("author", None):
            continue
        last = (c.get("lastName") or "").strip()
        first = (c.get("firstName") or "").strip()
        if last and first:
            names.append("%s, %s." % (last, first[0]))
        elif last:
            names.append(last)
        elif c.get("name"):
            # Manual imports may store every author in one comma-separated
            # `name` string instead of Zotero-style creator records.
            raw_name = str(c["name"]).strip()
            split_names = [part.strip() for part in raw_name.split(",") if part.strip()]
            if len(creators or []) == 1 and len(split_names) >= 3:
                names.extend(split_names)
            elif raw_name:
                names.append(raw_name)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return names[0] if len(names) == 1 else names[0] + " et al."


def _safe_filename(value, fallback):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "－", str(value or "")).strip().rstrip(". ")
    return name or fallback


def _research_html_paths(projects):
    used, result = set(), {}
    for project in projects:
        stem = _safe_filename(project.get("name"), project.get("id", "research"))
        filename = stem + ".html"
        if filename.casefold() in used:
            filename = stem + " — " + project["id"] + ".html"
        used.add(filename.casefold())
        result[project["id"]] = "research/" + filename
    return result


def _render_research_page(project, cfg):
    template = RESEARCH_TEMPLATE_PATH.read_text(encoding="utf-8")
    def text(value):
        escaped = _common.html_escape(str(value or ""))
        return escaped.replace("\n", "<br>") if escaped else '<span class="empty">—</span>'
    keywords = "".join('<span class="keyword">%s</span>' % _common.html_escape(str(x))
                       for x in (project.get("keywords") or []))
    replacements = {
        "__TITLE__": _common.html_escape(project.get("name", project.get("id", "Research"))),
        "__STATUS__": _common.html_escape(project.get("status", "active")),
        "__RESEARCH_QUESTION__": text(project.get("research_question")),
        "__BACKGROUND__": text(project.get("background")),
        "__METHOD__": text(project.get("method_or_design")),
        "__DATA__": text(project.get("data_or_materials")),
        "__CHALLENGES__": text(project.get("current_challenges")),
        "__KEYWORDS__": keywords or '<span class="empty">—</span>',
        "__DEFAULT_ACCENT__": cfg.get("default_accent", "blue"),
    }
    return _common.apply_placeholders(template, replacements, list(replacements))


def _write_research_pages(projects, cfg):
    paths = _research_html_paths(projects)
    out_dir = _common.HTML_RESEARCH_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    desired = set()
    for project in projects:
        target = _common.HTML_DIR / paths[project["id"]]
        # Case-insensitive filesystems keep the old spelling when only the
        # filename's case changes, which can leave dashboard links broken when
        # the output is later served from a case-sensitive filesystem.
        for existing in out_dir.glob("*.html"):
            if existing.name.casefold() == target.name.casefold() and existing.name != target.name:
                temporary = out_dir / (project["id"] + ".rename-tmp")
                existing.replace(temporary)
                temporary.replace(target)
                break
        target.write_text(_render_research_page(project, cfg), encoding="utf-8")
        desired.add(target.resolve())
    for stale in out_dir.glob("*.html"):
        if stale.resolve() not in desired:
            stale.unlink()


def _week_monday(date_str):
    """Return the Monday (YYYY-MM-DD) of the ISO week containing date_str."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return d - timedelta(days=d.weekday())  # Monday=0


def _iso_week_label(monday):
    """Return an ISO week label like '2026-W26' for a Monday date."""
    iso = monday.isocalendar()
    return "%d-W%02d" % (iso[0], iso[1])


def _merge_edits_status(papers):
    """Apply each paper's <KEY>.edits.json status back to the manifest in memory.

    Browser status changes (via the File System Access API) are written to
    papers/<KEY>.edits.json. This folds them into the manifest snapshot so the
    dashboard reflects browser-side status edits without a separate sync step.
    """
    for p in papers:
        ep = _common.PAPERS_DIR / (p["zotero_key"] + ".edits.json")
        if not ep.exists():
            continue
        try:
            edits = json.loads(ep.read_text(encoding="utf-8"))
            if edits.get("status") in ("reading", "done", "archived"):
                p["status"] = edits["status"]
        except (json.JSONDecodeError, OSError):
            pass


def _build_collection_hierarchy(papers_flat):
    """Build a nested collection tree from the paper list.

    Returns (roots, path_map) where:
      - roots: list of top-level nodes (incl. a synthetic "Unfiled" node when
        any paper has no collection). Each node:
          {key, name, parent, depth, count, path, papers[], children[],
           is_unfiled?}
        `papers` are papers directly belonging to that node (leaf membership);
        `count` is the subtree total; `path` is the name breadcrumb list.
      - path_map: {collection_key: "Parent / Child" breadcrumb string}

    The full hierarchy (including intermediate collections that hold no papers
    directly) is taken from the live Zotero tree when reachable, with per-paper
    stored {key,name,parent} as an offline fallback.
    """
    # 1. Live tree (correct names + parents); fall back to empty on failure.
    if _common.load_config().get("connect_zotero"):
        try:
            tree = _common.fetch_collection_tree()
            if tree is None:
                tree = _common.load_collection_tree_cache() or []
        except Exception:
            tree = []
    else:
        tree = []
    node_map = {c["key"]: {"name": c["name"], "parent": c.get("parent")}
                for c in tree if c.get("key")}

    # 2. Union with per-paper stored collections (offline / missing nodes).
    for p in papers_flat:
        for c in p.get("collections", []):
            if isinstance(c, dict) and c.get("key") and c["key"] not in node_map:
                node_map[c["key"]] = {"name": c.get("name", c["key"]),
                                      "parent": c.get("parent")}

    # 3. Node objects.
    nodes = {}

    def get_node(key):
        if key not in nodes:
            nm = node_map.get(key, {})
            nodes[key] = {
                "key": key, "name": nm.get("name", key),
                "parent": nm.get("parent"),
                "children": [], "papers": [], "count": 0,
                "depth": 0, "path": [],
            }
        return nodes[key]

    for key in node_map:
        get_node(key)

    # 4. Assign papers to their direct collections.
    for p in papers_flat:
        for c in p.get("collections", []):
            key = c.get("key") if isinstance(c, dict) else c
            if key:
                get_node(key)["papers"].append(p)

    # 5. Link children; collect roots.
    roots = []
    for key, node in nodes.items():
        par = node["parent"]
        if par and par in nodes:
            if node not in nodes[par]["children"]:
                nodes[par]["children"].append(node)
        elif node not in roots:
            roots.append(node)

    # 6. Synthetic "Unfiled" group.
    unfiled = [p for p in papers_flat if not p.get("collections")]
    if unfiled:
        roots.insert(0, {
            "key": "__unfiled__", "name": "未分类 Unfiled", "parent": None,
            "children": [], "papers": unfiled, "count": 0, "depth": 0,
            "path": ["未分类 Unfiled"], "is_unfiled": True,
        })

    # 7. Compute depth / path / count, sort deterministically.
    def walk(node, depth, path):
        node["depth"] = depth
        node["path"] = path + [node["name"]]
        node["papers"].sort(
            key=lambda x: ((x.get("year") or ""), (x.get("title") or "")).__str__().lower())
        for ch in node["children"]:
            walk(ch, depth + 1, node["path"])
        node["count"] = len(node["papers"]) + sum(c["count"] for c in node["children"])
        node["children"].sort(key=lambda c: (c["name"] or "").lower())

    for r in roots:
        walk(r, 0, [])

    # 7b. Prune branches that contain no papers at all (neither directly nor in
    # any descendant). This keeps the dashboard focused on the collections the
    # reading list actually uses while still showing the full ancestor chain
    # (a parent with 0 direct papers but a populated child stays visible).
    def prune(node):
        node["children"] = [prune(c) for c in node["children"] if c["count"] > 0]
        return node
    roots = [prune(r) for r in roots if r["count"] > 0]

    # 8. Breadcrumb map for the table column.
    path_map = {}

    def collect_paths(node):
        path_map[node["key"]] = " / ".join(node["path"])
        for ch in node["children"]:
            collect_paths(ch)

    for r in roots:
        collect_paths(r)

    roots.sort(key=lambda r: (0 if r.get("is_unfiled") else 1,
                              (r["name"] or "").lower()))
    return roots, path_map


def build(include_archived=False):
    manifest = _common.load_manifest()
    papers_all = manifest.get("papers", [])
    papers = [p for p in papers_all
              if include_archived or p.get("status") != "archived"]

    # Flat paper list for the frontend.
    papers_flat = []
    for p in papers:
        meta = p.get("metadata", {})
        papers_flat.append({
            "key": p["zotero_key"],
            "title": meta.get("title", ""),
            "authors": _format_authors_short(meta.get("creators", [])),
            "year": str(meta.get("publicationYear", "")),
            "venue": meta.get("venue", ""),
            "status": p.get("status", "reading"),
            "tags": p.get("tags", []),
            "html_path": p.get("html_path", "papers/%s.html" % p["zotero_key"]),
            "annotation_count": p.get("annotation_count", 0),
            "reading_time_minutes": p.get("reading_time_minutes", 0),
            "read_by_day": p.get("reading_by_day", []),
            "read_dates": p.get("read_dates", []),
            # Keep the full {key,name,parent} dicts here — the tree builder
            # needs the key + parent to reconstruct nesting. The downstream
            # block converts this to a names list for card/table meta.
            "collections": p.get("collections", []),
        })
    # newest first by latest read_by_day date
    papers_flat.sort(key=lambda x: (x["read_by_day"][-1]["date"]
                                    if x.get("read_by_day") else
                                    (x["read_dates"][-1].get("date", "") if x.get("read_dates") else "")),
                     reverse=True)

    # Collection hierarchy (nested tree with parent→child relationships).
    groups, collection_path_map = _build_collection_hierarchy(papers_flat)

    # Per-paper collection breadcrumb paths (for the table view column).
    for p in papers_flat:
        paths = []
        for c in p.get("collections", []):
            key = c.get("key") if isinstance(c, dict) else c
            if key in collection_path_map:
                paths.append(collection_path_map[key])
        p["collection_paths"] = paths
        # Keep a names list for backward-compatible card meta / fallback.
        p["collections"] = [
            (c.get("name", "") if isinstance(c, dict) else c)
            for c in p.get("collections", [])
        ]

    # Daily reading-minutes calendar (full range — frontend crops to selected range).
    # Build a {date: {minutes, papers[]}} map from each paper's reading_by_day.
    today = datetime.now().date()
    span_start = today - timedelta(days=730)  # up to 2 years of history
    day_map = {}
    for p in papers_flat:
        for rd in p.get("read_by_day", []):
            d = rd.get("date")
            if not d:
                continue
            if d not in day_map:
                day_map[d] = {"date": d, "minutes": 0, "papers": []}
            day_map[d]["minutes"] += rd.get("minutes", 0)
            if p["title"] not in day_map[d]["papers"]:
                day_map[d]["papers"].append(p["title"])
    calendar = [day_map[d] for d in sorted(day_map.keys())
                if datetime.strptime(d, "%Y-%m-%d").date() >= span_start]

    # Stats.
    total = len(papers_flat)
    reading = sum(1 for p in papers_flat if p["status"] == "reading")
    done = sum(1 for p in papers_flat if p["status"] == "done")
    total_annots = sum(p["annotation_count"] for p in papers_flat)
    total_reading_minutes = sum(p["reading_time_minutes"] for p in papers_flat)
    stats = {
        "total": total, "reading": reading, "done": done,
        "total_annotations": total_annots,
        "total_reading_minutes": total_reading_minutes,
    }

    first_paper_path = papers_flat[0]["html_path"] if papers_flat else "#"

    def _json(obj):
        return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")

    # First-call config (language / default accent / Zotero connection).
    cfg = _common.load_config()
    zotero_mode = "on" if cfg["connect_zotero"] else "off"
    projects = _common.load_research_projects().get("projects", [])
    research_paths = _research_html_paths(projects)
    research_compact = [{
        "id": p.get("id"), "name": p.get("name"),
        "status": p.get("status", "active"),
        "research_question": p.get("research_question", ""),
        "keywords": p.get("keywords", []),
        "html_path": research_paths[p["id"]],
    } for p in projects]

    replacements = {
        "__PAPERS_JSON__": _json(papers_flat),
        "__RESEARCH_JSON__": _json(research_compact),
        "__GROUPS_JSON__": _json(groups),
        "__CALENDAR_JSON__": _json(calendar),
        "__STATS_JSON__": _json(stats),
        "__TOTAL_PAPERS__": str(total),
        "__FIRST_PAPER_PATH__": _common.html_escape(first_paper_path),
        "__GENERATED_AT__": _common.now_iso(),
        "__DEFAULT_ACCENT__": cfg["default_accent"],
        "__ZOTERO_MODE__": zotero_mode,
    }

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return _common.apply_placeholders(template, replacements, DASHBOARD_PLACEHOLDER_REGISTRY)


def main():
    ap = argparse.ArgumentParser(description="Build the reading dashboard HTML.")
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    # Guard: in obsidian-only mode the HTML dashboard is not maintained.
    # add/finalize render the Obsidian dashboard via build_markdown, so this
    # script must not (re)write html/dashboard.html or html/research/ here.
    # --stdout stays available for piping in any mode.
    if not args.stdout and _common.load_config().get("output_mode", "html") == "obsidian":
        sys.stderr.write("Skipped HTML dashboard: output_mode=obsidian "
                         "(Obsidian dashboard is maintained by build_markdown).\n")
        return

    html = build(args.include_archived)

    if args.stdout:
        sys.stdout.write(html)
        return

    _common.ensure_output_dirs()
    _common.copy_fonts()
    projects = _common.load_research_projects().get("projects", [])
    _write_research_pages(projects, _common.load_config())
    out = _common.DASHBOARD_PATH
    out.write_text(html, encoding="utf-8")
    sys.stderr.write("Wrote %s\n" % out)


if __name__ == "__main__":
    main()
