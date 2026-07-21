# Troubleshooting

## "API Error 403: Forbidden" / "Key not found"

The `ZOTERO_API_KEY` is invalid, expired, or lacks library-read access. Zotero
returns 403 / "Key not found" at `https://api.zotero.org/keys/<KEY>`.

**Fix**: create a fresh key at https://www.zotero.org/settings/keys/new with
"Allow library access" (read) checked, then `export ZOTERO_API_KEY=<newkey>`.
Confirm the numeric `ZOTERO_USER_ID` (found on the same settings page, NOT the
username) is also set.

> **Gotcha — empty key looks like "Invalid key"**: the Bash tool's
> non-interactive shell does **not** auto-source `~/.zshrc`, so a `ZOTERO_API_KEY`
> exported there is absent from `os.environ` and the request goes out with an
> *empty* key → Zotero returns 403 "Invalid key". This is NOT a dead key. Either
> run `source ~/.zshrc` first, or rely on the built-in fallback:
> `_common.get_zotero_config()` automatically parses `~/.zshrc` / `~/.bashrc` /
> `~/.zprofile` / `~/.bash_profile` for `ZOTERO_*` vars when the environment is
> unset, so the scripts work without a manual `source`.

Verify with:
```bash
python3 scripts/fetch_annotations.py <PAPER_KEY>
```

## Paper has no PDF attachment (`has_pdf: false`)

Some Zotero items are metadata-only (no downloaded PDF). `fetch_annotations.py`
returns `has_pdf: false` with empty annotations.

**Handling**: `add`/`refresh` still succeed. The HTML renders with an empty
highlights panel ("未检测到 PDF 高亮"). The LLM summary is generated from the
`abstractNote` only, with `key_quotes: []`. No error.

To add a PDF: use the zotero skill's `fetch-pdfs` command, or attach one in the
Zotero desktop client, then `refresh --key <KEY>`.

## Paper has PDF but no annotations (`has_annotations: false`)

The PDF exists but the user hasn't highlighted it in Zotero's built-in reader.
Annotations created in external PDF readers (Preview, Adobe) are NOT synced to
Zotero's API — only highlights made in Zotero's own reader become `annotation`
items.

**Handling**: same as no-PDF — empty highlights panel, summary from abstract.

## Duplicate add ("already in list", exit code 2)

`add --key <KEY>` refuses if the key is already in the manifest. This protects
against clobbering an existing summary/edits.

**Options**:
- To pull fresh annotations: `refresh --key <KEY>` (keeps edits + summary).
- To start over: `remove --key <KEY>` then `add --key <KEY>` (deletes edits
  unless `--keep-edits` is passed to remove).
- To change status only: `mark --key <KEY> --status done`.

## Rate limiting (429 / 503)

Zotero returns 429 (too many requests) or 503 (service unavailable) under
load. `_common.api_request` retries twice with 2s/4s backoff. If retries are
exhausted, the script exits with the error.

**Fix**: wait a minute and retry. `refresh --all` already pauses 0.5s between
papers to avoid bursts. For very large libraries, refresh in smaller batches
by key.

## Collection renamed or deleted in Zotero

