---
name: paper-notes
description: Manage a personal close-reading workflow with Zotero or local PDFs, editable HTML and/or Obsidian Markdown paper notes, reading dashboards, structured research-project management, research-aware relevance analysis, annotation refresh, and bidirectional edit sync. Use when the user wants to curate a reading list, turn papers or highlights into close-reading notes, manage research directions, review reading history, or maintain HTML/Obsidian literature notes.
---

# paper-notes

Manage a personal close-reading workflow built on Zotero or local PDFs. Maintain a curated manifest, fetch highlights and notes, render editable HTML, Obsidian Markdown, or both from canonical JSON, and aggregate papers with structured research-project context.

## Permissions & Data Flow

This skill reads and writes only the user's own literature data. It does not exfiltrate credentials, cookies, or personal data.

- **External service — Zotero Web API** (`api.zotero.org`): GET-only access to the user's own Zotero library (metadata, PDF annotations, notes, collections) using the user's own `ZOTERO_API_KEY`. No POST/PUT/DELETE; no third-party endpoints.
- **Local file reads**: reads PDFs and Zotero's full-text cache from the local Zotero storage directory (`~/Zotero/storage/...` by default, overridable via `ZOTERO_DATA_DIR`); reads `~/.zshrc`, `~/.bashrc`, `~/.zprofile`, `~/.bash_profile` only to recover `ZOTERO_*` environment variables when the shell did not export them.
- **Local file writes**: all outputs go under `outputs/paper-notes/` in the working directory (manifest, HTML pages, JSON summaries, extracted figures/sections). No writes outside this directory.
- **Browser capability**: the generated paper page offers a "Sync Folder" button using the File System Access API (`showDirectoryPicker`) to persist in-browser edits back to `papers/<KEY>.edits.json`. Granted only on an explicit user gesture; non-Chromium browsers fall back to manual Export/Import JSON.
- **Runtime dependencies**: figure/section extraction uses PyMuPDF (`pip install pymupdf`) if available; generated pages load MathJax v3 from the jsDelivr CDN for LaTeX rendering. Both are optional — the skill degrades gracefully without them.
- **No hidden behavior**: no `eval`/`exec`/`os.system`, no shell injection (`subprocess` is always called with list args, never `shell=True`), no account automation, no telemetry.

## Source & Attribution

- Original, self-authored skill (`agent_created: true`). All bundled code (Python scripts, HTML templates, CSS) is the author's own work.
- No third-party source code is bundled. Self-hosted web fonts ship in `assets/fonts/` for offline rendering.
- No content scraping, plagiarism, or reposting of others' skills.

## When to use

- "add paper X to my reading list" / "把 X 加入精读" — fetch + render a paper.
- "show my reading dashboard" / "阅读仪表盘" — build dashboard.html.
- "refresh paper X" / "刷新 X 的标注" — re-fetch annotations after re-reading.
- "mark X done" / "archive X" — change reading status.
- "remove X" — delete from the reading list.

## Prerequisites

- `ZOTERO_API_KEY` and `ZOTERO_USER_ID` environment variables set (standard Zotero Web API credentials). Create a key at https://www.zotero.org/settings/keys/new.
- No companion skill is required. This skill bundles a read-only `scripts/zotero.py` that supports the `search` and `get` operations used by the workflow.

If credentials are missing or the key is invalid (403 / "Key not found"), tell the user and link the key-creation page. See `references/troubleshooting.md`.

## First-run initialization (IMPORTANT)

On the **first** invocation of this skill in a project (detect by: `outputs/paper-notes/litreader.config.json` does **not** exist, or `load_config()["initialized"]` is false), ask the user five setup questions **before** doing any work, then persist the answers with:

```
python3 <paper-notes-skill-dir>/scripts/manage_reading_list.py init \
  --language zh|en \
  --accent rose|green|blue \
  --connect-zotero yes|no \
  --output html|obsidian|both \
  --research-context yes|no
```

The five questions, and what each controls:

