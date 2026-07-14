#!/usr/bin/env python3
"""Render a single close-reading HTML page for a paper.

Reads the paper manifest entry + cached annotations + the LLM-generated
structured summary (+ optional user edits) and applies them to
assets/paper_template.html via __PLACEHOLDER__ replacement.

Usage:
    python3 build_paper_html.py --key VNPN6FHT
    python3 build_paper_html.py --key VNPN6FHT --summary-file /tmp/summ.json
    python3 build_paper_html.py --key VNPN6FHT --stdout

Edits (papers/<KEY>.edits.json) override the summary when present, so user
edits survive refresh. Zero dependencies — stdlib only.
"""

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

import _common

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE.parent / "assets" / "paper_template.html"

# Every __TOKEN__ the template knows about. Unused ones are cleaned to "".
PAPER_PLACEHOLDER_REGISTRY = [
    "__TITLE__", "__AUTHORS__", "__YEAR__", "__VENUE__",
    "__DOI__", "__DOI_LINK__", "__ZOTERO_KEY__", "__COLLECTIONS__",
    "__TAGS_HTML__", "__KEYWORDS_ROW__", "__ABSTRACT__", "__STATUS__",
    # Heilmeier Q1-Q7
    "__OBJECTIVE__", "__PROBLEM_LANDSCAPE__", "__APPROACH__", "__IMPACT__",
    "__RISKS_HTML__", "__COST__", "__EXPERIMENTS_RESULTS__",
    # kept
    "__RELEVANCE__", "__KEY_QUOTES_HTML__", "__OPEN_QUESTIONS_HTML__",
    "__CUSTOM_NOTES__", "__FIGURES_HTML__", "__SECTIONS_HTML__",
    "__HIGHLIGHTS_HTML__", "__NOTES_HTML__",
    "__ANNOTATION_COUNT__", "__READING_TIME__",
    "__INITIAL_EDITS_JSON__", "__GENERATED_AT__",
    # First-call config (injected from litreader.config.json)
    "__DEFAULT_ACCENT__", "__ZOTERO_MODE__",
]

# Highlight color → soft background for swatches in the highlights panel.
_SWATCH_BG = {
    "yellow":  "#ffd400",
    "red":     "#ff6666",
    "green":   "#5fb236",
    "blue":    "#2ea8e5",
    "purple":  "#a28ae5",
    "magenta": "#e56eee",
    "other":   "#C9C0B8",
}


def format_authors(creators, max_shown=3):
    """Render authors for the PAPER page: up to `max_shown` (default 3) authors,
    then 'et al.'.

    e.g. "Zhao, J." (1) / "Zhao, J. & Liang, J." (2) /
    "Zhao, J., Liang, J. & Cai, Z." (3) / 4+ → "Zhao, J., Liang, J., Cai, Z. et al."
    Filters to author-type creators; falls back to whatever name fields exist.
    (The dashboard keeps its own 1-author short form — _format_authors_short — untouched.)
    """
    if not creators:
        return ""
    names = []
    for c in creators:
        if c.get("creatorType") and c["creatorType"] not in ("author", None):
            continue
        last = (c.get("lastName") or "").strip()
        first = (c.get("firstName") or "").strip()
        if last and first:
            names.append("%s, %s." % (last, first[0]))
        elif last:
            names.append(last)
        elif first:
            names.append(first)
    if not names:
        # fall back to whatever fields exist
        for c in creators:
            nm = (c.get("name") or "").strip()
            if nm:
                names.append(nm)
    if len(names) == 0:
        return ""
    if len(names) <= 2:
        if len(names) == 1:
            return names[0]
        return names[0] + " & " + names[1]
    if len(names) == max_shown:
        # exactly max_shown authors → list all of them
        return ", ".join(names[:-1]) + " & " + names[-1]
    # more than max_shown → first max_shown + "et al."
    return ", ".join(names[:max_shown]) + " et al."


