#!/usr/bin/env python3
"""Extract the section structure of a paper's PDF for close reading.

Reads the LOCAL Zotero PDF (via _common.local_pdf_path) and builds a list of
the paper's own sections (Abstract, Introduction, Results subsections,
Discussion, Methods, ...) using the PDF outline (TOC) as the backbone, then
fills gaps (Abstract / Introduction / Methods are often absent from the NM
inline TOC) with a font/size-based heading scan. For each section it extracts
the raw text so the LLM can write a faithful per-section summary + analysis.

Output: papers/<KEY>.section_text.json
    {
      "zotero_key": "...",
      "generated_at": "...",
      "pdf_source": "local",
      "sections": [
        {"level": 2, "heading": "Abstract", "page": 1,
         "text": "...", "truncated": false},
        ...
      ]
    }

Usage:
    python3 extract_sections.py <KEY> [--pdf-attachment-key <ATT>]

Requires PyMuPDF (fitz). The local PDF is found via ZOTERO_DATA_DIR (default ~/Zotero).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import _common

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.stderr.write("Error: PyMuPDF (fitz) is required. Install it in the venv.\n")
    sys.exit(1)


# Headings that are editorial back-matter, not the paper's scholarly argument.
_BACK_MATTER = {
    "online content", "reporting summary", "ethics", "data availability",
    "code availability", "author contributions", "competing interests",
    "references", "supplementary information", "supplementary",
    "acknowledgements", "acknowledgments", "peer review",
    "additional information", "rights and permissions",
    "publisher's note", "open access", "funding", "brief communication",
    "extended data", "correspondence and requests", "reprints and permissions",
    "methods only", "article",
}

# Standard top-level sections we want even when the inline TOC omits them.
_STANDARD = ["Abstract", "Introduction", "Methods", "Materials and methods",
             "Results", "Discussion", "Conclusions", "Conclusion"]

# Substrings that mark a figure/table caption entry in the TOC (noise).
_FIG_TBL_NOISE = ("fig.", "table", "extended data")

# Single-letter figure panel labels (a, b, c …) that are not headings.
_PANEL_LABELS = set("abcdefghijklmnopqrstuvwxyz")


def _is_noise(title):
    t = _norm(title)
    if len(t) <= 1 or t in _PANEL_LABELS:
        return True
    # exact back-matter match OR back-matter token is a prefix
    # (e.g. "publisher's note …", "supplementary information …")
    for bm in _BACK_MATTER:
        if t == bm or t.startswith(bm + " ") or t.startswith(bm):
            return True
    # figure / table caption entries from the TOC
    for n in _FIG_TBL_NOISE:
        if t.startswith(n) or n in t:
            return True
    return False


def _norm(s):
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s.strip().lower().rstrip("."))


def _detect_standard_sections(doc):
    """Scan pages for standalone heading lines matching STANDARD section names.

    Returns list of (heading, page) using font-size/bold heuristics. Used to
    fill gaps the inline TOC leaves (Abstract / Introduction / Methods).
    """
    found = []
    seen = set()
    for pi in range(doc.page_count):
        page = doc[pi]
        d = page.get_text("dict")
        sizes = [s["size"] for b in d["blocks"] for l in b.get("lines", [])
                 for s in l["spans"]]
        if not sizes:
            continue
        max_size = max(sizes)
        threshold = max(9.0, max_size * 0.92)
        for b in d["blocks"]:
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                txt = " ".join(s["text"] for s in spans).strip()
                if not txt or len(txt) > 70:
                    continue
                match = None
                for name in _STANDARD:
                    nt = _norm(name)
                    if _norm(txt) == nt or _norm(txt).startswith(nt + " "):
                        match = name
                        break
                if not match:
                    continue
                prominent = any(s["size"] >= threshold or (s.get("flags", 0) & 16)
                                for s in spans)
                if not prominent:
                    continue
                key = (match, pi)
                if key in seen:
                    continue
                seen.add(key)
                found.append((match, pi + 1))
    return found


def _detect_bold_subheadings(doc, pages):
    """Scan the given page range for bold, short, standalone subheadings.

    Used to catch Methods subsections ("Study approval…", "MedQA scoring")
    that the inline TOC omits. Scoped to the Methods region so it does not
    sweep up figure-caption / table-cell bold text on later pages.
    `pages` is a list of 0-based page indices. Returns list of (heading, page).
    """
    found = []
    seen = set()
    for pi in pages:
        if pi < 0 or pi >= doc.page_count:
            continue
        d = doc[pi].get_text("dict")
        for b in d["blocks"]:
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                txt = " ".join(s["text"] for s in spans).strip()
                if not txt or not (3 <= len(txt) <= 70):
                    continue
                if _is_noise(txt):
                    continue
                # running page numbers, percentages, axis labels (25%, mean=4.7)
                # Standalone section numbers (e.g. "4.1", "4.2") are
                # layout artifacts, not headings. Keep numbered headings only
                # when a title follows the number on the same line.
                if txt.isdigit() or re.match(r"^\d+(?:\.\d+)*\.?$", txt) or re.match(r"^\d+[\d,\s%]*$", txt) or "=" in txt:
                    continue
                # author / name lists contain commas — real headings here don't
                if "," in txt:
                    continue
                bold = any(s.get("flags", 0) & 16 for s in spans)
                if not bold:
                    continue
                key = (_norm(txt), pi)
                if key in seen:
                    continue
                seen.add(key)
                found.append((txt, pi + 1))
    return found


def _extract_section_text(doc, start_page_1based, end_page_1based):
    """Return text from start_page to end_page (inclusive), 1-based."""
    lo = max(0, start_page_1based - 1)
    hi = min(doc.page_count - 1, end_page_1based - 1)
    chunks = []
    for pi in range(lo, hi + 1):
        chunks.append(doc[pi].get_text("text"))
    text = "\n".join(chunks).strip()
    return text


def extract(key, attachment_key=None, pdf_path=None):
    if pdf_path:
        pdf = str(Path(pdf_path).expanduser())
    elif attachment_key:
        pdf = _common.local_pdf_path(attachment_key)
    else:
        # try to resolve from manifest
        man = _common.load_manifest()
        pdf = None
        for p in man.get("papers", []):
            if p.get("zotero_key") == key:
                att = p.get("pdf_attachment_key")
                if att:
                    pdf = _common.local_pdf_path(att)
                break
    if not pdf or not Path(pdf).is_file():
        return {"zotero_key": key, "sections": [],
                "note": "Local PDF not found (set ZOTERO_DATA_DIR / pdf-attachment-key)."}

    doc = fitz.open(pdf)

    # 1) TOC-derived candidates (level >= 2, non-noise)
    toc = doc.get_toc()
    toc_secs = []
    for level, title, page in toc:
        if level < 2:
            continue
        if _is_noise(title):
            continue
        toc_secs.append({"level": min(level, 3), "heading": title.strip(),
                         "page": int(page)})

    # 2) detected standard sections (Abstract/Intro/Methods/...)
    std = _detect_standard_sections(doc)

    # 3) merge TOC + standard first, so we can locate the Methods region
    merged = {}
    for s in toc_secs:
        merged[(_norm(s["heading"]), s["page"])] = s
    for heading, page in std:
        dup = any(abs(pg - page) <= 1 and h == _norm(heading)
                  for (h, pg) in merged.keys())
        if dup:
            continue
        merged[(_norm(heading), page)] = {
            "level": 2, "heading": heading, "page": page}

    # locate Methods page to scope the bold-subheading scan
    methods_page = None
    for s in merged.values():
        if _norm(s["heading"]) in ("methods", "materials and methods"):
            methods_page = s["page"]
            break
    # Only run the bold-subheading scan for papers whose TOC is sparse
    # (Brief Communications) — full articles already expose their real
    # subsections via the TOC, and scanning Methods there explodes into
    # bullet points / table cells.
    toc_sub_count = sum(1 for s in toc_secs if s["level"] >= 3)
    if methods_page is not None and toc_sub_count < 4:
        m0 = methods_page - 1  # 0-based
        scan_pages = list(range(max(1, m0), min(doc.page_count, m0 + 2)))
        bold_subs = _detect_bold_subheadings(doc, scan_pages)
        for heading, page in bold_subs:
            dup = any(abs(pg - page) <= 1 and h == _norm(heading)
                      for (h, pg) in merged.keys())
            if dup:
                continue
            merged[(_norm(heading), page)] = {
                "level": 3, "heading": heading, "page": page}

    # 4) sort by page; assign sensible levels
    sections = sorted(merged.values(), key=lambda s: s["page"])
    # Some PDFs place the section number on its own line immediately before
    # the title (for example, "4.1" followed by "Data Curation"). Fold that
    # number into the following section instead of treating it as a title.
    folded = []
    pending_number = None
    for s in sections:
        heading = str(s.get("heading", "")).strip()
        if re.match(r"^\d+(?:\.\d+)*\.?$", heading):
            pending_number = heading.rstrip(".")
            continue
        if pending_number and not s.get("number"):
            s["number"] = pending_number
        pending_number = None
        folded.append(s)
    sections = folded
    # Recover numbers whose PDF text places the number on the line directly
    # above a TOC-derived title (e.g. "4.1\nData Curation").
    for s in sections:
        if s.get("number"):
            continue
        page_text = doc[max(0, int(s["page"]) - 1)].get_text("text")
        title = re.escape(re.sub(r"\s+", " ", str(s["heading"]).strip()))
        match = re.search(r"(?m)^\s*(\d+(?:\.\d+)*)\s*\n\s*" + title + r"\s*$", page_text)
        if match:
            s["number"] = match.group(1)
    for s in sections:
        h = _norm(s["heading"])
        if h in {_norm(x) for x in _STANDARD}:
            s["level"] = 2
        else:
            s["level"] = max(2, min(s.get("level", 3), 3))

    # 5) ensure Abstract exists at the front
    if not any(_norm(s["heading"]) == "abstract" for s in sections):
        sections.insert(0, {"level": 2, "heading": "Abstract", "page": 1})

    # 6) Gap-fill: Brief Communications (and similar) often have no explicit
    #    "Results"/"Discussion" header — the main narrative sits between the
    #    abstract and Methods. Insert a "Results and discussion" section there
    #    if no Results/Discussion section already exists and the gap is meaty.
    has_results = any(_norm(s["heading"]) in ("results", "discussion",
                                              "results and discussion")
                      for s in sections)
    if not has_results:
        # find the page where Methods starts (or end of doc)
        methods_page = None
        for s in sections:
            if _norm(s["heading"]) in ("methods", "materials and methods"):
                methods_page = s["page"]
                break
        # abstract page is the first section's page
        abs_page = sections[0]["page"]
        gap_start = abs_page + 1
        gap_end = (methods_page - 1) if methods_page else doc.page_count
        gap_text = _extract_section_text(doc, gap_start, gap_end + 1)
        # only insert if there's a meaningful amount of narrative text
        if len(gap_text.strip()) > 600:
            insert_at = 1
            for i, s in enumerate(sections):
                if s["page"] > abs_page:
                    insert_at = i
                    break
            sections.insert(insert_at, {
                "level": 2, "heading": "Results and discussion",
                "page": gap_start, "synthetic": True})

    # 7) extract text per section (page range = this.page .. next.page-1)
    MAX_CHARS = 8000
    for i, s in enumerate(sections):
        end_p = sections[i + 1]["page"] if i + 1 < len(sections) else doc.page_count
        text = _extract_section_text(doc, s["page"], end_p)
        truncated = len(text) > MAX_CHARS
        if truncated:
            text = text[:MAX_CHARS] + "\n…[truncated]"
        s["text"] = text
        s["truncated"] = truncated

    doc.close()
    return {
        "zotero_key": key,
        "generated_at": _common.now_iso(),
        "pdf_source": "local",
        "sections": sections,
    }


def main():
    ap = argparse.ArgumentParser(description="Extract paper section structure.")
    ap.add_argument("--key", required=True)
    ap.add_argument("--pdf-attachment-key", help="Zotero PDF attachment key")
    ap.add_argument("--pdf", help="Explicit local PDF path (for manual imports)")
    args = ap.parse_args()
    try:
        _common.validate_paper_key(args.key)
    except ValueError as exc:
        ap.error(str(exc))

    data = extract(args.key, args.pdf_attachment_key, args.pdf)
    _common.ensure_output_dirs()
    out = _common.PAPERS_DIR / (args.key + ".section_text.json")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(data.get("sections", []))
    sys.stderr.write("Wrote %s (%d sections)\n" % (out, n))


if __name__ == "__main__":
    main()