1. **Preferred language** (`--language`) — the language the summary + UI copy should default to. zh = Chinese (default), en = English. The LLM summary procedure then defaults to that language instead of always Chinese.
2. **Default page color / accent** (`--accent`) — rose / green / blue. Stored as `default_accent` and injected into **every** generated page's `<body data-accent>` + the topbar switcher's initial selection, so newly built pages show the chosen color on first open (before any per-page localStorage override).
3. **Connect to Zotero?** (`--connect-zotero`) — the most consequential switch:
   - **yes** (default): normal flow — fetch metadata/annotations via the `zotero.py` CLI, derive the reading calendar, extract figures from the cloud/local PDF, and render the Zotero-only modules. The Obsidian dashboard shows only the aggregate SVG heatmap, never a recent-reading or per-day paper list.
   - **no**: the skill runs **Zotero-free**. The dashboard's heatmap/timeline are hidden (`body[data-zotero="off"]`), the paper page hides the two Zotero-only submodules, and papers are added by **manual upload** instead of Zotero fetch:
     ```
     python3 <paper-notes-skill-dir>/scripts/manage_reading_list.py add --manual \
       --pdf /path/to/paper.pdf --title "..." --authors "..." \
       --year 2024 --venue "..." --doi 10.x/y --abstract "..."
     ```
     This reads the local PDF, extracts figures locally (PyMuPDF, venv python), writes an empty summary template, and renders the page. The key is synthetic (`local-<hash>`). The user later asks the LLM to fill the summary.
4. **Output format** (`--output`) — `html` writes editable web pages, `obsidian` writes a self-contained Markdown vault, and `both` maintains both. Existing configs without this key migrate to `html`.
5. **Use research context?** (`--research-context`) — `yes` makes every future paper add pause before mutation and requires the user to choose one active/paused research project or explicitly choose `none`; `no` skips this question during paper adds and generates general research significance. This preference can later be changed with `manage_reading_list.py settings --research-context yes|no`.

All builders call `_common.load_config()`. HTML builders inject accent/Zotero settings; the output mode selects HTML, Obsidian, or both. On subsequent calls the config exists, so skip the questions.

**Enforced in code:** `manage_reading_list.py add` refuses to run until init has completed — if the config is missing or `initialized` is false it prints `{"ok":false,"error":"not_initialized","next_step":"run_init"}` and exits with code 3 without adding anything. Ask the five questions, run `init`, then retry the add. (`list` / other read commands are not gated.)

## Outputs

All runtime artifacts land in the working directory under `outputs/paper-notes/`:

- `reading-list.json` — the manifest (source of truth for the close-reading set).
- `html/dashboard.html` — the reading dashboard.
- `html/research/<project name>.html` — one read-only HTML detail page per research project; the compact dashboard table links to it.
- `html/papers/<KEY>.html` — one editable page per paper. Its figures and fonts also live under `html/`, making the HTML tree self-contained.
- `papers/<KEY>.summary.json` — the LLM-generated structured summary.
- `papers/<KEY>.edits.json` — the user's exported HTML edits (persists across refresh).
- `papers/<KEY>.annotations.json` — cached PDF annotations + notes.
- `papers/<KEY>.section_text.json` — Python-extracted searchable text grouped by paper section; this is the only full-text input for the LLM.
- `research-projects.json` — canonical structured research projects and per-field timestamps.
- `collection-tree.json` — the last successfully fetched Zotero hierarchy, stored as a versioned cache envelope. A failed fetch never replaces it; Obsidian path migration stops if any selected collection ancestor cannot be resolved.
- `obsidian/Dashboard.md`, `obsidian/Papers/<Collection hierarchy>/<paper title>.md`, `obsidian/Attachments/<Collection hierarchy>/<paper title>/`, `obsidian/Research/<ID>.md` — the self-contained vault when enabled. Paper attachments mirror the paper-note collection/title path; only dashboard-wide assets stay directly under `Attachments/`.

The skill package itself holds no runtime state — everything is reproducible from the manifest + Zotero.

## The bundled `zotero.py` CLI & annotation fetching