def mdInline(s):
    """Python mirror of the template's mdInline JS: safe inline markdown.

    HTML is escaped first (so raw tags can't inject), LaTeX delimiters
    ($…$) survive untouched for MathJax, then **bold**, `code`, *italic*,
    and [text](url) are applied. Keeps the build-time static HTML in sync
    with what the browser re-renders via mdInline on edit/load, so list
    items and quote blocks show bold without waiting for JS.
    """
    if s is None:
        return ""
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(?!\s)([^*]+?)(?<!\s)\*\*", r"<strong>\1</strong>", s)
    # italic uses * only (not _), mirroring the JS rule
    s = re.sub(r"(^|[^*])\*([^*\s][^*]*?)\*", r"\1<em>\2</em>", s)
    def safe_link(match):
        label, url = match.group(1), match.group(2)
        scheme = urllib.parse.urlsplit(url).scheme.lower()
        if scheme and scheme not in {"http", "https", "mailto"}:
            return match.group(0)
        href = (url.replace('"', '&quot;').replace("'", "&#39;")
                .replace("\n", "").replace("\r", ""))
        return '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (href, label)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+(?:\([^)]*\)[^)\s]*)*)\)", safe_link, s)
    return s

def render_list(items):
    """Render a list[str] as <li>…</li> items (no <ol> wrapper — caller adds it).

    Applies mdInline so **bold** etc. render in the static build (the
    browser re-applies it via mdInline on edit/load)."""
    if not items:
        return '<li data-placeholder="点击编辑…"></li>'
    out = []
    for item in items:
        out.append("<li>" + mdInline(item) + "</li>")
    return "".join(out)


def render_prose(text):
    """Render a multi-paragraph string as <p>…</p> blocks.

    The LLM (and hand edits) write long-form fields as natural paragraphs
    separated by a blank line ("\\n\\n"). Injecting the raw string through
    html_escape alone makes the browser collapse every newline into a space,
    so the whole field reads as one run-on block. This helper splits on blank
    lines into real <p> paragraphs, and preserves single newlines inside a
    paragraph as <br>. The output round-trips with the template's writeProse /
    readProse JS helpers (which rebuild the same <p> structure from text).

    Returns "" for empty input so the contenteditable stays truly :empty and
    the CSS placeholder shows.
    """
    if text is None:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""
    # Split on one-or-more blank lines into paragraphs.
    paragraphs = re.split(r"\n[ \t]*\n+", s)
    out = []
    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():
            continue
        lines = [mdInline(ln) for ln in para.split("\n")]
        out.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(out)


def paper_keywords(meta):
    """Return author-supplied keywords only; tags are not paper keywords."""
    raw = meta.get("keywords") or meta.get("keyword") or meta.get("subjects") or []
    if isinstance(raw, str):
        raw = re.split(r"[,;|]", raw)
    values = [str(x).strip() for x in raw if str(x).strip()]
    if not values:
        extra = str(meta.get("extra", ""))
        match = re.search(r"(?im)^keywords?\s*:\s*(.+)$", extra)
        if match:
            values = [x.strip() for x in re.split(r"[,;|]", match.group(1)) if x.strip()]
    if not values:
        return ""
    return ('<div class="head-status keywords-row">'
            '<span class="hs-label">Keywords</span>'
            '<span class="keywords-value">%s</span></div>'
            % _common.html_escape(" · ".join(values)))


def render_quotes(quotes):
    """Render key_quotes as .quote-block cards."""
    if not quotes:
        return '<div class="field-text" style="color:var(--ink-faint);font-style:italic;">尚无关键引文。在 Zotero 高亮会自动出现在下方"Highlights from Zotero"。</div>'
    out = []
    for i, q in enumerate(quotes):
        text = str(q.get("text", ""))
        note = str(q.get("note", ""))
        page = _common.html_escape(str(q.get("page", "")))
        color = _common.html_escape(q.get("color", ""))
        page_label = ("p." + page) if page else "no page"
        # data-tex keeps the RAW markdown source (lossless round-trip on edit);
        # the visible content is mdInline-rendered so **bold** shows statically.
        text_disp = mdInline(text) if text else ""
        note_disp = mdInline(note) if note else ""
        out.append(
            ('<div class="quote-block">'
            '<div class="qb-label"><span class="qb-swatch" style="background:%s;"></span>QUOTE %d · %s</div>'
            '<div class="quote-text editable" contenteditable="true" data-field="key_quotes.%d.text" data-tex="%s" data-placeholder="引文原文…">%s</div>'
            '<div class="quote-note editable" contenteditable="true" data-field="key_quotes.%d.note" data-tex="%s" data-placeholder="为什么这句重要…">%s</div>'
            '<span class="quote-meta" data-page="%s" data-color="%s"></span>'
            "</div>")
            % (color or "#C9C0B8", i + 1, page_label,
               i, _common.html_escape(text), text_disp,
               i, _common.html_escape(note), note_disp,
               page, color)
        )
    return "".join(out)


