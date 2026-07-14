<div align="center">

# paper-notes

[![GitHub stars](https://img.shields.io/github/stars/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/network/members)
[![GitHub issues](https://img.shields.io/github/issues/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/issues)
[![License](https://img.shields.io/github/license/ZinSheng/paper-notes?style=flat-square)](LICENSE)

**A reusable, evidence-first workflow for close-reading research papers.**

*Zotero · PDF annotations · Editable HTML notes · Reading dashboard*

[English](README.md) · [中文](README_ZH.md)

</div>

---

> **We Build Your Research Sense**

A Zotero-based paper close-reading skill. It maintains a curated reading list, pulls PDF highlights and notes, extracts searchable body text with Python, renders editable HTML pages, and builds a reading dashboard with a historical calendar. The LLM reads extracted text only; PDF images are never used as model input.

## Features

- **Zotero sync**: fetches paper metadata, PDF highlights, and notes through the companion `zotero` skill.
- **Editable HTML reading pages**: generates evidence-aware structured summaries with Markdown and LaTeX support.
- **Full-text pipeline**: automatically creates `section_text.json`; failed extraction blocks complete note generation.
- **Section analysis**: creates `sections.json`, preserves source numbering, and validates parent/child ordering.
- **Reading dashboard**: groups papers by Zotero collection with tag filters and a historical heatmap.
- **Three theme accents**: rose, green, and blue, with persistent switching.
- **Zotero-free mode**: supports manual PDF upload and hides Zotero-dependent dashboard modules.

## Why use it

- **Evidence-first**: summaries and section analyses use extracted text, metadata, and annotations while separating facts, inferences, and uncertainties.
- **Editable outputs**: generated HTML pages support browser editing, autosave, JSON import/export, and folder sync.
- **Reproducible artifacts**: the manifest, summaries, extracted sections, annotations, and user edits are stored as separate files for backup and versioning.
- **Flexible sources**: connect to Zotero or import local PDFs without Zotero.

## Installation

```bash
git clone https://github.com/ZinSheng/paper-notes.git
cd paper-notes
```

Copy `skills/paper-notes/` into a skill directory supported by your AI agent runtime:

```bash
cp -R skills/paper-notes <your-skills-directory>/paper-notes
```

Prerequisites: set `ZOTERO_API_KEY` and `ZOTERO_USER_ID`; figure extraction requires PyMuPDF.

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