This skill's own `scripts/zotero.py` exposes only read-only **search** and **get** commands. It deliberately omits add, update, delete, upload, and other Zotero write operations. `scripts/fetch_annotations.py` separately reads the Zotero 6+ `annotation` itemType (PDF highlights). Annotations live two levels below the paper — paper → PDF attachment → annotations — so `fetch_annotations.py` walks that hierarchy. See `references/annotation_fields.md` for the field mapping and color strategy.

## Commands

| User says | Run |
|---|---|
| add paper by title/DOI | `manage_reading_list.py add --search "..."` or `add --doi 10.x/y` → confirm with user → `add --key <KEY>` |
| add by known key | `manage_reading_list.py add --key <KEY>` |
| show dashboard | `build_dashboard.py` |
| refresh annotations | `manage_reading_list.py refresh --key <KEY>` |
| regenerate summary | `manage_reading_list.py refresh --key <KEY> --regenerate-summary` (then run the summary procedure below) |
| change status | `manage_reading_list.py mark --key <KEY> --status reading\|done\|archived` |
| archive | `manage_reading_list.py archive --key <KEY>` (restore with `restore`) |
| remove | `manage_reading_list.py remove --key <KEY>` (`--keep-edits` preserves user edits) |
| list | `manage_reading_list.py list [--json]` |
| manage research | after a conversational intake and user confirmation, `manage_reading_list.py research add|update|list|archive ...` |
| enable/disable research context prompts | `manage_reading_list.py settings --research-context yes|no` |
| sync editable views | `sync_edits.py [--key <KEY>]` |
| finalize generated notes | `manage_reading_list.py finalize-summary --key <KEY>` |

Resolve `<paper-notes-skill-dir>` to the directory containing this `SKILL.md`. All scripts run with `python3` (e.g. `python3 <paper-notes-skill-dir>/scripts/manage_reading_list.py add --key VNPN6FHT`). The one exception is `extract_figures.py`, which needs PyMuPDF. `manage_reading_list.py` already resolves a PyMuPDF-capable interpreter (env override `LITERATURE_READER_FIGURE_PYTHON`, else a managed venv, else the current interpreter) and invokes it automatically during `add`/`refresh`, so you usually don't call it directly.

## The "manual add" interaction flow (IMPORTANT)

`add` is the primary entrypoint. The user says "把 Lutz 2008 Gender Migration Domestic Work 加入精读". Execute:

1. **Search & confirm** — `python3 <paper-notes-skill-dir>/scripts/zotero.py --json search "Lutz Gender Migration Domestic Work" --limit 5`. If one high-confidence match, show it and wait for yes. If multiple, list the top 5 and ask which. If none, ask the user to add the item in Zotero first. **Never add without confirming the match.**
2. **Resolve research context when enabled** — read `load_config()["use_research_context"]`. When true, list active/paused projects and ask the user to choose one or explicitly choose no project. Then call add with `--research <ID>|none`. Never infer a project from topic similarity. When false, do not ask and omit `--research`. The CLI enforces this before writing any paper files and returns `next_step: repeat_add_with_research` if the choice is missing.
3. **Add** — `manage_reading_list.py add --key <KEY> [--research <ID>|none]`. When Zotero assigns several collections, ask the user which one to use and repeat with `--collection <KEY>`; one collection is automatic and none maps to `Unfiled`. The script fetches source data, writes an empty summary template in `template` state, updates the manifest and dashboard, but deliberately does not create a formal paper page. If PDF text extraction fails, the add stops.
4. **Generate the summary** (when `next_step == "generate_summary"`) — first build a coherent article guide, then follow the evidence-aware schema procedure below.
5. **Finalize** — after both summary and sections JSON are complete, run `manage_reading_list.py finalize-summary --key <KEY>`. This validates them, records canonical field baselines, and first-renders only the enabled outputs.
6. **Report** — after **every** HTML generation or regeneration, explicitly remind the user to open `outputs/paper-notes/html/papers/<KEY>.html` and click **"Sync Folder"**, then choose `outputs/paper-notes/`. This persists browser edits and status to `papers/<KEY>.edits.json`; it must be done even when the page is only regenerated. Also provide the HTML path and note that edits otherwise remain only in localStorage; Export/Import JSON is the fallback in non-Chromium browsers.