def render_highlights(annotations):
    """Render the read-only Zotero highlights panel grouped by color_category."""
    if not annotations:
        return '<div style="color:var(--ink-faint);font-style:italic;">未检测到 PDF 高亮。摘要基于 abstract 生成。</div>'
    groups = {}
    for ann in annotations:
        cat = ann.get("color_category", "other")
        groups.setdefault(cat, []).append(ann)
    # stable order
    order = ["yellow", "red", "green", "blue", "purple", "magenta", "other"]
    out = []
    for cat in order:
        items = groups.get(cat)
        if not items:
            continue
        swatch = _SWATCH_BG.get(cat, "#cccccc")
        out.append(
            '<div class="hl-group">'
            '<div class="hl-group-head"><span class="hl-swatch" style="background:%s;"></span>%s (%d)</div>'
            % (swatch, cat.capitalize(), len(items))
        )
        for ann in items:
            text = _common.html_escape(ann.get("text", ""))
            page = _common.html_escape(str(ann.get("page_label", "")))
            comment = ann.get("comment", "")
            atype = ann.get("type", "highlight")
            page_html = (' · <span class="hl-page">p.%s</span>' % page) if page else ""
            comment_html = ""
            if comment:
                comment_html = '<span class="hl-comment">» %s</span>' % _common.html_escape(comment)
            type_tag = ""
            if atype != "highlight":
                type_tag = '<em style="color:var(--ink-faint);font-size:11px;">[%s]</em> ' % atype
            out.append(
                '<div class="hl-item">%s%s%s</div>' % (type_tag, text, page_html)
            )
            if comment_html:
                out.append('<div class="hl-item is-comment">%s</div>' % comment_html)
        out.append("</div>")
    return "".join(out)


def render_notes(notes):
    """Render Zotero standalone notes (read-only)."""
    if not notes:
        return '<div style="color:var(--ink-faint);font-style:italic;">无 Zotero 笔记。</div>'
    out = []
    for n in notes:
        text = _common.html_escape(n.get("text", ""))
        out.append('<div class="hl-item is-comment">%s</div>' % text)
    return "".join(out)


