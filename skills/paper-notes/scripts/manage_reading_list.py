#!/usr/bin/env python3
"""Manage the close-reading manifest (reading-list.json).

Subcommands:
    add      Add a paper by Zotero key. Fetches metadata + annotations,
             writes an empty summary template, renders HTML, updates the
             manifest, and prints a JSON status (including next_step:
             "generate_summary" to signal the LLM should fill the summary).
    remove   Delete a paper's record + generated files (optionally keep edits).
    archive  Mark a paper as archived (hidden from dashboard, files kept).
    restore  Move an archived paper back to "reading".
    list     Print the manifest (human-readable or --json).
    refresh  Re-fetch metadata + annotations + re-render HTML (keeps edits).
             Use --regenerate-summary to flag the summary for LLM regeneration.
    mark     Set a paper's status (reading | done | archived).

Usage:
    python3 manage_reading_list.py add --key VNPN6FHT
    python3 manage_reading_list.py add --search "Lutz gender migration"
    python3 manage_reading_list.py add --doi 10.1177/1350506808090759
    python3 manage_reading_list.py list --json
    python3 manage_reading_list.py refresh --key VNPN6FHT --regenerate-summary
    python3 manage_reading_list.py mark --key VNPN6FHT --status done
    python3 manage_reading_list.py remove --key VNPN6FHT
    python3 manage_reading_list.py archive --key VNPN6FHT

Zero dependencies — stdlib only. Calls zotero.py, fetch_annotations.py and
build_paper_html.py as subprocesses.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import _common

HERE = Path(__file__).resolve().parent
FETCH_ANN = HERE / "fetch_annotations.py"
BUILD_HTML = HERE / "build_paper_html.py"
BUILD_DASHBOARD = HERE / "build_dashboard.py"
EXTRACT_FIG = HERE / "extract_figures.py"
EXTRACT_SECTIONS = HERE / "extract_sections.py"


def _resolve_figure_python():
    """Find a Python interpreter that has PyMuPDF (fitz) installed.

    extract_figures.py needs PyMuPDF. Resolution order (no hardcoded home
    directory, so the skill is portable across users/machines):
      1. $LITERATURE_READER_FIGURE_PYTHON — explicit override.
      2. A managed venv (standard layout under the user's home directory, so
         Path.home() keeps it user-agnostic).
      3. The interpreter currently running this script (sys.executable).
    Returns a path string. Callers handle "PyMuPDF missing" gracefully if no
    candidate actually has it.
    """
    override = os.environ.get("LITERATURE_READER_FIGURE_PYTHON", "").strip()
    if override and Path(override).is_file():
        return override
    wb_venv = (
        Path.home()
        / ".workbuddy"
        / "binaries"
        / "python"
        / "envs"
        / "default"
        / "bin"
        / "python"
    )
    if wb_venv.is_file():
        return str(wb_venv)
    return sys.executable

# Empty summary template — the LLM fills this in after `add` returns.
# Schema is Heilmeier's catechism adapted for paper reading (see
# references/summary_schema.md). Figures are NOT part of the summary — they
# come from extract_figures.py writing papers/<KEY>_images/manifest.json.
SUMMARY_TEMPLATE = {
    "schema_version": 3,
    "zotero_key": "",
    "generated_at": "",
    "model": "",
    "paper_type": [],
    "keywords": [],
    "one_sentence_summary": "",
    "research_question": "",
    "contribution": "",
    "background_and_gap": "",
    "data_or_materials": "",
    "method_or_design": "",
    "results_or_claims": "",
    "benchmark_or_dataset_details": "",
    "limitations_and_threats": [],
    "reproduction_conditions": "",
    "interpretation": "",
    "relevance_to_my_work": "",
    "evidence_map": [],
    "uncertainties": [],
    "key_quotes": [],
    "open_questions": [],
    "custom_notes": "",
}


# ─── zotero.py wrapper ───────────────────────────────────────────────────────

def _run_zotero(*args):
    """Run the zotero skill's script with --json and return parsed JSON.

    args are the subcommand + its args (e.g. ['get', 'VNPN6FHT']).
    """
    zpy = str(_common.zotero_py_path())
    cmd = [sys.executable, zpy, "--json"] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        sys.stderr.write("zotero.py %s failed: %s\n" % (" ".join(args), proc.stderr.strip()))
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _run_script(script, *args):
    """Run a sibling python script, returning (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(script)] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_figures(key, pdf_attachment_key=None):
    """Best-effort figure extraction via a PyMuPDF-capable python.

    extract_figures.py imports PyMuPDF, so it must run with an interpreter that
    has the package. _resolve_figure_python() locates one. Returns the manifest
    dict or None on failure.
    """
    fig_python = _resolve_figure_python()
    args = [fig_python, str(EXTRACT_FIG), key, "--max", "8"]
    if pdf_attachment_key:
        args += ["--pdf-attachment-key", pdf_attachment_key]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not proc.stdout.strip():
            sys.stderr.write("figure extraction failed: %s\n" % proc.stderr.strip())
            return None
        return json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _extract_figures_local(key, pdf_path):
    """Figure extraction for a local PDF (no Zotero) using a PyMuPDF-capable python.

    Runs extract_figures.extract() with pdf_bytes supplied directly, so PyMuPDF
    loads in the right interpreter. Returns the manifest dict or None on failure.
    """
    fig_python = _resolve_figure_python()
    code = (
        "import sys, json; sys.path.insert(0, %r);"
        "import extract_figures as ef;"
        "b=open(%r,'rb').read();"
        "print(json.dumps(ef.extract(%r, pdf_bytes=b), ensure_ascii=False))"
    ) % (str(HERE), str(pdf_path), key)
    try:
        proc = subprocess.run([fig_python, "-c", code],
                              capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not proc.stdout.strip():
            sys.stderr.write("figure extraction error: %s\n" % proc.stderr.strip())
            return None
        return json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _extract_sections(key, pdf_attachment_key=None, pdf_path=None):
    """Extract searchable PDF text before summary generation.

    This is a required preparation step whenever a local PDF exists. The LLM
    later receives section_text.json, never the PDF or extracted images.
    """
    py = _resolve_figure_python()
    args = [py, str(EXTRACT_SECTIONS), "--key", key]
    if pdf_path:
        args += ["--pdf", str(pdf_path)]
    elif pdf_attachment_key:
        args += ["--pdf-attachment-key", pdf_attachment_key]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
        out_path = _common.PAPERS_DIR / (key + ".section_text.json")
        if proc.returncode != 0 or not out_path.is_file():
            return False, proc.stderr.strip() or "section_text.json was not created"
        data = json.loads(out_path.read_text(encoding="utf-8"))
        sections = data.get("sections", [])
        text_len = sum(len(s.get("text", "")) for s in sections if isinstance(s, dict))
        if not sections or text_len < 200:
            return False, "PDF text extraction returned no usable body text"
        return True, "%d sections, %d characters" % (len(sections), text_len)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
        return False, str(exc)


def _extract_year(date_str):
    """Pull a 4-digit year from a Zotero date field."""
    if not date_str:
        return None
    m = re.search(r"(19|20)\d{2}", str(date_str))
    return m.group(0) if m else None


def _normalize_metadata(item):
    """Flatten a Zotero item into the manifest metadata structure."""
    d = item.get("data", item)
    venue = d.get("publicationTitle") or d.get("proceedingsTitle") or \
            d.get("publisher") or d.get("bookTitle") or ""
    return {
        "title": d.get("title", "") or "",
        "creators": d.get("creators", []) or [],
        "itemType": d.get("itemType", "") or "",
        "date": d.get("date", "") or "",
        "venue": venue,
        "DOI": d.get("DOI", "") or "",
        "url": d.get("url", "") or "",
        "abstractNote": d.get("abstractNote", "") or "",
        "keywords": d.get("keywords") or d.get("keyword") or d.get("subjects") or [],
        "extra": d.get("extra", "") or "",
        "publicationYear": _extract_year(d.get("date", "")),
    }


def _resolve_collections(collection_keys, node_map):
    """Map collection keys to {key, name, parent} using a {key: {name, parent}} map.

    Falls back to the key itself as the name when a key is unknown (e.g. offline
    fallback), preserving the key so the dashboard can still group by it.
    """
    out = []
    for k in collection_keys or []:
        node = node_map.get(k) or {}
        out.append({
            "key": k,
            "name": node.get("name", k),
            "parent": node.get("parent"),
        })
    return out


def _build_collection_nodes():
    """Fetch the full collection tree and return {key: {name, parent}}.

    Uses the Web API directly (via _common) to get correct names AND the
    parentCollection relationship, which the human-readable `zotero.py
    collections` output does not expose as JSON.
    """
    tree = _common.fetch_collection_tree()
    m = {}
    for c in tree:
        m[c["key"]] = {"name": c["name"], "parent": c.get("parent")}
    return m


# ─── commands ───────────────────────────────────────────────────────────────

def _require_initialized():
    """Refuse add-type commands until first-run init has completed.

    Enforces the first-run setup at the code level (not just via SKILL.md): if
    the user never answered the language / accent / connect-zotero questions,
    `add` exits with a structured hint telling the LLM to run `init` first, so
    every generated page honors the user's choices from the very first paper.
    """
    cfg = _common.load_config()
    if cfg.get("initialized"):
        return
    sys.stderr.write(
        "paper-notes is not initialized. Ask the user the 3 first-run "
        "questions, then run: manage_reading_list.py init --language zh|en "
        "--accent rose|green|blue --connect-zotero yes|no\n"
    )
    print(json.dumps({
        "ok": False,
        "error": "not_initialized",
        "next_step": "run_init",
        "message": "First-run setup required. Ask the user for preferred "
                   "language, default accent color (rose/green/blue), and "
                   "whether to connect Zotero (yes/no), then run "
                   "`manage_reading_list.py init` with those answers before "
                   "adding papers.",
    }, ensure_ascii=False, indent=2))
    sys.exit(3)


def _write_empty_summary(key):
    """Write an empty Heilmeier summary template for the LLM to fill later."""
    summary = json.loads(json.dumps(SUMMARY_TEMPLATE))
    summary["zotero_key"] = key
    (_common.PAPERS_DIR / (key + ".summary.json")).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_annotations(key, ann_data):
    """Cache a paper's annotations/notes JSON for rendering."""
    _common.ensure_output_dirs()
    (_common.PAPERS_DIR / (key + ".annotations.json")).write_text(
        json.dumps(ann_data, ensure_ascii=False, indent=2), encoding="utf-8")


def _finalize_add(manifest, key, paper, status):
    """Common tail for both add paths: render HTML, append, save, print status."""
    _run_script(BUILD_HTML, "--key", key)
    manifest["papers"].append(paper)
    _common.save_manifest(manifest)
    print(json.dumps(status, ensure_ascii=False, indent=2))


def cmd_add(args):
    # First-run gate: block adds until the user has completed init (#4).
    _require_initialized()

    manifest = _common.load_manifest()
    existing = {p["zotero_key"] for p in manifest["papers"]}

    # ── Manual add (no Zotero): user supplies a local PDF + metadata. ──
    if args.manual:
        return _cmd_add_manual(args, manifest, existing)

    if args.search:
        candidates = _run_zotero("search", args.search)
        _print_candidates(candidates)
        return
    if args.doi:
        candidates = _run_zotero("search", args.doi)
        # filter by DOI match
        if isinstance(candidates, list):
            candidates = [c for c in candidates
                           if (c.get("data", {}).get("DOI") or "") == args.doi]
        _print_candidates(candidates)
        return
    if not args.key:
        sys.stderr.write("Provide --key, --search, or --doi.\n")
        sys.exit(1)

    key = args.key
    if key in existing:
        rec = next(p for p in manifest["papers"] if p["zotero_key"] == key)
        sys.stderr.write(
            "Paper %s already in list (status: %s). Use 'refresh' instead, "
            "or 'remove --key %s' first.\n" % (key, rec.get("status"), key)
        )
        sys.exit(2)

    # Fetch metadata
    item = _run_zotero("get", key)
    if not item:
        sys.stderr.write("Could not fetch item %s from Zotero.\n" % key)
        sys.exit(1)
    metadata = _normalize_metadata(item)

    # Resolve collection names + hierarchy.
    # NOTE: `zotero.py get --json` prints item["data"] directly, so the parsed
    # object already has `collections` at the top level (a list of key strings).
    col_map = _build_collection_nodes()
    col_keys = item.get("collections", []) or []
    col_keys = [c for c in col_keys if isinstance(c, str)]
    collections = _resolve_collections(col_keys, col_map)

    tags = [t.get("tag", "") for t in item.get("tags", [])
            if isinstance(t, dict)]

    # Fetch annotations
    rc, out, err = _run_script(FETCH_ANN, key)
    ann_data = None
    if rc == 0 and out.strip():
        try:
            ann_data = json.loads(out)
        except json.JSONDecodeError:
            ann_data = None
    if ann_data is None:
        ann_data = {"annotations": [], "notes": [],
                    "has_pdf": False, "has_annotations": False,
                    "annotation_count": 0, "annotation_summary": {},
                    "pdf_attachment_key": None}

    # Cache annotations for rendering
    _cache_annotations(key, ann_data)

    # Full-text extraction is required before summary generation whenever a
    # Zotero PDF is available. Do not silently fall back to abstract-only notes.
    if ann_data.get("has_pdf") and ann_data.get("pdf_attachment_key"):
        ok, detail = _extract_sections(key, ann_data["pdf_attachment_key"])
        if not ok:
            sys.stderr.write("正文抽取失败，已停止添加：%s\n" % detail)
            sys.exit(1)

    # Compute read_dates from annotations (historical reading record)
    read_dates = _compute_read_dates(item, ann_data)

    # Best-effort figure extraction from the PDF (needs PyMuPDF in managed venv).
    # Writes papers/<KEY>_images/manifest.json on success.
    if ann_data.get("has_pdf") and ann_data.get("pdf_attachment_key"):
        _extract_figures(key, ann_data["pdf_attachment_key"])

    # Write empty summary template (LLM fills it next)
    _write_empty_summary(key)

    # Append manifest entry
    paper = {
        "zotero_key": key,
        "status": args.status or "reading",
        "date_added_to_reading": _common.now_iso(),
        "last_synced": _common.now_iso(),
        "last_viewed": "",
        "html_path": "papers/%s.html" % key,
        "edits_path": "papers/%s.edits.json" % key,
        "summary_path": "papers/%s.summary.json" % key,
        "metadata": metadata,
        "collections": collections,
        "tags": tags,
        "pdf_attachment_key": ann_data.get("pdf_attachment_key"),
        "annotation_count": ann_data.get("annotation_count", 0),
        "annotation_summary": ann_data.get("annotation_summary", {}),
        "read_dates": read_dates,
        "reading_time_minutes": ann_data.get("reading_time_minutes", 0),
        "reading_by_day": ann_data.get("reading_by_day", []),
        "has_pdf": ann_data.get("has_pdf", False),
        "has_annotations": ann_data.get("has_annotations", False),
        "user_edits_version": 0,
        "notes": "",
    }

    # Render, append, save, and signal next step (shared tail).
    _finalize_add(manifest, key, paper, {
        "ok": True,
        "next_step": "generate_summary",
        "key": key,
        "title": metadata["title"],
        "html_path": "papers/%s.html" % key,
        "annotation_count": paper["annotation_count"],
        "has_pdf": paper["has_pdf"],
        "message": "Paper added with empty summary. Generate structured summary "
                   "per references/summary_schema.md, then re-run build_paper_html.",
    })


def _gen_local_key(seed):
    """Generate a stable synthetic key for a manually-added (non-Zotero) paper."""
    return "local-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def _cmd_add_manual(args, manifest, existing):
    """Add a paper from a local PDF without a Zotero connection.

    Reads PDF bytes, extracts figures locally, writes metadata + an empty
    summary template, renders the HTML, and appends a manifest entry. The key
    is synthetic ('local-<hash>'). Used when the user opts out of Zotero in
    the first-call init.
    """
    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.is_file():
        sys.stderr.write("PDF not found: %s\n" % pdf_path)
        sys.exit(1)
    pdf_bytes = pdf_path.read_bytes()

    seed = (args.title or "") + str(pdf_path)
    key = _gen_local_key(seed)
    if key in existing:
        rec = next(p for p in manifest["papers"] if p["zotero_key"] == key)
        sys.stderr.write("Paper %s already added (status: %s).\n"
                        % (key, rec.get("status")))
        sys.exit(2)

    # Best-effort figure extraction from the local PDF (needs PyMuPDF in venv).
    fig_count = 0
    fig_manifest = _extract_figures_local(key, pdf_path)
    ok, detail = _extract_sections(key, pdf_path=pdf_path)
    if not ok:
        sys.stderr.write("正文抽取失败，已停止添加：%s\n" % detail)
        sys.exit(1)
    if fig_manifest:
        fig_count = fig_manifest.get("count", 0)

    creators = [{"name": args.authors}] if args.authors else []
    metadata = {
        "title": args.title or pdf_path.stem,
        "creators": creators,
        "itemType": "manuscript",
        "date": "",
        "venue": args.venue or "",
        "DOI": args.doi or "",
        "url": "",
        "abstractNote": args.abstract or "",
        "keywords": [],
        "extra": "",
        "publicationYear": args.year or "",
    }

    # Cache an empty annotations record (no Zotero highlights available).
    ann_data = {"annotations": [], "notes": [], "has_pdf": True,
                "has_annotations": False, "annotation_count": 0,
                "annotation_summary": {}, "pdf_attachment_key": None}
    _cache_annotations(key, ann_data)

    # Empty summary template for the LLM to fill.
    _write_empty_summary(key)

    paper = {
        "zotero_key": key,
        "status": args.status or "reading",
        "date_added_to_reading": _common.now_iso(),
        "last_synced": _common.now_iso(),
        "last_viewed": "",
        "html_path": "papers/%s.html" % key,
        "edits_path": "papers/%s.edits.json" % key,
        "summary_path": "papers/%s.summary.json" % key,
        "metadata": metadata,
        "collections": [],
        "tags": [],
        "pdf_attachment_key": None,
        "annotation_count": 0,
        "annotation_summary": {},
        "read_dates": [],
        "reading_time_minutes": 0,
        "reading_by_day": [],
        "has_pdf": True,
        "has_annotations": False,
        "manual": True,
        "user_edits_version": 0,
        "notes": "",
    }

    # Render, append, save, and signal next step (shared tail).
    _finalize_add(manifest, key, paper, {
        "ok": True,
        "next_step": "generate_summary",
        "key": key,
        "title": metadata["title"],
        "html_path": "papers/%s.html" % key,
        "annotation_count": 0,
        "has_pdf": True,
        "manual": True,
        "message": "Manually-added paper (no Zotero). Generate structured "
                   "summary per references/summary_schema.md, then re-run "
                   "build_paper_html.",
    })


def cmd_init(args):
    """Persist first-call preferences to litreader.config.json."""
    cfg = {
        "initialized": True,
        "language": args.language,
        "default_accent": args.accent,
        "connect_zotero": (args.connect_zotero == "yes"),
    }
    _common.save_config(cfg)
    # Rebuild dashboard + all papers so the new accent / Zotero settings take
    # effect immediately. Config is read at build time, not render time, so an
    # init after papers were added would otherwise leave stale values in HTML.
    _run_script(BUILD_DASHBOARD)
    manifest = _common.load_manifest()
    for p in manifest.get("papers", []):
        _run_script(BUILD_HTML, "--key", p["zotero_key"])
    print(json.dumps({"ok": True, "config": _common.load_config()},
                     ensure_ascii=False, indent=2))


def _print_candidates(candidates):
    if not candidates:
        print(json.dumps({"ok": True, "candidates": [], "message": "No matches."}))
        return
    out = []
    for c in candidates[:8]:
        d = c.get("data", {})
        creators = d.get("creators", [])
        first = ""
        if creators:
            ln = creators[0].get("lastName") or creators[0].get("name") or ""
            first = ln + (", " + (creators[0].get("firstName") or "")[0:1] + "." if creators[0].get("firstName") else "")
        out.append({
            "key": c.get("key"),
            "title": d.get("title", ""),
            "creators": first,
            "year": _extract_year(d.get("date", "")),
            "itemType": d.get("itemType", ""),
            "doi": d.get("DOI", ""),
        })
    print(json.dumps({"ok": True, "candidates": out,
                      "message": "Confirm which to add (use its key)."}, ensure_ascii=False, indent=2))


def _compute_read_dates(item, ann_data):
    """Build read_dates for the historical calendar.

    Sources (in priority): annotation dateAdded (grouped by day, count),
    then the paper's dateAdded as a reading-start approximation.
    """
    by_day = {}
    for ann in ann_data.get("annotations", []):
        day = ann.get("date_added_day")
        if day:
            by_day[day] = by_day.get(day, 0) + 1
    read_dates = [{"date": d, "source": "annotation", "count": c}
                  for d, c in sorted(by_day.items())]
    # Paper dateAdded as a baseline marker if no annotation dates exist.
    # `_run_zotero("get", key)` returns the item's data dict directly (not
    # wrapped in {"data": ...}), so accept both shapes.
    data = item.get("data", item) if isinstance(item, dict) else {}
    paper_added = data.get("dateAdded", "")
    paper_day = None
    if paper_added:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", paper_added)
        paper_day = m.group(1) if m else None
    if paper_day and paper_day not in by_day:
        read_dates.insert(0, {"date": paper_day, "source": "dateAdded", "count": 0})
    return read_dates


def cmd_remove(args):
    try:
        _common.validate_paper_key(args.key)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        sys.exit(1)
    manifest = _common.load_manifest()
    new_papers = []
    removed = False
    for p in manifest["papers"]:
        if p["zotero_key"] == args.key:
            removed = True
            # delete generated files
            for suffix in (".html", ".summary.json", ".annotations.json",
                           ".sections.json", ".section_text.json"):
                f = _common.PAPERS_DIR / (args.key + suffix)
                if f.exists():
                    f.unlink()
            image_dir = _common.PAPERS_DIR / (args.key + "_images")
            if image_dir.is_dir():
                for child in image_dir.iterdir():
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                image_dir.rmdir()
            if not args.keep_edits:
                ef = _common.PAPERS_DIR / (args.key + ".edits.json")
                if ef.exists():
                    ef.unlink()
        else:
            new_papers.append(p)
    if not removed:
        sys.stderr.write("Paper %s not in manifest.\n" % args.key)
        sys.exit(1)
    manifest["papers"] = new_papers
    _common.save_manifest(manifest)
    print(json.dumps({"ok": True, "key": args.key, "removed": True}))


def _set_status(args, status):
    try:
        _common.validate_paper_key(args.key)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        sys.exit(1)
    manifest = _common.load_manifest()
    found = False
    for p in manifest["papers"]:
        if p["zotero_key"] == args.key:
            p["status"] = status
            p["last_synced"] = _common.now_iso()
            found = True
            break
    if not found:
        sys.stderr.write("Paper %s not in manifest.\n" % args.key)
        sys.exit(1)
    _common.save_manifest(manifest)
    print(json.dumps({"ok": True, "key": args.key, "status": status}))


def cmd_archive(args):
    _set_status(args, "archived")


def cmd_restore(args):
    _set_status(args, "reading")


def cmd_mark(args):
    if args.status not in ("reading", "done", "archived"):
        sys.stderr.write("status must be reading | done | archived\n")
        sys.exit(1)
    _set_status(args, args.status)


def cmd_list(args):
    manifest = _common.load_manifest()
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    papers = manifest["papers"]
    if args.status:
        papers = [p for p in papers if p.get("status") == args.status]
    if not papers:
        print("(empty)")
        return
    print("%-10s  %-8s  %-6s  %s" % ("KEY", "STATUS", "ANNOTS", "TITLE"))
    print("-" * 72)
    for p in papers:
        title = p.get("metadata", {}).get("title", "")[:48]
        print("%-10s  %-8s  %-6d  %s" % (
            p["zotero_key"], p.get("status", "?"),
            p.get("annotation_count", 0), title))


def cmd_refresh(args):
    manifest = _common.load_manifest()
    keys = []
    if args.all:
        keys = [p["zotero_key"] for p in manifest["papers"]]
    elif args.key:
        try:
            _common.validate_paper_key(args.key)
        except ValueError as exc:
            sys.stderr.write(str(exc) + "\n")
            sys.exit(1)
        keys = [args.key]
    else:
        sys.stderr.write("Provide --key or --all.\n")
        sys.exit(1)

    col_map = _build_collection_nodes()
    import time as _t
    for i, key in enumerate(keys):
        if i > 0:
            _t.sleep(0.5)
        _refresh_one(manifest, key, col_map, args.regenerate_summary)
    _common.save_manifest(manifest)
    print(json.dumps({"ok": True, "refreshed": keys,
                      "regenerate_summary": bool(args.regenerate_summary)}))


def _refresh_one(manifest, key, col_map, regenerate_summary):
    paper = next((p for p in manifest["papers"] if p["zotero_key"] == key), None)
    if not paper:
        sys.stderr.write("Paper %s not in manifest.\n" % key)
        return
    item = _run_zotero("get", key)
    if item:
        paper["metadata"] = _normalize_metadata(item)
        # `zotero.py get --json` prints data directly; collections is a list of
        # key strings at the top level.
        col_keys = item.get("collections", []) or []
        col_keys = [c for c in col_keys if isinstance(c, str)]
        paper["collections"] = _resolve_collections(col_keys, col_map)
        paper["tags"] = [t.get("tag", "") for t in item.get("tags", [])
                         if isinstance(t, dict)]

    rc, out, err = _run_script(FETCH_ANN, key)
    ann_data = None
    if rc == 0 and out.strip():
        try:
            ann_data = json.loads(out)
        except json.JSONDecodeError:
            ann_data = None
    if ann_data is None:
        ann_data = {"annotations": [], "notes": [], "has_pdf": False,
                    "has_annotations": False, "annotation_count": 0,
                    "annotation_summary": {}, "pdf_attachment_key": None}
    _cache_annotations(key, ann_data)
    paper["pdf_attachment_key"] = ann_data.get("pdf_attachment_key")
    paper["annotation_count"] = ann_data.get("annotation_count", 0)
    paper["annotation_summary"] = ann_data.get("annotation_summary", {})
    paper["has_pdf"] = ann_data.get("has_pdf", False)
    paper["has_annotations"] = ann_data.get("has_annotations", False)
    paper["read_dates"] = _compute_read_dates(item or {}, ann_data)
    paper["reading_time_minutes"] = ann_data.get("reading_time_minutes", 0)
    paper["reading_by_day"] = ann_data.get("reading_by_day", [])

    if ann_data.get("has_pdf") and ann_data.get("pdf_attachment_key"):
        ok, detail = _extract_sections(key, ann_data["pdf_attachment_key"])
        if not ok:
            sys.stderr.write("正文抽取失败，未生成新的 summary：%s\n" % detail)
            return

    # Re-extract figures if a PDF is present (best-effort).
    if ann_data.get("has_pdf") and ann_data.get("pdf_attachment_key"):
        _extract_figures(key, ann_data["pdf_attachment_key"])

    if regenerate_summary:
        _write_empty_summary(key)
        # NOTE: edits.json is NOT removed — user edits persist. Only the
        # summary is blanked for LLM regeneration. The LLM should generate a
        # fresh summary; if edits.json exists it will still override at render.

    _run_script(BUILD_HTML, "--key", key)
    paper["last_synced"] = _common.now_iso()


def main():
    ap = argparse.ArgumentParser(description="Manage the close-reading manifest.")
    sub = ap.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Add a paper to the reading list")
    p_add.add_argument("--key", help="Zotero item key")
    p_add.add_argument("--search", help="Search query (prints candidates, no add)")
    p_add.add_argument("--doi", help="DOI (prints matching candidate, no add)")
    p_add.add_argument("--status", choices=["reading", "done"],
                       help="Initial status (default reading)")
    p_add.add_argument("--manual", action="store_true",
                       help="Add from a local PDF without Zotero")
    p_add.add_argument("--pdf", help="Local PDF path (with --manual)")
    p_add.add_argument("--title", help="Title (--manual)")
    p_add.add_argument("--authors", help="Authors, free text (--manual)")
    p_add.add_argument("--year", help="Year (--manual)")
    p_add.add_argument("--venue", help="Journal / venue (--manual)")
    p_add.add_argument("--abstract", help="Abstract text (--manual)")
    p_add.set_defaults(func=cmd_add)

    p_init = sub.add_parser("init",
                            help="Save first-call preferences (language, accent, Zotero)")
    p_init.add_argument("--language", choices=["zh", "en"], required=True)
    p_init.add_argument("--accent", dest="accent",
                        choices=["rose", "green", "blue"], required=True)
    p_init.add_argument("--connect-zotero", dest="connect_zotero",
                        choices=["yes", "no"], required=True)
    p_init.set_defaults(func=cmd_init)

    p_rm = sub.add_parser("remove", help="Remove a paper + its files")
    p_rm.add_argument("--key", required=True)
    p_rm.add_argument("--keep-edits", action="store_true", help="Keep .edits.json")
    p_rm.set_defaults(func=cmd_remove)

    p_arc = sub.add_parser("archive", help="Archive a paper")
    p_arc.add_argument("--key", required=True)
    p_arc.set_defaults(func=cmd_archive)

    p_res = sub.add_parser("restore", help="Restore an archived paper")
    p_res.add_argument("--key", required=True)
    p_res.set_defaults(func=cmd_restore)

    p_list = sub.add_parser("list", help="List the manifest")
    p_list.add_argument("--status", choices=["reading", "done", "archived"])
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_ref = sub.add_parser("refresh", help="Re-fetch + re-render")
    p_ref.add_argument("--key")
    p_ref.add_argument("--all", action="store_true")
    p_ref.add_argument("--regenerate-summary", action="store_true",
                       help="Blank the summary for LLM regeneration (keeps edits)")
    p_ref.set_defaults(func=cmd_refresh)

    p_mark = sub.add_parser("mark", help="Set status")
    p_mark.add_argument("--key", required=True)
    p_mark.add_argument("--status", required=True,
                        choices=["reading", "done", "archived"])
    p_mark.set_defaults(func=cmd_mark)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