## LLM summary generation procedure (evidence-aware schema v4)

When `add` (or `refresh --regenerate-summary`) signals summary generation is needed:

1. Read `references/summary_schema.md` for the schema, article-guide structure, paper profiles, evidence rules, and final checklist.
2. Inputs are text extracted by the Python pipeline only: metadata/abstract, `papers/<KEY>.section_text.json`, `papers/<KEY>.sections.json` (if already generated), and `papers/<KEY>.annotations.json`. Never open or inspect PDF images. Do not pass figure images or the figure manifest to the LLM; figures are rendered for human viewing only. If `section_text.json` is missing while a PDF exists, stop and run the extraction step before writing a summary.
3. Select one or more paper profiles (`empirical`, `theory`, `method`, `benchmark`, `dataset`, `survey`, `system`, `replication`, or `other`) and generate `reading_guide` before filling the detailed fields. The guide must explain the paper as a connected argument, not as a list of field definitions:
   - `background`: the concrete situation or limitation that makes the work necessary; express the chain `existing understanding → gap → need for this study`.
   - `question`: the specific question, hypothesis, construction task, measurement task, or comparison the paper addresses.
   - `approach`: how the authors answer the question. For method papers emphasize the mechanism and input-output logic; for empirical papers emphasize subjects, data, design, and identification; for benchmark/dataset papers emphasize what is measured, how the resource is constructed, and how it is evaluated. Prefer 2–5 numbered points when the design has separable elements.
   - `main_findings`: the most important results, with selective numbers or evidence anchors when available. Prefer 2–5 numbered points when the findings are separable.
   - `insight`: what the findings change, clarify, or reveal. Separate the authors' interpretation from what the evidence independently supports.
   - `limitations`: the most consequential boundary, threat, missing evidence, or alternative explanation.
   `background`, `question`, `insight`, and `limitations` normally use short paragraphs. For `approach` and `main_findings`, prefer one numbered point per line in the form `1. **短而明确的结论**：用两三句解释它如何做、发现了什么或为什么重要。` The bold lead must state the point itself; the explanation must be brief but sufficient for a reader to understand it. Use a normal short paragraph only when a list would fragment an inseparable argument. Avoid repeating the same sentence across fields. The guide should let an intelligent non-specialist understand what the paper is doing before reading the detailed modules.
4. Adapt the guide to the paper profile instead of forcing every paper into one template. For method/system papers, foreground the technical bottleneck, core mechanism, validation, and operating conditions. For empirical/replication papers, foreground the question, design, findings, and competing explanations. For benchmark/dataset papers, foreground the measurement gap, construction choices, evaluation protocol, and capability or coverage insight. For theory papers, foreground the assumptions, propositions, derivation, and scope. For survey papers, foreground the review question, coverage, organizing framework, and synthesis.
5. Generate the detailed fields using the guide as the controlling narrative. Do not treat `research_question`, `contribution`, `method_or_design`, `results_or_claims`, and `interpretation` as independent summaries. They must agree with the guide and add detail rather than restating it. Fields that do not apply should be empty or `不适用`; do not invent generic content just to fill the schema.
6. Distinguish three layers whenever interpreting a result: (a) what the paper directly reports, (b) what the evidence supports, and (c) what remains a hypothesis, limitation, or alternative explanation. Never turn an author interpretation into a demonstrated mechanism without evidence.
7. Resolve research context according to configuration before generating `relevance_to_my_work`. If `use_research_context` is true, the add flow must already have saved an explicit project/none choice; use it and never silently choose a project. If false, do not ask and write only general research significance. Reuse an existing paper's saved choice on refresh unless explicitly changed. Completed projects remain historical context but cannot be selected for a new analysis.
8. Apply the remaining hard rules:
   - `key_quotes.text` MUST be copied **verbatim** from a real Zotero highlight — never paraphrase or invent. If no annotations, `key_quotes: []`.
   - With a selected project, `relevance_to_my_work` must use its structured fields and name a specific research question, design choice, dataset decision, or measurement problem. With no project, write general research significance without implying knowledge of the user's work. Do not invent a connection when one is weak.
   - Default language: Chinese. Quote text stays in the original language.
   - Do not use first-person stance labels or “不是……而是……” / “not X but Y” constructions.
   - Use `evidence_map` and `uncertainties` to separate reported facts, supported inferences, speculation, and missing information.
   - Keep prose concise and evidence-dense; use paragraphs only where the content has genuinely distinct parts. `build_paper_html.py`'s `render_prose()` + the template's `writeProse`/`readProse` JS preserve paragraph breaks.
   - Write prose as standard Markdown source, never HTML. The renderer supports `**bold**`, `*italic*`, inline code, links, and simple ordered/unordered lists while preserving the original Markdown for future `.md` or other output formats. Use selective `**bold**` spans for important terms, metrics, mechanisms, or caveats; do not bold entire sentences or paragraphs.
