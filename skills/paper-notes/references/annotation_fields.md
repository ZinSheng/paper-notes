# Zotero Annotation Fields & Color Mapping

This documents the `annotation` itemType (Zotero 6+) that `fetch_annotations.py`
parses, and the color-category display strategy.

## Why a separate fetcher?

The companion `zotero` skill's `children`/`get` commands recognize only
`attachment` and `note` itemTypes. PDF highlights are stored as `annotation`
items two levels below the paper:

```
paper (itemType: journalArticle / bookSection / ...)
  └─ PDF attachment (itemType: attachment, contentType: application/pdf)
       └─ annotation (itemType: annotation)   ← fetched here
       └─ note      (itemType: note)          ← also fetched
```

So fetching annotations requires: `GET /items/<PAPER>/children` → find the PDF
attachment → `GET /items/<PDF_ATTACHMENT>/children` → filter `annotation`.

## Annotation fields parsed

| Zotero field             | Output field     | Notes                                    |
|--------------------------|------------------|-------------------------------------------|
| `annotationType`         | `type`           | `highlight` / `note` / `image` / `ink`    |
| `annotationText`          | `text`           | Verbatim highlight text (empty for `note`-type, which carry text in `annotationComment`) |
| `annotationComment`      | `comment`        | User's margin note                        |
| `annotationColor`        | `color`          | Hex, e.g. `#ffd400`                       |
| (derived)                | `color_category` | Mapped from `color` (see below)           |
| `annotationPageLabel`     | `page_label`     | Page label string                         |
| `annotationSortIndex`     | `sort_index`     | Sort key (lexicographic = reading order)  |
| `dateAdded`              | `date_added`     | ISO timestamp                             |
| `dateModified`           | `date_modified`  | ISO timestamp                             |
| (derived)                | `date_added_day` | `YYYY-MM-DD` for the reading calendar     |

`note` items (standalone Zotero notes) are also captured with their HTML body
stripped to a plain-text preview.

## Color → category mapping

Zotero ships 6 default annotation colors. Only these exact hex values map to a
named category; any custom color maps to `"other"`.

| Hex       | Category | Display swatch |
|-----------|----------|----------------|
| `#ffd400` | yellow   | warm yellow    |
| `#ff6666` | red      | coral red      |
| `#5fb236` | green    | sage green     |
| `#2ea8e5` | blue     | sky blue       |
| `#a28ae5` | purple   | lavender       |
| `#e56eee` | magenta  | magenta        |
| (other)   | other    | gray           |

## Display strategy (IMPORTANT)

**Colors are displayed only — no semantic meaning is imposed.** The user may
have a personal color system in Zotero (e.g. yellow = definitions, red =
disagreement). This skill does NOT assume one. The highlights panel groups by
`color_category` purely for visual scanning, with a small swatch + count, and
renders each highlight's text verbatim with its page label and (if present)
the user's comment.

When generating `key_quotes` in the summary, copy the original `color` into the
quote object so the HTML quote card can show the swatch — but never translate a
color into a claim about the user's intent.

## Output JSON structure

```json
{
  "zotero_key": "VNPN6FHT",
  "pdf_attachment_key": "WXYZ1234",
  "has_pdf": true,
  "has_annotations": true,
  "annotation_count": 23,
  "annotation_summary": {"highlight": 18, "note": 3, "image": 1, "ink": 1},
  "annotations": [ { ...normalized record... }, ... ],
  "notes": [ {key, html, text, date_added, date_added_day}, ... ]
}
```

`fetch_annotations.py` caches this to `papers/<KEY>.annotations.json` during
`add`/`refresh`, and `build_paper_html.py` reads it to render the highlights
panel.