The manifest stores a `{key, name}` snapshot at add time. On `refresh`:
- If the collection key still exists but the name changed → name is updated.
- If the collection key no longer exists (deleted in Zotero) → the old record
  is retained but the dashboard still shows it under the old name (so the user
  doesn't lose the grouping). Re-adding the paper to a new collection and
  refreshing picks up the new collection.

## Edits vs. refresh conflict

`edits.json` (the user's HTML edits, exported via the Export button) is **never
overwritten** by `refresh`. This is by design — user edits survive re-fetching
annotations.

- `refresh --key <KEY>`: re-fetches annotations + re-renders HTML, using the
  existing `edits.json` (if present) as the editable content, falling back to
  `summary.json`.
- `refresh --key <KEY> --regenerate-summary`: blanks `summary.json` for the LLM
  to regenerate. **`edits.json` is still preserved.** If the user wants the
  fresh LLM summary to show, they must delete `papers/<KEY>.edits.json` first
  (or the LLM-edited content in edits takes precedence at render).

Recommendation: tell the user "to discard your manual edits and use the new
LLM summary, delete `papers/<KEY>.edits.json` then re-run build_paper_html."

## Lost edits (cleared localStorage)

Browser localStorage is per-browser and can be cleared. Recovery path:
- If the user exported `edits.json` (via the Export button) and the file sits
  in `papers/<KEY>.edits.json`, it's loaded as the initial content on next
  render — edits are recovered.
- If no export happened, edits are lost. Encourage users to click Export JSON
  after substantial edits.

## `next_step: generate_summary` flow

`manage_reading_list.py add` returns `next_step: "generate_summary"` because
the script is a stateless renderer — it does NOT call the LLM. After adding:
1. Read `references/summary_schema.md`.
2. Read `papers/<KEY>.annotations.json` + the abstract from the manifest.
3. Generate the schema-conformant summary JSON.
4. Write it to `papers/<KEY>.summary.json`.
5. Re-run `build_paper_html.py --key <KEY>` + `build_dashboard.py`.

If skipped, the paper page shows empty editable regions (placeholders) — still
functional but unpopulated.

## Status sync from the browser (File System Access API)

The paper page's "Sync Folder" button uses the **File System Access API**
(`showDirectoryPicker`). When the user clicks it and grants access to the
`outputs/paper-notes/` directory, every edit (including status changes)
is written directly to `papers/<KEY>.edits.json` on disk — no backend server.
The directory handle is persisted in IndexedDB so the connection survives
reloads (in Chromium browsers).

**Browser support**: Chrome, Edge, and other Chromium browsers. Safari and
Firefox do not support `showDirectoryPicker` — the page shows Export/Import
JSON buttons as a manual fallback. In those browsers, status changes only
persist to localStorage until the user clicks Export JSON.

**How browser status reaches the manifest**: `build_dashboard.py` and
`build_paper_html.py` both read each `papers/<KEY>.edits.json` and apply its
`status` field on top of the manifest entry before rendering. So a status
change made in the browser flows into the dashboard the next time
`build_dashboard.py` runs — no separate sync command needed. (The manifest's
`reading-list.json` itself is not rewritten by the browser; the merge happens
at render time. If you want the manifest file updated too, run
`manage_reading_list.py mark --key <KEY> --status <status>`.)

## Reading time is an approximation (honesty note)

Zotero's **Web API does NOT expose per-paper reading duration**. The
`reading_time_minutes` / `reading_by_day` fields are an **approximation**
derived from annotation timestamps: consecutive annotations no more than
10 min apart form a session, whose duration is the span from its first to
last annotation. A session containing a single annotation counts as 5 min;
there is no per-annotation overhead or per-session cap. Sessions that cross
midnight have their minutes split between the affected UTC dates. This captures
highlighting activity, not actual time the PDF was open.

If a paper was read but never highlighted in Zotero's reader, its reading
time will read as 0 even though it was read. Treat the reading-time metric as
"highlighting activity time", not "total reading time". True reading duration
is only in Zotero's local desktop database, which the Web API does not expose.

## Figure extraction failures

`extract_figures.py` runs during `add`/`refresh` (best-effort). It needs
PyMuPDF. `manage_reading_list.py` already resolves a PyMuPDF-capable interpreter
(env override `LITERATURE_READER_FIGURE_PYTHON`, else a managed
venv, else the current interpreter) and calls it automatically. If it fails
silently, the paper page's Figures section shows an empty-state message — the
rest of the page still renders. Re-run manually:

```bash
# any interpreter that has PyMuPDF installed
python3 scripts/extract_figures.py <KEY>
```

A PDF may have no extractable embedded images (some journals render figures as
vector graphics, not raster XObjects). In that case the count is 0 — not a bug.