9. Record `research_context` (`id`, `name`, `research_question`, `project_updated_at`) and `relevance_generated_at`, then write the JSON to `papers/<KEY>.summary.json`.
9. Read every section in `papers/<KEY>.section_text.json` and write `papers/<KEY>.sections.json`. Each section object must contain `heading`, `page`, `level`, `summary`, and `analysis`; `summary` states what the section says, while `analysis` evaluates evidence, assumptions, limitations, or relevance. Do not skip this step because the summary JSON was successfully written. **Hierarchy is mandatory:** derive `level` from the source number — `4` is level 2, `4.1` is level 3, `4.1.1` is level 4, and so on. A numbered child must never have the same level as its parent.
10. Validate that `sections.json` exists, contains at least one section with non-empty `summary` and `analysis`, preserves source order, has no duplicate section numbers, and places every parent before its subsections. Explicitly verify that every dotted number has a deeper `level` than its parent (for example, `4.1` > `4`); the renderer infers hierarchy from numbering as a safety net, but an incorrect `level` in the generated JSON remains a generation error and must be reported. If validation fails, report the exact artifact or numbering error and do not claim the paper is fully generated.
11. Before rendering, perform a narrative consistency check: the guide's question, approach, findings, and insight must be traceable to the detailed fields and section analysis; remove duplicated or contradictory claims; mark unsupported explanations in `uncertainties`.
13. Run `sync_edits.py` at workflow boundaries before refresh/rebuild. HTML edits continue to merge from `edits.json`. Obsidian Markdown is authoritative for user-maintained note fields: visible headings identify fields, missing unambiguous headings clear only their corresponding JSON values, and duplicate/ambiguous headings are reported without changing canonical JSON. Obsidian pages contain no hidden field markers or baseline hashes.
14. For a new or regenerated summary, use `finalize-summary`; do not call a builder directly while the paper is in `template` state.

## Research projects and editable-view sync

Store projects in `research-projects.json` with stable ID, name, status, research question, background, method/design, data/materials, current challenges, keywords, and per-field timestamps. For Obsidian output, `Research/*.md` is authoritative for these editable fields and synchronizes back to JSON; the Dashboard remains derived and read-only.

HTML research pages and both dashboards are read-only. A project may be created conversationally through the research CLI; afterward the user may edit its Obsidian Research page directly. Synchronizing that page updates `research-projects.json` and the Dashboard's core-question/status/keyword columns.

Obsidian is content- and edit-equivalent, not browser-interaction-equivalent. Its ordinary Markdown files are the editing surface and source of truth for structured note content; do not add `%% paper-notes:field... %%` comments. Preserve user-added headings and paragraphs during rebuilds. Zotero metadata, highlights, figures, attachments, and reading statistics remain generated from their original sources. No Dataview or community plugin is required.

Never delete HTML or Obsidian paper edits unless the user asks to discard them. Research context is selected in conversation for summary generation and displayed read-only on pages.

The generated paper page is organized into three reader-facing blocks: `论文速览` (background, question, approach, findings, insight), `原文精读` (section summaries/analyses, quotes, figures, and source material), and `参考意义` (risks, costs, relevance, limitations, and open questions). Keep the content assignment aligned with this structure; do not put open questions inside the close-reading block.

## Reading time (approximation — be honest)

