#!/usr/bin/env python3
"""Extract important figures from a paper's PDF.

Downloads the PDF via the Zotero file API and extracts embedded images with
PyMuPDF (fitz), filtering out tiny icons/logos and deduplicating reused images.
Saves qualifying figures to papers/<KEY>_images/ and writes a manifest.json
that build_paper_html.py reads to render the Figures section.

This script REQUIRES PyMuPDF. `manage_reading_list.py` resolves a
PyMuPDF-capable interpreter automatically (env override
$LITERATURE_READER_FIGURE_PYTHON, else a managed venv, else the
current interpreter). To run it directly:
    python3 extract_figures.py <PAPER_KEY>

Usage:
    python3 extract_figures.py <PAPER_KEY>
    python3 extract_figures.py <PAPER_KEY> --pdf-attachment-key WXYZ1234
    python3 extract_figures.py <PAPER_KEY> --max 8

Output (stdout JSON):
    {zotero_key, count, figures: [{index, filename, page, width, height}]}
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# PyMuPDF import — fail clearly if not run in the managed venv.
try:
    import fitz  # PyMuPDF
except ImportError:
    sys.stderr.write(
        "Error: PyMuPDF (fitz) not found. Install it into the current interpreter\n"
        "(pip install pymupdf) or set LITERATURE_READER_FIGURE_PYTHON to a "
        "PyMuPDF-capable interpreter.\n"
    )
    sys.exit(1)

import _common
import fetch_annotations  # reuse find_pdf_attachment

MIN_WIDTH = 150      # px — skip icons/logos
MIN_HEIGHT = 150
MIN_BYTES = 5 * 1024  # 5KB — skip tiny decorative images
DEFAULT_MAX = 8


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def extract(key, api_key=None, prefix=None, pdf_attachment_key=None,
             max_figures=DEFAULT_MAX, pdf_bytes=None):
    """Extract qualifying figures from a paper's PDF.

    Two input modes:
      - Zotero mode: pass api_key + prefix (and optionally
        pdf_attachment_key); the PDF is downloaded via the Zotero file API
        with a local-storage fallback.
      - Local mode: pass pdf_bytes directly (e.g. for manual add without a
        Zotero connection). api_key/prefix are ignored in this case.

    Returns the manifest dict (with 'count' + 'figures').
    """
    # 1. Resolve PDF bytes.
    pdf_source = "local:bytes"
    if pdf_bytes is None:
        # Zotero mode — look up the attachment key if needed.
        if not pdf_attachment_key:
            pdf_attachment_key = fetch_annotations.find_pdf_attachment(
                key, api_key, prefix
            )
        if not pdf_attachment_key:
            return {"zotero_key": key, "count": 0, "figures": [],
                    "note": "No PDF attachment found."}

        # 2. Obtain PDF bytes — try Web API first, fall back to local Zotero
        #    storage (files often aren't synced to the cloud; API returns 404).
        pdf_bytes = None
        pdf_source = "api"
        try:
            pdf_bytes = _common.api_get_bytes(
                "/items/%s/file" % pdf_attachment_key, api_key
            )
        except Exception as e:
            sys.stderr.write(
                "Web API PDF download failed (%s); trying local Zotero storage...\n"
                % e
            )
            local_path = _common.local_pdf_path(pdf_attachment_key)
            if local_path:
                try:
                    with open(local_path, "rb") as f:
                        pdf_bytes = f.read()
                    pdf_source = "local:" + local_path
                    sys.stderr.write("Loaded PDF from local storage: %s\n" % local_path)
                except OSError as oe:
                    sys.stderr.write("Local read also failed: %s\n" % oe)
        if not pdf_bytes or len(pdf_bytes) < 1000:
            return {"zotero_key": key, "count": 0, "figures": [],
                    "note": "PDF unavailable (Web API + local fallback both failed)."}

    # 3. Open with PyMuPDF and walk pages for embedded images.
    out_dir = _common.PAPERS_DIR / (key + "_images")
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    seen_hashes = set()      # dedup by content hash
    seen_xrefs = set()       # dedup by xref (same image reused)
    figures = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        try:
            images = page.get_images(full=True)
        except Exception:
            images = []
        for img in images:
            xref = img[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            if not info or not info.get("image"):
                continue
            img_bytes = info["image"]
            w = info.get("width", 0)
            h = info.get("height", 0)
            if w < MIN_WIDTH or h < MIN_HEIGHT:
                continue
            if len(img_bytes) < MIN_BYTES:
                continue
            # dedup by content hash (same image at different xrefs)
            hsh = _sha256(img_bytes)
            if hsh in seen_hashes:
                continue
            seen_hashes.add(hsh)

            ext = info.get("ext", "png")
            idx = len(figures) + 1
            filename = "%s_fig%02d.%s" % (key, idx, ext)
            (out_dir / filename).write_bytes(img_bytes)
            figures.append({
                "index": idx,
                "filename": filename,
                "page": page_num + 1,
                "width": w,
                "height": h,
                "bytes": len(img_bytes),
            })
            if len(figures) >= max_figures:
                break
        if len(figures) >= max_figures:
            break

    doc.close()

    # 4. Write manifest.json for build_paper_html.py.
    manifest = {
        "zotero_key": key,
        "pdf_attachment_key": pdf_attachment_key,
        "pdf_source": pdf_source,
        "count": len(figures),
        "figures": figures,
        "image_dir": "papers/%s_images/" % key,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main():
    ap = argparse.ArgumentParser(description="Extract figures from a paper's PDF.")
    ap.add_argument("paper_key", help="Zotero item key of the paper")
    ap.add_argument("--pdf-attachment-key", help="PDF attachment key (skip lookup)")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX,
                    help="Max figures to extract (default %d)" % DEFAULT_MAX)
    args = ap.parse_args()
    try:
        _common.validate_paper_key(args.paper_key)
    except ValueError as exc:
        ap.error(str(exc))

    api_key, prefix = _common.get_zotero_config()
    result = extract(args.paper_key, api_key, prefix,
                      args.pdf_attachment_key, args.max)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
