#!/usr/bin/env python3
"""Explicitly merge HTML/Obsidian user edits into canonical paper JSON."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import _common

HTML_FIELD_RE = re.compile(
    r"<!-- paper-notes:field:([a-zA-Z0-9_]+):start(?:\s+base-sha256=([a-f0-9]+))? -->\n?"
    r"(.*?)\n?<!-- paper-notes:field:\1:end -->", re.S
)
OBSIDIAN_FIELD_RE = re.compile(
    r"%% paper-notes:field:([a-zA-Z0-9_]+):start(?:\s+base-sha256=([a-f0-9]+))? %%\n?"
    r"(.*?)\n?%% paper-notes:field:\1:end %%", re.S
)
GUIDE_MAP = {
    "guide_background": "background", "guide_question": "question",
    "guide_approach": "approach", "guide_findings": "main_findings",
    "guide_insight": "insight", "guide_limitations": "limitations",
}
SUMMARY_MAP = {
    "objective": "one_sentence_summary", "problem_landscape": "background_and_gap",
    "approach": "method_or_design", "impact": "contribution",
    "risks": "limitations_and_threats", "cost": "reproduction_conditions",
    "experiments_results": "results_or_claims",
    "relevance_to_my_work": "relevance_to_my_work",
    "open_questions": "open_questions", "custom_notes": "custom_notes",
    "key_quotes": "key_quotes", "module_notes": "module_notes",
}
LIST_FIELDS = {"risks", "open_questions"}
PAPER_HEADINGS = {
    "guide_background": "研究背景", "guide_question": "研究目标",
    "guide_approach": "研究内容", "guide_findings": "主要结论",
    "guide_insight": "主要洞见", "risks": "风险与威胁",
    "guide_limitations": "总体局限", "cost": "成本与复现条件",
    "relevance_to_my_work": "与我研究的关联", "open_questions": "待追问",
    "custom_notes": "我的笔记",
}
RESEARCH_HEADINGS = {
    "research_question": "研究问题", "background": "背景与动机",
    "method_or_design": "方法或设计", "data_or_materials": "数据或材料",
    "current_challenges": "当前难点", "keywords": "关键词",
}
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def value_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso_from_mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _parse_time(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _list_from_markdown(value):
    return [m.group(1).strip() for line in value.splitlines()
            if (m := re.match(r"\s*(?:[-*]|\d+\.)\s+(.*)", line))]


def _parse_fields(path):
    text = path.read_text(encoding="utf-8")
    matches = HTML_FIELD_RE.findall(text) + OBSIDIAN_FIELD_RE.findall(text)
    return [(name, base or None, body.strip()) for name, base, body in matches]


def _heading_blocks(text):
    """Return a small Markdown heading tree without interpreting body markup."""
    lines = text.splitlines()
    headings, fenced = [], False
    for index, line in enumerate(lines):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
            continue
        match = None if fenced else HEADING_RE.match(line)
        if match:
            headings.append({"level": len(match.group(1)), "title": match.group(2).strip(),
                             "line": index, "body_start": index + 1})
    for i, heading in enumerate(headings):
        end = len(lines)
        for following in headings[i + 1:]:
            if following["level"] <= heading["level"]:
                end = following["line"]
                break
        heading["end"] = end
        heading["body"] = "\n".join(lines[heading["body_start"]:end]).strip()
    return headings


def _unique_heading(headings, title, within=None):
    matches = [h for h in headings if h["title"] == title and
               (within is None or (h["line"] > within["line"] and h["line"] < within["end"]))]
    return (matches[0] if len(matches) == 1 else None), len(matches)


def _frontmatter(text):
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    result = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            continue
        value = match.group(2).strip()
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            pass
        result[match.group(1)] = value
    return result


def _section_name(value):
    return re.sub(r"^\d+(?:\.\d+)*(?:[.)])?\s+", "", str(value or "").strip())


def _plain_marker_migration(text):
    """Remove legacy comments and add headings for the two formerly unlabeled fields."""
    text = re.sub(r"^### 风险与局限\s*$", "### 风险与威胁", text, flags=re.M)
    text = re.sub(r"%% paper-notes:field:guide_insight:start[^%]*%%\s*", "### 主要洞见\n", text)
    text = re.sub(r"%% paper-notes:field:guide_limitations:start[^%]*%%\s*", "### 总体局限\n", text)
    text = re.sub(r"%% paper-notes:field:section_\d+_summary:start[^%]*%%\s*", "###### 总结\n", text)
    text = re.sub(r"%% paper-notes:field:section_\d+_analysis:start[^%]*%%\s*", "###### 分析\n", text)
    text = re.sub(r"%% paper-notes:field:quote_(\d+)_text:start[^%]*%%\s*",
                  lambda m: "#### 引文 %d\n\n##### 原文\n" % (int(m.group(1)) + 1), text)
    text = re.sub(r"%% paper-notes:field:quote_\d+_note:start[^%]*%%\s*", "##### 说明\n", text)
    text = re.sub(r"^%% paper-notes:field:[^\n]+%%\s*\n?", "", text, flags=re.M)
    return text


def _cleanup_legacy_labels(text):
    text = re.sub(r"^\*\*总结\*\*\s*\n(?=###### 总结\s*$)", "", text, flags=re.M)
    text = re.sub(r"^\*\*分析\*\*\s*\n(?=###### 分析\s*$)", "", text, flags=re.M)
    text = re.sub(r"^###### 总结\s*$", "**总结**", text, flags=re.M)
    text = re.sub(r"^###### 分析\s*$", "**分析**", text, flags=re.M)
    text = re.sub(r"^(_p\.[^\n]*_)\n\s*\n(?=\*\*总结\*\*$)", r"\1\n", text, flags=re.M)
    return text


def _labeled_body(lines, start, end, label):
    markers = {"**%s**" % label, "###### %s" % label}
    positions = [i for i in range(start, end) if lines[i].strip() in markers]
    if len(positions) != 1:
        return None, len(positions), None
    begin = positions[0] + 1
    stops = [i for i in range(begin, end)
             if lines[i].strip() in {"**总结**", "**分析**", "###### 总结", "###### 分析"}]
    finish = min(stops) if stops else end
    return "\n".join(lines[begin:finish]).strip(), 1, positions[0]


def _state_path(key):
    return _common.PAPERS_DIR / (key + ".field-state.json")


def _load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _canonical_values(summary, sections):
    guide = summary.get("reading_guide", {}) if isinstance(summary.get("reading_guide"), dict) else {}
    values = {field: guide.get(target, "") for field, target in GUIDE_MAP.items()}
    values["sections"] = sections.get("sections", [])
    for field, target in SUMMARY_MAP.items():
        values[field] = summary.get(target, [] if field in LIST_FIELDS or field == "key_quotes" else ({} if field == "module_notes" else ""))
    for i, section in enumerate(sections.get("sections", [])):
        values["section_%d_summary" % i] = section.get("summary", "")
        values["section_%d_analysis" % i] = section.get("analysis", "")
    for i, quote in enumerate(summary.get("key_quotes", []) or []):
        values["quote_%d_text" % i] = quote.get("text", "")
        values["quote_%d_note" % i] = quote.get("note", quote.get("explanation", ""))
    for module, value in (summary.get("module_notes", {}) or {}).items():
        values["module_note_" + module.replace("-", "_")] = value
    return values


def _write_canonical(field, value, summary, sections):
    if field == "sections" and isinstance(value, list):
        sections["sections"] = value
    elif field in GUIDE_MAP:
        summary.setdefault("reading_guide", {})[GUIDE_MAP[field]] = value
    elif field in SUMMARY_MAP:
        summary[SUMMARY_MAP[field]] = value
    elif (m := re.fullmatch(r"section_(\d+)_(summary|analysis)", field)):
        idx = int(m.group(1))
        if idx < len(sections.get("sections", [])):
            sections["sections"][idx][m.group(2)] = value
    elif (m := re.fullmatch(r"quote_(\d+)_(text|note)", field)):
        idx = int(m.group(1))
        quotes = summary.setdefault("key_quotes", [])
        if idx < len(quotes):
            quotes[idx][m.group(2)] = value
    elif (m := re.fullmatch(r"module_note_(.+)", field)):
        summary.setdefault("module_notes", {})[m.group(1).replace("_", "-")] = value


def _paper_markdown_path(paper):
    stored = paper.get("obsidian_path")
    if stored:
        path = _common.OBSIDIAN_DIR / stored
        if path.exists():
            return path
    legacy = _common.OBSIDIAN_PAPERS_DIR / (paper["zotero_key"] + ".md")
    return legacy if legacy.exists() else None


def _backup_conflict(key, field, canonical, incoming, source, canonical_ts, incoming_ts):
    out = _common.OUTPUT_DIR / "conflicts"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = out / ("%s-%s-%s.json" % (key, field, stamp))
    path.write_text(json.dumps({
        "key": key, "field": field, "source": source,
        "canonical": canonical, "incoming": incoming,
        "canonical_timestamp": canonical_ts, "incoming_timestamp": incoming_ts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def initialize_state(key, generation_state=None, force_stamp=False):
    """Create/update canonical field state after summary generation."""
    summary_path = _common.PAPERS_DIR / (key + ".summary.json")
    sections_path = _common.PAPERS_DIR / (key + ".sections.json")
    summary = _load_json(summary_path, {})
    sections = _load_json(sections_path, {"sections": []})
    state = _load_json(_state_path(key), {"version": 1, "fields": {}})
    fallback = summary.get("generated_at") or (_iso_from_mtime(summary_path) if summary_path.exists() else _common.now_iso())
    for field, value in _canonical_values(summary, sections).items():
        old = state.setdefault("fields", {}).get(field)
        if force_stamp or not old or old.get("hash") != value_hash(value):
            state["fields"][field] = {"hash": value_hash(value), "updated_at": fallback, "source": "canonical"}
    if generation_state:
        state["generation_state"] = generation_state
    else:
        state.setdefault("generation_state", "generated" if any(_canonical_values(summary, sections).values()) else "template")
    _state_path(key).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def sync_paper(key):
    """Mirror HTML edits and Markdown-owned note fields into canonical JSON."""
    _common.validate_paper_key(key)
    manifest = _common.load_manifest()
    paper = next((p for p in manifest.get("papers", []) if p.get("zotero_key") == key), None)
    if not paper:
        raise ValueError("paper %s not found in manifest" % key)
    summary_path = _common.PAPERS_DIR / (key + ".summary.json")
    sections_path = _common.PAPERS_DIR / (key + ".sections.json")
    edits_path = _common.PAPERS_DIR / (key + ".edits.json")
    summary = _load_json(summary_path, {})
    sections = _load_json(sections_path, {"sections": []})
    state = initialize_state(key)
    canonical = _canonical_values(summary, sections)
    candidates = []
    conflicts = []
    cleared_fields = []
    ambiguous_fields = []

    # HTML exports contain field-level timestamps for changed fields. Legacy
    # exports fall back to file mtime, but an untracked empty value never clears
    # a non-empty canonical value.
    edits = _load_json(edits_path, {}) if edits_path.exists() else {}
    html_times = edits.get("_field_updated_at", {}) if isinstance(edits.get("_field_updated_at"), dict) else {}
    html_mtime = _iso_from_mtime(edits_path) if edits_path.exists() else ""
    for field, value in edits.items():
        if field.startswith("_") or field in ("zotero_key", "schema_version", "built_at", "generated_at", "exported_at"):
            continue
        if field in canonical:
            if value == canonical[field]:
                continue
            explicit_ts = html_times.get(field)
            if not explicit_ts and value in ("", [], {}) and canonical.get(field) not in ("", [], {}):
                continue
            candidates.append((field, value, explicit_ts or html_mtime, "html"))

    changed = False
    for field, incoming, incoming_ts, source in candidates:
        current = canonical.get(field)
        meta = state.setdefault("fields", {}).get(field, {})
        canonical_ts = meta.get("updated_at", "")
        incoming_dt, canonical_dt = _parse_time(incoming_ts), _parse_time(canonical_ts)
        if incoming != current and (not incoming_dt or not canonical_dt):
            conflicts.append(_backup_conflict(key, field, current, incoming, source, canonical_ts, incoming_ts))
            continue
        if incoming_dt == canonical_dt and incoming != current:
            conflicts.append(_backup_conflict(key, field, current, incoming, source, canonical_ts, incoming_ts))
            continue
        if incoming_dt < canonical_dt:
            continue
        _write_canonical(field, incoming, summary, sections)
        canonical[field] = incoming
        state["fields"][field] = {"hash": value_hash(incoming), "updated_at": incoming_ts, "source": source}
        changed = True

    # Obsidian is authoritative for note content. Legacy markers are consumed
    # once, then removed in place; current notes are parsed by visible headings.
    md_path = _paper_markdown_path(paper)
    preserved_custom_blocks = 0
    if md_path:
        text = md_path.read_text(encoding="utf-8")
        legacy = _parse_fields(md_path)
        md_values = {}
        if legacy:
            for field, _base, raw in legacy:
                if field in canonical:
                    md_values[field] = _list_from_markdown(raw) if field in LIST_FIELDS else raw
            migrated = _cleanup_legacy_labels(_plain_marker_migration(text))
            if migrated != text:
                md_path.write_text(migrated, encoding="utf-8")
                text = migrated
        else:
            cleaned = _cleanup_legacy_labels(text)
            if cleaned != text:
                md_path.write_text(cleaned, encoding="utf-8")
                text = cleaned
            headings = _heading_blocks(text)
            text_lines = text.splitlines()
            recognized = set()
            for field, title in PAPER_HEADINGS.items():
                node, count = _unique_heading(headings, title)
                if count == 1:
                    value = _list_from_markdown(node["body"]) if field in LIST_FIELDS else node["body"]
                    md_values[field] = value
                    recognized.add(node["line"])
                elif count == 0:
                    md_values[field] = [] if field in LIST_FIELDS else ""
                    cleared_fields.append(field)
                else:
                    ambiguous_fields.append(field)

            sections_root, root_count = _unique_heading(headings, "分章节总结与分析")
            section_nodes = []
            if root_count == 1:
                section_nodes = [h for h in headings
                                 if h["line"] > sections_root["line"] and h["line"] < sections_root["end"]
                                 and h["title"] not in ("总结", "分析")]
            for index, section in enumerate(sections.get("sections", [])):
                prefix = "section_%d_" % index
                if root_count != 1:
                    if root_count > 1:
                        ambiguous_fields += [prefix + "summary", prefix + "analysis"]
                    else:
                        md_values[prefix + "summary"] = ""
                        md_values[prefix + "analysis"] = ""
                        cleared_fields += [prefix + "summary", prefix + "analysis"]
                    continue
                expected_name = _section_name(section.get("heading"))
                if len(section_nodes) == len(sections.get("sections", [])):
                    candidate = section_nodes[index]
                    section_node = candidate if _section_name(candidate["title"]) == expected_name else None
                    section_count = 1 if section_node else 0
                else:
                    matches = [h for h in section_nodes if _section_name(h["title"]) == expected_name]
                    section_node = matches[0] if len(matches) == 1 else None
                    section_count = len(matches)
                if section_count != 1:
                    target = ambiguous_fields if section_count > 1 else cleared_fields
                    target += [prefix + "summary", prefix + "analysis"]
                    if section_count == 0:
                        md_values[prefix + "summary"] = ""
                        md_values[prefix + "analysis"] = ""
                    continue
                recognized.add(section_node["line"])
                following_lines = [h["line"] for h in section_nodes if h["line"] > section_node["line"]]
                section_field_end = min(following_lines) if following_lines else sections_root["end"]
                for suffix, label in (("summary", "总结"), ("analysis", "分析")):
                    value, count, marker_line = _labeled_body(
                        text_lines, section_node["line"] + 1, section_field_end, label)
                    field = prefix + suffix
                    if count == 1:
                        md_values[field] = value
                        recognized.add(marker_line)
                    elif count == 0:
                        md_values[field] = ""
                        cleared_fields.append(field)
                    else:
                        ambiguous_fields.append(field)
            quotes_root, quotes_root_count = _unique_heading(headings, "关键引文")
            for index, _quote in enumerate(summary.get("key_quotes", []) or []):
                fields = (("quote_%d_text" % index, "原文"),
                          ("quote_%d_note" % index, "说明"))
                quote_node, quote_count = ((None, 0) if quotes_root_count != 1 else
                                           _unique_heading(headings, "引文 %d" % (index + 1), quotes_root))
                for field, label in fields:
                    if quote_count == 1:
                        node, count = _unique_heading(headings, label, quote_node)
                    else:
                        node, count = None, quote_count
                    if count == 1:
                        value = node["body"]
                        if label == "原文":
                            value = re.sub(r"\n?页码：[^\n]*；颜色：[^\n]*$", "", value).strip()
                        md_values[field] = value
                        recognized.add(node["line"])
                    elif count == 0:
                        md_values[field] = ""
                        cleared_fields.append(field)
                    else:
                        ambiguous_fields.append(field)
            known_titles = set(PAPER_HEADINGS.values()) | {"论文速览", "原文精读", "分章节总结与分析",
                                                           "关键引文", "论文图表", "Zotero 高亮", "Zotero 笔记", "参考意义"}
            preserved_custom_blocks = sum(h["title"] not in known_titles and h["line"] not in recognized
                                          for h in headings)

        md_ts = _iso_from_mtime(md_path)
        for field, incoming in md_values.items():
            if field in canonical and incoming != canonical[field]:
                _write_canonical(field, incoming, summary, sections)
                canonical[field] = incoming
                state.setdefault("fields", {})[field] = {
                    "hash": value_hash(incoming), "updated_at": md_ts, "source": "obsidian"}
                changed = True

        status = _frontmatter(text).get("status")
        if status in ("reading", "done", "archived") and paper.get("status") != status:
            paper["status"] = status
            _common.save_manifest(manifest)
            changed = True

    # Status remains an explicitly editable presentation field.
    status = edits.get("status")
    if status in ("reading", "done", "archived") and paper.get("status") != status:
        paper["status"] = status
        _common.save_manifest(manifest)
        changed = True

    if changed:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if sections.get("sections"):
            sections_path.write_text(json.dumps(sections, ensure_ascii=False, indent=2), encoding="utf-8")
        _state_path(key).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"key": key, "changed": changed, "conflicts": conflicts,
            "cleared_fields": sorted(set(cleared_fields)),
            "ambiguous_fields": sorted(set(ambiguous_fields)),
            "preserved_custom_blocks": preserved_custom_blocks}


def sync_research():
    """Mirror editable Obsidian Research pages into research-projects.json."""
    data = _common.load_research_projects()
    projects = data.get("projects", [])
    by_id = {p.get("id"): p for p in projects}
    by_name = {p.get("name"): p for p in projects}
    changed = False
    cleared_fields, ambiguous_fields = [], []
    preserved_custom_blocks = 0
    seen = set()
    if not _common.OBSIDIAN_RESEARCH_DIR.is_dir():
        return {"changed": False, "conflicts": [], "cleared_fields": [],
                "ambiguous_fields": [], "preserved_custom_blocks": 0}

    for path in sorted(_common.OBSIDIAN_RESEARCH_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front = _frontmatter(text)
        project = by_id.get(front.get("research_id")) or by_id.get(path.stem) or by_name.get(path.stem)
        if not project or project.get("id") in seen:
            ambiguous_fields.append("research:%s" % path.name)
            continue
        seen.add(project.get("id"))
        if not front.get("research_id"):
            if text.startswith("---\n"):
                text = "---\nresearch_id: %s\n%s" % (
                    json.dumps(project["id"], ensure_ascii=False), text[4:])
            else:
                text = "---\nresearch_id: %s\n---\n\n%s" % (
                    json.dumps(project["id"], ensure_ascii=False), text)
            path.write_text(text, encoding="utf-8")
            front = _frontmatter(text)
            changed = True
        headings = _heading_blocks(text)
        updates = {}
        recognized = set()
        for field, title in RESEARCH_HEADINGS.items():
            node, count = _unique_heading(headings, title)
            label = "%s.%s" % (project["id"], field)
            if count == 1:
                value = node["body"]
                if field == "keywords":
                    value = [x.strip() for x in re.split(r"[,，;；\n]", value) if x.strip()]
                updates[field] = value
                recognized.add(node["line"])
            elif count == 0:
                updates[field] = [] if field == "keywords" else ""
                cleared_fields.append(label)
            else:
                ambiguous_fields.append(label)
        if front.get("status") in ("active", "paused", "completed"):
            updates["status"] = front["status"]

        now = _iso_from_mtime(path)
        stamps = project.setdefault("field_updated_at", {})
        project_changed = False
        for field, value in updates.items():
            if project.get(field) != value:
                project[field] = value
                stamps[field] = now
                project_changed = True
        if project_changed:
            project["updated_at"] = now
            changed = True
        preserved_custom_blocks += sum(h["title"] not in set(RESEARCH_HEADINGS.values())
                                       and h["line"] not in recognized for h in headings)

    if changed:
        _common.save_research_projects(data)
    return {"changed": changed, "conflicts": [],
            "cleared_fields": sorted(set(cleared_fields)),
            "ambiguous_fields": sorted(set(ambiguous_fields)),
            "preserved_custom_blocks": preserved_custom_blocks}


def _refresh_dashboards():
    cfg = _common.load_config()
    here = Path(__file__).resolve().parent
    if cfg.get("output_mode", "html") in ("html", "both"):
        subprocess.run([sys.executable, str(here / "build_dashboard.py")], check=True)
    if cfg.get("output_mode") in ("obsidian", "both"):
        subprocess.run([sys.executable, str(here / "build_markdown.py"), "--dashboard-only"], check=True)


def sync_all():
    result = {"papers": []}
    for paper in _common.load_manifest().get("papers", []):
        result["papers"].append(sync_paper(paper["zotero_key"]))
    result["research"] = sync_research()
    return result


def main():
    ap = argparse.ArgumentParser(description="Explicitly merge HTML and Obsidian user edits")
    ap.add_argument("--key", help="sync one paper; omit to sync all")
    ap.add_argument("--research-only", action="store_true", help="sync Obsidian Research pages only")
    args = ap.parse_args()
    if args.research_only:
        result = sync_research()
    elif args.key:
        result = {"paper": sync_paper(args.key)}
    else:
        result = sync_all()
    research_result = result if args.research_only else result.get("research", {})
    if research_result.get("changed"):
        _refresh_dashboards()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
