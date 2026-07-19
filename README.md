<div align="center">

# paper-notes

[![GitHub stars](https://img.shields.io/github/stars/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/network/members)
[![GitHub issues](https://img.shields.io/github/issues/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/issues)
[![License](https://img.shields.io/github/license/ZinSheng/paper-notes?style=flat-square)](LICENSE)

**A paper close-reading skill that turns every paper into research sense.**

*Zotero sync · Paper overview · Deep reading · Editable notes · Reading dashboard*

[English](README.md) · [中文](README_ZH.md)

</div>

---

> **We Build Your Research Sense** — turn every paper into intuition you can use in your own research.

`paper-notes` is an AI-agent skill for close-reading research papers. It syncs collections, paper metadata, PDF highlights, and notes from Zotero; distils each paper's structure and key findings from its text; then turns section-by-section reading notes, relevance to your work, and reading history into editable local knowledge assets.

## What you get

- **One-click Zotero sync**: bring collections, paper metadata, PDF highlights, and notes from your existing library straight into the workflow.
- **A paper at a glance**: surface the key points, argument structure, and core conclusions before you decide where to go deep.
- **Section-by-section deep reading**: generate reading notes alongside the source text, giving long papers a clear path through close reading.
- **Relevance to your research**: relate a paper to your questions, methods, and direction, so reading compounds into research sense.
- **A complete reading view**: the dashboard groups papers by Zotero collection and brings together lists, tag filters, reading records, and a historical heatmap.
- **Notes that stay yours**: edit every reading page directly in the browser, save automatically, and sync `.edits.json` back to a local folder.

## Features

- **Evidence-first text pipeline**: extracts PDF body text to `section_text.json`; failed extraction prevents full-note generation. The model reads extracted text, never PDF images.
- **Structured close-reading outputs**: creates paper overviews, section analyses, and deep-reading notes. `sections.json` preserves source numbering and validates parent/child order.
- **Markdown + LaTeX**: every note field supports rich text and live MathJax formula rendering.
- **Figure extraction + Lightbox**: uses PyMuPDF to extract embedded PDF figures, filter tiny or low-resolution images, and inspect them at native resolution.
- **Editable, exportable, reproducible**: browser editing, localStorage autosave, JSON import/export, and folder sync; manifests, summaries, sections, annotations, and edits are stored separately.
- **Personalized reading experience**: switch between rose, green, and blue accents, with preferences remembered per paper.
- **Fully optional Zotero connection**: upload a local PDF to generate a reading page without Zotero; Zotero-dependent dashboard modules hide automatically.

## Installation

```bash
git clone https://github.com/ZinSheng/paper-notes.git
cd paper-notes
```

Copy `skills/paper-notes/` into a skill directory supported by your AI agent runtime:

```bash
cp -R skills/paper-notes <your-skills-directory>/paper-notes
```

When using Zotero, set `ZOTERO_API_KEY` and `ZOTERO_USER_ID`; figure extraction requires PyMuPDF.

## Quick start

```bash
cd <your project directory>
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py init \
  --language en --accent blue --connect-zotero yes
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py add --key <ZOTERO_KEY>
python3 .codex/skills/paper-notes/scripts/build_dashboard.py
```

Outputs are written to `outputs/paper-notes/` under the current working directory.

## License

Provided as-is for personal learning and use.