Zotero's Web API does NOT expose true reading duration. The `reading_time_minutes` / `reading_by_day` fields are **approximations** derived from annotation timestamps: consecutive annotations within 10 min of each other form a reading session; a session's duration equals the time span between its first and last annotation; a single isolated annotation (no neighbour within 10 min) counts as 5 min. No per-annotation overhead — time comes from actual inter-annotation gaps. This captures **highlighting activity time**, not total time the PDF was open. A paper read but never highlighted in Zotero's reader shows 0 — expected. The dashboard heatmap and per-paper reading-time stats both use this approximation. State this honestly when reporting reading-time figures; do not present them as authoritative "Zotero reading time".

## Browser → file status sync

The paper page's "Sync Folder" button uses the **File System Access API** (`showDirectoryPicker`). In Chromium browsers, granting access to the `outputs/paper-notes/` directory makes every edit (including status changes) auto-write to `papers/<KEY>.edits.json` — no backend. `build_dashboard.py` and `build_paper_html.py` merge each `<KEY>.edits.json`'s `status` on top of the manifest at render time, so browser status changes flow into the dashboard automatically. Safari/Firefox lack this API and fall back to manual Export/Import JSON. See `references/troubleshooting.md`.

## Refresh after re-reading

After the user adds new highlights in Zotero's PDF reader, they say "refresh paper X". Run `manage_reading_list.py refresh --key <KEY>`: re-fetches annotations + re-renders HTML, **preserving `edits.json`**. If the user also wants a fresh LLM summary, add `--regenerate-summary` and re-run the summary procedure. To discard manual edits and use the new summary instead, delete `papers/<KEY>.edits.json` before rebuilding.

## Visual style

Both templates (`assets/paper_template.html`, `assets/dashboard_template.html`) use an editorial reading layout: warm accent on warm-ink text (`#423F3D`), white background, 1px hairline borders (no shadow cards), tiny uppercase letterspaced labels as section markers, single column (~720px), dot list markers. The accent is **themeable** via 3 swatches (rose / green / blue) using the same 4-level structure (`--accent-light` / `--accent-mid` / `--accent-deep` / `--accent-tint`, + `--accent-mid-rgb` for alpha). Rose default `#ED7E7D` mid; green `#6FBF92`; blue `#6BA6D4` — all share hue/lightness so they read as one material. Set `<body data-accent="rose|green|blue">`; the override blocks sit just before `</style>`. The paper page shows a 3-dot Theme switcher in the topbar (persisted per paper in `localStorage` as `litreader:<key>:accent`); the dashboard has the same switcher (persisted as `litreader:dashboard:accent`). The dashboard's heatmap `--hm-0..--hm-4` are redefined inside each theme block so the heatmap recolors with the theme. The per-paper page makes every summary field `contenteditable` with localStorage auto-save + a "Sync Folder" button (File System Access API) that auto-writes edits + status to `papers/<KEY>.edits.json`, plus Export/Import JSON as fallback. A top-bar `← 总览` link (and a footer `← Back to Dashboard` link) returns to `../dashboard.html`. The dashboard renders a **GitHub-style contribution heatmap** (daily reading-minutes, 5 intensity levels from `--hm-0` to `--hm-4`) with a time-range switcher (3M / 6M / 1Y / All). Do not restyle to a different palette, and if you add a new accent color keep the 4-level structure aligned.

## Dashboard: collections & views