def _safe_json_for_script(obj):
    """JSON-encode for embedding inside <script>, escaping < to prevent breakout."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


def format_reading_time(minutes):
    """Render reading minutes as '1h 6m' / '42m' / '—'."""
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        m = 0
    if m <= 0:
        return "—"
    h, rem = divmod(m, 60)
    if h > 0:
        return "%dh %02dm" % (h, rem)
    return "%dm" % rem


def render_figures(key):
    """Render the figures grid from papers/<KEY>_images/manifest.json.

    Returns HTML for the Figures section. If no manifest, returns an empty-state.
    """
    manifest_path = _common.PAPERS_DIR / (key + "_images") / "manifest.json"
    if not manifest_path.exists():
        return ('<div style="color:var(--ink-faint);font-style:italic;font-size:14px;">'
                '未提取到论文图表（extract_figures.py 需在有 PDF 时运行）。</div>')
    try:
        fig_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return '<div style="color:var(--ink-faint);font-style:italic;">图表清单读取失败。</div>'
    figures = fig_data.get("figures", [])
    if not figures:
        return '<div style="color:var(--ink-faint);font-style:italic;">PDF 中未发现可提取的图表。</div>'
    img_dir = fig_data.get("image_dir", "papers/%s_images/" % key)
    # The paper HTML file lives inside papers/, so the <img src> must be
    # relative to that directory. The manifest stores image_dir as
    # "papers/<KEY>_images/" (relative to the output root), which would
    # resolve to papers/papers/<KEY>_images/ in the browser. Strip a leading
    # "papers/" prefix so the src becomes "<KEY>_images/..." — correct from
    # the HTML's own location.
    if img_dir.startswith("papers/"):
        img_dir = img_dir[len("papers/"):]
    cards = []
    for fig in figures:
        fname = _common.html_escape(fig.get("filename", ""))
        page = _common.html_escape(str(fig.get("page", "")))
        w = fig.get("width", 0)
        h = fig.get("height", 0)
        cards.append(
            '<div class="figure-card">'
            '<img src="%s%s" alt="Figure p.%s" loading="lazy">'
            '<div class="figure-meta"><span>p.%s</span><span>%s×%s</span></div>'
            '</div>'
            % (img_dir, fname, page, page, w, h)
        )
    return '<div class="figures-grid">' + "".join(cards) + "</div>"


def render_sections(sections, paper_key=None):
    """Render the per-section summary + analysis module.

    `sections` is a list of {heading, page, level, summary, analysis,
    synthetic?} loaded from papers/<KEY>.sections.json (edits override at
    render time). Returns HTML for the 'Section-by-section' module.

    Display only numbering present in the source heading. Unnumbered sections
    such as Abstract remain unnumbered; never invent a new 1,2,3 sequence.
    """
    if not sections:
        return ('<div style="color:var(--ink-faint);font-style:italic;font-size:14px;">'
                '尚未生成分章节分析。运行 extract_sections.py 后由 LLM 撰写各节总结与研究关联。</div>')
    # Backfill source numbers for older sections.json files. The extractor
    # stores standalone PDF number lines in section_text.json; pair each such
    # number with the next titled section for backward compatibility.
    source_numbers = {}
    try:
        key = paper_key
        if key:
            raw = json.loads((_common.PAPERS_DIR / (key + ".section_text.json")).read_text(encoding="utf-8"))
            pending = None
            for item in raw.get("sections", []):
                h = str(item.get("heading", "")).strip()
                if item.get("number"):
                    source_numbers[h] = str(item["number"])
                if re.match(r"^\d+(?:\.\d+)*\.?$", h):
                    pending = h.rstrip(".")
                elif pending:
                    source_numbers[h] = pending
                    pending = None
    except (OSError, json.JSONDecodeError):
        pass
    prepared = []
    seen_numbers = {}
    for source_index, item in enumerate(sections):
        s = dict(item)
        raw = str(s.get("heading", "")).strip()
        if re.match(r"^\d+(?:\.\d+)*\.?$", raw):
            continue
        match = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+(.+)$", raw)
        number = (str(s.get("number", "")).strip() or
                  (match.group(1) if match else "") or
                  source_numbers.get(raw, ""))
        number = number.rstrip(".")
        s["_source_index"] = source_index
        s["_number"] = number
        if number:
            seen_numbers.setdefault(number, []).append(source_index)
        prepared.append(s)
    for number, indexes in seen_numbers.items():
        if len(indexes) > 1:
            sys.stderr.write("WARNING: %s has duplicate section number %s at positions %s.\n"
                             % (paper_key or "paper", number, indexes))
    all_numbers = set(seen_numbers)
    for number in sorted(all_numbers):
        parts = number.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            if parent not in all_numbers:
                sys.stderr.write("WARNING: %s has subsection %s without parent %s.\n"
                                 % (paper_key or "paper", number, parent))
    first_numbered = next((x["_source_index"] for x in prepared if x["_number"]), None)
    def section_key(s):
        if s["_number"]:
            return (1, tuple(int(x) for x in s["_number"].split(".")))
        # Keep unnumbered front matter (Abstract, etc.) in source order.
        if first_numbered is None or s["_source_index"] < first_numbered:
            return (0, s["_source_index"])
        return (2, s["_source_index"])
    prepared.sort(key=section_key)
    cards = []
    for i, s in enumerate(prepared):
        lvl = int(s.get("level", 2))
        raw_heading = str(s.get("heading", "")).strip()
        # A numeric-only heading is an extraction artifact. Do not render a
        # card whose title is merely "4.1" or "4.2".
        if re.match(r"^\d+(?:\.\d+)*\.?$", raw_heading):
            continue
        number_match = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+(.+)$", raw_heading)
        source_number = s.get("_number", "")
        display_heading = number_match.group(2) if number_match else raw_heading
        heading = _common.html_escape(display_heading)
        page = _common.html_escape(str(s.get("page", "")))
        summary = render_prose(s.get("summary", ""))
        analysis = render_prose(s.get("analysis", ""))
        syn_tag = (' <span class="sec-synthetic" title="该标题为根据正文结构补入的章节标签">合成</span>'
                   if s.get("synthetic") else "")
        lvl_cls = " lvl3" if lvl >= 3 else ""
        syn_attr = ' data-synthetic="1"' if s.get("synthetic") else ""

        disp_num = _common.html_escape(source_number)

        cards.append(
            '<section class="sec-card%s" data-index="%d" data-num="%s" data-heading="%s" data-page="%s"%s>'
            '<div class="sec-head"><span class="sec-num">%s</span>'
            '<h3>%s%s</h3><span class="sec-page">p.%s</span></div>'
            '<div class="sec-body">'
            '<div class="sec-label">本节总结</div>'
            '<div class="field-text sec-summary editable" contenteditable="true" '
            'data-placeholder="本节讲了什么…">%s</div>'
            '<div class="sec-label sec-label-analysis">研究关联与分析</div>'
            '<div class="field-text sec-analysis editable" contenteditable="true" '
            'data-placeholder="与牙科基准的关联…">%s</div>'
            '</div></section>'
            % (lvl_cls, i, disp_num, heading, page, syn_attr, disp_num, heading, syn_tag, page, summary, analysis)
        )
    return '<div class="sections-list">' + "".join(cards) + "</div>"


def build(key, summary_file=None):
    """Build the HTML for a paper. Returns the HTML string."""
    _common.validate_paper_key(key)
    manifest = _common.load_manifest()
    paper = None
    for p in manifest.get("papers", []):
        if p.get("zotero_key") == key:
            paper = p
            break
    if not paper:
        sys.stderr.write("Error: paper %s not found in manifest.\n" % key)
        sys.exit(2)

    meta = paper.get("metadata", {})
    collections = paper.get("collections", [])
    tags = paper.get("tags", [])
    annotations_path = _common.PAPERS_DIR / (key + ".annotations.json")
    annotations = []
    if annotations_path.exists():
        try:
            ann_data = json.loads(annotations_path.read_text(encoding="utf-8"))
            annotations = ann_data.get("annotations", [])
        except (json.JSONDecodeError, OSError):
            pass

    # Summary source: --summary-file > papers/<KEY>.summary.json
    summary = {}
    if summary_file:
        summary = json.loads(Path(summary_file).read_text(encoding="utf-8"))
    else:
        sp = _common.PAPERS_DIR / (key + ".summary.json")
        if sp.exists():
            try:
                summary = json.loads(sp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                summary = {}

    # Edits override summary if present.
    edits = {}
    ep = _common.PAPERS_DIR / (key + ".edits.json")
    if ep.exists():
        try:
            edits = json.loads(ep.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            edits = {}

    # Per-section summary + analysis (LLM-generated).
    sections_data = {"sections": []}
    sp_sec = _common.PAPERS_DIR / (key + ".sections.json")
    if sp_sec.exists():
        try:
            sections_data = json.loads(sp_sec.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            sections_data = {"sections": []}
    # edits.json sections (browser-synced) override the LLM file
    if isinstance(edits.get("sections"), list) and edits["sections"]:
        sections_data["sections"] = edits["sections"]
    if not sections_data.get("sections"):
        text_source = _common.PAPERS_DIR / (key + ".section_text.json")
        if text_source.exists():
            sys.stderr.write(
                "WARNING: %s has extracted body text but no sections.json; "
                "section-by-section analysis was not generated.\n" % key
            )
        else:
            sys.stderr.write(
                "WARNING: %s has no section_text.json; full-text extraction "
                "or section analysis is missing.\n" % key
            )

    def pick(field, default=""):
        return edits.get(field, summary.get(field, default))

    # The merged object injected into the page (edits win, fall back to summary).
    # Schema v3 is evidence-aware and paper-type driven. Keep legacy display
    # slots as compact views so existing HTML templates remain compatible.
    initial = {}
    initial["objective"] = pick("one_sentence_summary", pick("objective", ""))
    initial["problem_landscape"] = pick("background_and_gap", pick("problem_landscape", ""))
    initial["approach"] = pick("method_or_design", pick("approach", ""))
    initial["impact"] = pick("contribution", pick("impact", ""))
    initial["risks"] = pick("limitations_and_threats", pick("risks", []))
    initial["cost"] = pick("reproduction_conditions", pick("cost", ""))
    results = pick("results_or_claims", pick("experiments_results", ""))
    benchmark = pick("benchmark_or_dataset_details", "")
    initial["experiments_results"] = results + (("\n\n" + benchmark) if benchmark else "")
    initial["relevance_to_my_work"] = pick("relevance_to_my_work", "")
    initial["custom_notes"] = pick("custom_notes", "")
    for f in ["paper_type", "keywords", "research_question", "data_or_materials",
              "interpretation", "evidence_map", "uncertainties", "open_questions"]:
        initial[f] = pick(f, [] if f in ("paper_type", "keywords", "evidence_map", "uncertainties", "open_questions") else "")
    initial["key_quotes"] = pick("key_quotes", [])
    initial["module_notes"] = pick("module_notes", {})
    initial["schema_version"] = summary.get("schema_version", 3)
    initial["zotero_key"] = key
    initial["sections"] = sections_data.get("sections", [])
    initial["generated_at"] = summary.get("generated_at", _common.now_iso())
    # Bump on every build. The page's load logic compares this against the
    # localStorage snapshot; a mismatch (stale/older sync) discards the
    # stale copy in favour of the freshly-built embedded data, so fixes always
    # take effect on reload without manually clearing localStorage.
    initial["built_at"] = _common.now_iso()

    # Status: edits.json status wins over manifest status (browser-synced).
    status = edits.get("status") or paper.get("status", "reading")

    # DOI link
    doi = meta.get("DOI", "") or ""
    if doi:
        doi_link = '<a href="https://doi.org/%s" target="_blank" rel="noopener">%s</a>' % (
            _common.html_escape(doi), _common.html_escape(doi)
        )
    else:
        doi_link = '<span style="color:var(--ink-faint);">—</span>'

    collections_str = ", ".join(
        _common.html_escape(c.get("name", "")) for c in collections
    ) or "Unfiled"

    # First-call config (language / default accent / Zotero connection).
    cfg = _common.load_config()
    default_accent = cfg["default_accent"]
    zotero_mode = "on" if cfg["connect_zotero"] else "off"

    replacements = {
        "__DEFAULT_ACCENT__": default_accent,
        "__ZOTERO_MODE__": zotero_mode,
        "__TITLE__": _common.html_escape(meta.get("title", "(untitled)")),
        "__AUTHORS__": _common.html_escape(format_authors(meta.get("creators", []))),
        "__YEAR__": _common.html_escape(str(meta.get("publicationYear", ""))),
        "__VENUE__": _common.html_escape(meta.get("venue", "")),
        "__DOI__": _common.html_escape(doi),
        "__DOI_LINK__": doi_link,
        "__ZOTERO_KEY__": _common.html_escape(key),
        "__COLLECTIONS__": collections_str,
        "__ABSTRACT__": _common.html_escape(meta.get("abstractNote", "")),
        "__STATUS__": _common.html_escape(status),
        "__KEYWORDS_ROW__": paper_keywords(meta),
        # Heilmeier Q1-Q7 (long-form fields → multi-paragraph <p> blocks)
        "__OBJECTIVE__": render_prose(initial["objective"]),
        "__PROBLEM_LANDSCAPE__": render_prose(initial["problem_landscape"]),
        "__APPROACH__": render_prose(initial["approach"]),
        "__IMPACT__": render_prose(initial["impact"]),
        "__RISKS_HTML__": render_list(initial["risks"]),
        "__COST__": render_prose(initial["cost"]),
        "__EXPERIMENTS_RESULTS__": render_prose(initial["experiments_results"]),
        "__RELEVANCE__": render_prose(initial["relevance_to_my_work"]),
        "__KEY_QUOTES_HTML__": render_quotes(initial["key_quotes"]),
        "__FIGURES_HTML__": render_figures(key),
        "__SECTIONS_HTML__": render_sections(initial["sections"], key),
        "__OPEN_QUESTIONS_HTML__": render_list(initial["open_questions"]),
        "__CUSTOM_NOTES__": render_prose(initial["custom_notes"]),
        "__HIGHLIGHTS_HTML__": render_highlights(annotations),
        "__NOTES_HTML__": render_notes([]),
        "__ANNOTATION_COUNT__": str(paper.get("annotation_count", len(annotations))),
        "__READING_TIME__": format_reading_time(paper.get("reading_time_minutes", 0)),
        "__INITIAL_EDITS_JSON__": _safe_json_for_script(initial),
        "__GENERATED_AT__": _common.now_iso(),
    }

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = _common.apply_placeholders(template, replacements, PAPER_PLACEHOLDER_REGISTRY)
    return html


def main():
    ap = argparse.ArgumentParser(description="Render a paper's close-reading HTML.")
    ap.add_argument("--key", required=True, help="Zotero key of the paper")
    ap.add_argument("--summary-file", help="Override summary JSON file path")
    ap.add_argument("--stdout", action="store_true", help="Print HTML instead of writing")
    args = ap.parse_args()

    try:
        html = build(args.key, args.summary_file)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1

    if args.stdout:
        sys.stdout.write(html)
    else:
        _common.ensure_output_dirs()
        _common.copy_fonts()
        out = _common.PAPERS_DIR / (args.key + ".html")
        out.write_text(html, encoding="utf-8")
        sys.stderr.write("Wrote %s\n" % out)


if __name__ == "__main__":
    raise SystemExit(main())