The "By Collection" module renders Zotero's **nested** collection hierarchy (parent→child), not a flat name list. Mechanics:
- `_common.fetch_collection_tree()` pulls the full tree (`key` / `name` / `parentCollection`) straight from the Zotero Web API; the bundled `zotero.py` intentionally has no collections command.
- Treat collection fetch failure as unavailable, never as an empty tree. Only an explicit `build_markdown.py --prepare-paths` may move notes; it must validate every ancestor before moving anything and use the last complete cache when offline.
- `manage_reading_list.py` stores each paper's collections as `[{key, name, parent}]`. **Note:** `zotero.py get --json` prints `item["data"]` directly, so `collections` is a top-level list of **key strings** — read `item.get("collections")`, never `item.get("data", {}).get("collections")`.
- `build_dashboard.py` → `_build_collection_hierarchy()` builds a nested tree, propagates subtree counts, prunes branches with 0 papers (ancestors stay visible), and emits breadcrumb paths used by the table view's Collection column.
- A **卡片视图 / 表格视图** toggle switches paper rendering between cards (inside each collection) and a table. Both views show **read-only tags** (from Zotero) as non-editable chips.
- The table view's **出版物 (venue)** column shows `metadata.venue` (the journal/conference). The Collection hierarchy is already expressed by the nested tree, so the list no longer repeats a flat Collection column.
- A **search box** (title/author) and **sort** control (最近阅读 / 年份 / 阅读时长) sit in the By Collection header; both re-render the tree, applying within each collection node.

### Tags (read-only)
- Tags come from Zotero `item.tags` only. The paper page renders them in the header `.tag-row` as static `tag-pill` chips; the dashboard renders them as static `pc-tag` chips in both card and table views. No editing, no edits.json tag merge.

### Figures (lightbox) + Markdown + Math (universal)
- Extracted figures render in the `论文图表` submodule as `.figure-card` cards (grid). **Each card is click-to-enlarge**: a click opens a full-screen lightbox overlay (`#lbOverlay` with the native-resolution `<img>` + caption); click the backdrop / × button / `Esc` closes it. This matters because some extracted figures are tiny (e.g. 150×198) and illegible inline.
- **Token budget — figures are extracted by Python (PyMuPDF) for human viewing only.** `extract_figures.py` writes image files + `manifest.json`; the LLM receives none of them. During summary generation, do not read the manifest, attach images, describe image pixels, or infer claims from figures. The summary JSON must stay image-free.
- **Markdown + LaTeX render uniformly in EVERY editable text field** — the overview guide fields, the reference-significance fields, the legacy detail fields, section summaries/analyses, and quote blocks. There is no special "formula module"; formatting is a property of the shared renderer, not of any one section.
  - Inline markdown: `**bold**`, `*italic*` (underscore `_italic_` is intentionally **not** supported — `_` is ubiquitous in LaTeX subscripts like `x_i` / `_{i=1}` and would be mangled), `` `code` ``, and `[text](url)` links.
  - LaTeX delimiters: `$…$` / `\(…\)` inline, `$$…$$` / `\[…\]` display, typeset by MathJax v3 (tex-svg from jsDelivr, loaded in `<head>`). MathJax auto-typesets the whole document on startup and re-runs via `window.litTypeset()` once ready. The `mdInline` pass escapes HTML and leaves `$…$` untouched, so formulas survive markdown.
  - Why `*` not `_` for italic, and why round-tripping matters: editing must stay lossless. Every field keeps its **raw source in `data-tex`**. On `focus` the field shows the raw markdown+LaTeX source (editable plaintext); on `blur` it re-renders via `writeProse` (markdown) and re-typesets math; on save `collectEdits` reads `data-tex`, so a rendered `<strong>`/`<mjx-container>` never corrupts what lands in localStorage / edits.json. Quote blocks carry `data-tex` from `build_paper_html.render_quotes`.
- **Accent color is themeable** via a switcher in the topbar (three dots: rose / green / blue). The whole UI recolors through three CSS-variable families — `--accent-light` / `--accent-mid` / `--accent-deep` / `--accent-tint` (plus `--accent-mid-rgb` for alpha shadows) — defined in `:root` (rose default) and overridden by `[data-accent="green"]` / `[data-accent="blue"]`. The chosen theme persists per-paper in `localStorage` (`litreader:<key>:accent`) and is applied on load via `setAccent()`. When adding a new accent, copy the 4-level structure (keep light/mid/deep/tint lightness aligned with rose) so the three themes read as the same material. The fixed semantic greens (`#8FB98A` for "saved/synced" dots, `.is-connected`) stay literal and are NOT part of the theme system.

## Edge cases

See `references/troubleshooting.md` for: invalid API key, no PDF / no annotations, duplicate add, rate limiting, collection rename, edits-vs-refresh conflicts, and the `next_step:generate_summary` flow.
