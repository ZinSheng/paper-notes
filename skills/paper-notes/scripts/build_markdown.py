#!/usr/bin/env python3
"""Pure-render the self-contained Obsidian vault from canonical JSON."""

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import _common
import sync_edits


ACCENTS = {
    "rose": ["#F5F0EC", "#FCE4E0", "#F7B5AC", "#F08A7E", "#E25648"],
    "green": ["#F5F0EC", "#E4F4EA", "#B6DFC4", "#6FBF92", "#1F7A4F"],
    "blue": ["#F5F0EC", "#E4F1F8", "#AFD2EC", "#6BA6D4", "#286BA3"],
}


def _load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _yaml_scalar(value):
    return "null" if value in (None, "") else json.dumps(value, ensure_ascii=False)


def _yaml_list(name, values):
    values = [str(v) for v in (values or []) if str(v).strip()]
    if not values:
        return [name + ": []"]
    return [name + ":"] + ["  - " + json.dumps(v, ensure_ascii=False) for v in values]


def _yaml_block(name, value):
    if not value:
        return [name + ": null"]
    lines = str(value).splitlines() or [str(value)]
    return [name + ": |-"] + ["  " + line for line in lines]


def _replace_frontmatter(existing, rendered):
    """Refresh generated YAML while preserving the user-authored note body."""
    marker = "---\n"
    if not rendered.startswith(marker):
        return existing
    rendered_end = rendered.find("\n---\n", len(marker))
    if rendered_end < 0:
        return existing
    generated_frontmatter = rendered[:rendered_end + len("\n---\n")]
    if not existing.startswith(marker):
        return generated_frontmatter + "\n" + existing.lstrip("\n")
    existing_end = existing.find("\n---\n", len(marker))
    if existing_end < 0:
        return existing
    return generated_frontmatter + existing[existing_end + len("\n---\n"):]


def _creator_names(creators):
    names = []
    for creator in creators or []:
        if creator.get("creatorType") and creator.get("creatorType") != "author":
            continue
        name = creator.get("name") or " ".join(
            x for x in (creator.get("firstName"), creator.get("lastName")) if x)
        if name:
            names.append(name.strip())
    return names


def _authors_short(creators, limit=3):
    names = _creator_names(creators)
    if len(names) > limit:
        return ", ".join(names[:limit]) + " et al."
    return ", ".join(names)


def _short_text(value, limit=88):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _format_minutes(minutes):
    minutes = int(round(minutes or 0))
    if minutes <= 0:
        return "0m"
    hours, remain = divmod(minutes, 60)
    return ("%dh %dm" % (hours, remain)) if hours else "%dm" % remain


def _paper_keywords(meta):
    raw = meta.get("keywords") or meta.get("keyword") or meta.get("subjects") or []
    if isinstance(raw, str):
        raw = re.split(r"[,;|]", raw)
    values = [str(x).strip() for x in raw if str(x).strip()]
    if not values:
        match = re.search(r"(?im)^keywords?\s*:\s*(.+)$", str(meta.get("extra", "")))
        if match:
            values = [x.strip() for x in re.split(r"[,;|]", match.group(1)) if x.strip()]
    return values


def _md_table(value):
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")


def _wiki(path, label):
    return "[[%s|%s]]" % (str(path).replace("|", "－"), str(label).replace("|", "－"))


def _safe_part(value, fallback="Untitled"):
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "－", str(value or "")).strip().rstrip(". ")
    return value or fallback


def _collection_nodes(manifest, tree=None):
    nodes = {}
    cached = tree if tree is not None else (_common.load_collection_tree_cache() or [])
    for item in cached:
        if item.get("key"):
            nodes[item["key"]] = {"name": item.get("name", item["key"]), "parent": item.get("parent")}
    for paper in manifest.get("papers", []):
        for item in paper.get("collections", []):
            if isinstance(item, dict) and item.get("key"):
                nodes.setdefault(item["key"], {"name": item.get("name", item["key"]), "parent": item.get("parent")})
    return nodes


def _collection_path(paper, nodes, strict=False):
    collections = [c for c in paper.get("collections", []) if isinstance(c, dict)]
    selected = paper.get("selected_collection_key")
    if not selected and len(collections) == 1:
        selected = collections[0].get("key")
    if not selected:
        return ["Unfiled"]
    path, seen, current = [], set(), selected
    while current:
        if current in seen:
            raise RuntimeError("collection cycle for %s at %s" % (paper["zotero_key"], current))
        seen.add(current)
        node = nodes.get(current)
        if not node:
            direct = next((c for c in collections if c.get("key") == current), None)
            if direct:
                node = {"name": direct.get("name"), "parent": direct.get("parent")}
            elif strict:
                raise RuntimeError("missing collection %s for paper %s" % (current, paper["zotero_key"]))
            else:
                node = {"name": current, "parent": None}
        if strict and not node.get("name"):
            raise RuntimeError("missing collection name %s for paper %s" % (current, paper["zotero_key"]))
        path.append(_safe_part(node.get("name"), current))
        current = node.get("parent")
    return list(reversed(path)) or ["Unfiled"]


def desired_paths(manifest, tree=None, strict=False):
    nodes = _collection_nodes(manifest, tree)
    used = set()
    result = {}
    for paper in manifest.get("papers", []):
        key = paper["zotero_key"]
        title = _safe_part(paper.get("metadata", {}).get("title"), key)
        parts = ["Papers"] + _collection_path(paper, nodes, strict=strict)
        rel = Path(*parts) / (title + ".md")
        folded = str(rel).casefold()
        if folded in used:
            rel = Path(*parts) / (title + " — " + key + ".md")
        used.add(str(rel).casefold())
        result[key] = rel.as_posix()
    return result


def _attachment_rel(paper, manifest):
    """Mirror a paper note's collection/title path under Attachments."""
    note_rel = paper.get("obsidian_path") or desired_paths(manifest, strict=True)[paper["zotero_key"]]
    note_path = Path(note_rel)
    parts = list(note_path.parts)
    if parts and parts[0] == "Papers":
        parts = parts[1:]
    return (Path("Attachments") / Path(*parts)).with_suffix("")


def _attachment_rel_from_note(note_rel):
    note_path = Path(note_rel)
    parts = list(note_path.parts)
    if parts and parts[0] == "Papers":
        parts = parts[1:]
    return (Path("Attachments") / Path(*parts)).with_suffix("")


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attachment_copy_plan(old_dir, new_dir):
    plan = []
    if not old_dir.is_dir() or old_dir.resolve() == new_dir.resolve():
        return plan
    for source in old_dir.rglob("*"):
        if not source.is_file():
            continue
        target = new_dir / source.relative_to(old_dir)
        if target.exists():
            if _file_hash(source) != _file_hash(target):
                raise RuntimeError("attachment conflict: %s != %s" % (source, target))
        else:
            plan.append((source, target))
    return plan


def _remove_empty_parents(path, stop):
    current = path
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def prepare_paths():
    """Validate the full tree, then atomically migrate notes and attachments."""
    tree = _common.fetch_collection_tree()
    if tree is None:
        tree = _common.load_collection_tree_cache()
        if tree is None:
            raise RuntimeError("collection migration skipped: Zotero unavailable and no valid cache")
    else:
        _common.save_collection_tree_cache(tree)
    manifest = _common.load_manifest()
    paths = desired_paths(manifest, tree=tree, strict=True)
    operations = []
    for paper in manifest.get("papers", []):
        key = paper["zotero_key"]
        old_rel = paper.get("obsidian_path")
        old = (_common.OBSIDIAN_DIR / old_rel) if old_rel else (_common.OBSIDIAN_PAPERS_DIR / (key + ".md"))
        new = _common.OBSIDIAN_DIR / paths[key]
        if old.exists() and old.resolve() != new.resolve():
            result = sync_edits.sync_paper(key)
            if result.get("conflicts"):
                raise RuntimeError("cannot migrate %s with unresolved conflicts" % key)
            if new.exists():
                raise RuntimeError("refusing to overwrite existing note: %s" % new)
        old_attachment = _common.OBSIDIAN_DIR / _attachment_rel_from_note(old_rel or ("Papers/" + key + ".md"))
        new_attachment = _common.OBSIDIAN_DIR / _attachment_rel_from_note(paths[key])
        copy_plan = _attachment_copy_plan(old_attachment, new_attachment)
        operations.append((paper, old, new, old_attachment, new_attachment, copy_plan))

    moved, copied, manifest_changed = [], [], False
    try:
        for paper, old, new, old_attachment, new_attachment, copy_plan in operations:
            if old.exists() and old.resolve() != new.resolve():
                new.parent.mkdir(parents=True, exist_ok=True)
                old.replace(new)
                moved.append((old, new))
            for source, target in copy_plan:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append(target)
            desired = paths[paper["zotero_key"]]
            if paper.get("obsidian_path") != desired:
                paper["obsidian_path"] = desired
                manifest_changed = True
            collections = [c for c in paper.get("collections", []) if isinstance(c, dict)]
            if not paper.get("selected_collection_key") and len(collections) == 1:
                paper["selected_collection_key"] = collections[0].get("key")
                manifest_changed = True
        if manifest_changed:
            _common.save_manifest(manifest)
    except Exception:
        for target in reversed(copied):
            if target.exists():
                target.unlink()
        for old, new in reversed(moved):
            if new.exists() and not old.exists():
                old.parent.mkdir(parents=True, exist_ok=True)
                new.replace(old)
        raise

    for paper, old, new, old_attachment, new_attachment, copy_plan in operations:
        if old_attachment.is_dir() and old_attachment.resolve() != new_attachment.resolve():
            shutil.rmtree(old_attachment)
            _remove_empty_parents(old_attachment.parent, _common.OBSIDIAN_DIR / "Attachments")
        _remove_empty_parents(old.parent, _common.OBSIDIAN_PAPERS_DIR)
    return paths


def _project_for(paper):
    pid = paper.get("research_context_id")
    return next((p for p in _common.load_research_projects().get("projects", []) if p.get("id") == pid), None) if pid else None


def _field(value):
    if isinstance(value, list):
        return "\n".join("%d. %s" % (i + 1, item) for i, item in enumerate(value))
    return str(value or "")


def _source_section_numbers(key):
    """Backfill source numbering for legacy sections.json, as HTML does."""
    raw = _load_json(_common.PAPERS_DIR / (key + ".section_text.json"), {})
    numbers, pending = {}, None
    for item in raw.get("sections", []):
        heading = str(item.get("heading", "")).strip()
        if item.get("number"):
            numbers[heading] = str(item["number"]).rstrip(".")
        if re.fullmatch(r"\d+(?:\.\d+)*\.?", heading):
            pending = heading.rstrip(".")
        elif pending:
            numbers[heading] = pending
            pending = None
    return numbers


def build_paper(key):
    manifest = _common.load_manifest()
    paper = next((p for p in manifest.get("papers", []) if p.get("zotero_key") == key), None)
    if not paper:
        raise ValueError("paper %s not found" % key)
    summary = _load_json(_common.PAPERS_DIR / (key + ".summary.json"), {})
    sections = _load_json(_common.PAPERS_DIR / (key + ".sections.json"), {"sections": []}).get("sections", [])
    annotations = _load_json(_common.PAPERS_DIR / (key + ".annotations.json"), {})
    guide = summary.get("reading_guide", {}) if isinstance(summary.get("reading_guide"), dict) else {}
    meta = paper.get("metadata", {})
    project = _project_for(paper)
    research_name = project.get("name") if project else None
    collections = [c.get("name", "") for c in paper.get("collections", []) if isinstance(c, dict) and c.get("name")]

    lines = ["---", "title: " + _yaml_scalar(meta.get("title"))]
    lines += _yaml_list("authors", _creator_names(meta.get("creators", [])))
    year = meta.get("publicationYear")
    lines += ["year: " + _yaml_scalar(str(year) if year not in (None, "") else None),
              "venue: " + _yaml_scalar(meta.get("venue")),
              "zotero_key: " + _yaml_scalar(key)]
    lines += _yaml_list("collections", collections)
    lines += ["doi: " + _yaml_scalar(meta.get("DOI")),
              "highlights: " + str(int(paper.get("annotation_count", 0))),
              "reading_time: " + _yaml_scalar(_format_minutes(paper.get("reading_time_minutes", 0))),
              "status: " + _yaml_scalar(paper.get("status", "reading")),
              "research_context: " + _yaml_scalar(research_name)]
    lines += _yaml_list("keywords", _paper_keywords(meta))
    lines += _yaml_block("abstract", meta.get("abstractNote"))
    lines += ["---", "", "[[Dashboard|← Dashboard]]", "", "## 论文速览", "",
              "### 研究背景", _field(guide.get("background", summary.get("background_and_gap", ""))), "",
              "### 研究目标", _field(guide.get("question", summary.get("research_question", ""))), "",
              "### 研究内容", _field(guide.get("approach", summary.get("method_or_design", ""))), "",
              "### 主要结论", _field(guide.get("main_findings", summary.get("results_or_claims", ""))), "",
              "### 主要洞见", _field(guide.get("insight", summary.get("interpretation", ""))), "",
              "## 原文精读", "", "### 分章节总结与分析", ""]
    source_numbers = _source_section_numbers(key)
    for i, section in enumerate(sections):
        level = max(4, min(6, int(section.get("level", 2)) + 2))
        raw_heading = str(section.get("heading", "Section")).strip()
        match = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+(.+)$", raw_heading)
        number = (str(section.get("number") or "").rstrip(".") or
                  (match.group(1) if match else "") or source_numbers.get(raw_heading, ""))
        heading = match.group(2) if match else raw_heading
        display_heading = ((number + " ") if number else "") + heading
        lines += ["%s %s" % ("#" * level, display_heading), "_p.%s_" % section.get("page", ""),
                  "**总结**", _field(section.get("summary", "")), "",
                  "**分析**", _field(section.get("analysis", "")), ""]
    quotes = summary.get("key_quotes", []) or []
    lines += ["### 关键引文", ""]
    for i, quote in enumerate(quotes):
        lines += ["#### 引文 %d" % (i + 1), "",
                  "页码：%s；颜色：%s" % (quote.get("page", ""), quote.get("color", "")), "",
                  "##### 原文", _field(quote.get("text", "")), "",
                  "##### 说明", _field(quote.get("note", quote.get("explanation", ""))), ""]
    fig_manifest = _load_json(_common.PAPERS_DIR / (key + "_images") / "manifest.json", {})
    attachment_rel = _attachment_rel(paper, manifest).as_posix()
    lines += ["### 论文图表", ""]
    for fig in fig_manifest.get("figures", []):
        if fig.get("filename"):
            lines += ["![[%s/%s]]" % (attachment_rel, fig["filename"]), "", fig.get("caption", ""), ""]
    lines += ["### Zotero 高亮", ""]
    for ann in annotations.get("annotations", []):
        if ann.get("type") == "highlight" or ann.get("annotation_type") == "highlight":
            lines += ["> " + (ann.get("text") or ann.get("annotation_text") or ""), ""]
    lines += ["### Zotero 笔记", ""]
    for note in annotations.get("notes", []):
        lines += ["- " + str(note.get("note", note) if isinstance(note, dict) else note)]
    lines += ["", "## 参考意义", "", "### 风险与威胁",
              _field(summary.get("limitations_and_threats", [])), "",
              "### 总体局限", _field(guide.get("limitations", "")), "",
              "### 成本与复现条件", _field(summary.get("reproduction_conditions", "")), "",
              "### 与我研究的关联", _field(summary.get("relevance_to_my_work", "")), "",
              "### 待追问", _field(summary.get("open_questions", [])), "",
              "### 我的笔记", _field(summary.get("custom_notes", "")), ""]
    return "\n".join(lines).rstrip() + "\n"


def build_research(project):
    lines = ["---", "research_id: " + _yaml_scalar(project.get("id")),
             "status: " + _yaml_scalar(project.get("status")), "---", "",
             "[[Dashboard|← Dashboard]]", "",
             "## 研究问题", "", project.get("research_question", ""), "", "## 背景与动机", "", project.get("background", ""), "",
             "## 方法或设计", "", project.get("method_or_design", ""), "", "## 数据或材料", "", project.get("data_or_materials", ""), "",
             "## 当前难点", "", project.get("current_challenges", ""), "", "## 关键词", "",
             ", ".join(project.get("keywords", []))]
    return "\n".join(lines).rstrip() + "\n"


def _research_paths(projects):
    used, paths = set(), {}
    for project in projects:
        stem = _safe_part(project.get("name"), project["id"])
        filename = stem + ".md"
        if filename.casefold() in used:
            filename = stem + " — " + project["id"] + ".md"
        used.add(filename.casefold())
        paths[project["id"]] = filename
    return paths


def _write_research_pages(projects):
    _common.OBSIDIAN_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    paths = _research_paths(projects)
    for project in projects:
        target = _common.OBSIDIAN_RESEARCH_DIR / paths[project["id"]]
        legacy = _common.OBSIDIAN_RESEARCH_DIR / (project["id"] + ".md")
        if legacy.exists() and legacy.name != target.name:
            if legacy.name.casefold() == target.name.casefold():
                temporary = _common.OBSIDIAN_RESEARCH_DIR / (project["id"] + ".rename-tmp")
                legacy.replace(temporary)
                temporary.replace(target)
            elif not target.exists():
                legacy.replace(target)
            elif not legacy.samefile(target):
                legacy.unlink()
        if not target.exists():
            target.write_text(build_research(project), encoding="utf-8")


def _heatmap_data(papers):
    days = {}
    for paper in papers:
        for item in paper.get("reading_by_day", []):
            if item.get("date"):
                days[item["date"]] = days.get(item["date"], 0) + int(item.get("minutes", 0))
    return days


def build_heatmap_svg(papers, accent):
    colors = ACCENTS.get(accent, ACCENTS["blue"])
    today = datetime.now().date()
    end = today
    start = end - timedelta(days=364)
    grid_start = start - timedelta(days=(start.weekday() + 1) % 7)  # Sunday
    cell, gap, left, top = 12, 3, 42, 28
    width, height = left + 53 * (cell + gap) + 12, 148
    days = _heatmap_data(papers)
    max_minutes = max(days.values()) if days else 1
    rects = []
    cursor = grid_start
    while cursor <= end:
        if cursor >= start:
            week = (cursor - grid_start).days // 7
            row = (cursor.weekday() + 1) % 7
            minutes = days.get(cursor.isoformat(), 0)
            level = 0 if minutes <= 0 else min(4, max(1, int((minutes / max_minutes) * 4 + 0.999)))
            x, y = left + week * (cell + gap), top + row * (cell + gap)
            rects.append('<rect x="%d" y="%d" width="%d" height="%d" rx="2" fill="%s"><title>%s · %d min</title></rect>' %
                         (x, y, cell, cell, colors[level], cursor.isoformat(), minutes))
        cursor += timedelta(days=1)
    month_labels, seen = [], set()
    cursor = start
    while cursor <= end:
        key = (cursor.year, cursor.month)
        if key not in seen:
            seen.add(key)
            week = (cursor - grid_start).days // 7
            month_labels.append('<text x="%d" y="16">%s</text>' % (left + week * (cell + gap), cursor.strftime("%b")))
        cursor += timedelta(days=1)
    legend = []
    for i, color in enumerate(colors):
        legend.append('<rect x="%d" y="126" width="10" height="10" rx="2" fill="%s"/>' % (width - 105 + i * 14, color))
    return ("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"%d\" height=\"%d\" viewBox=\"0 0 %d %d\">"
            "<style>text{font:10px -apple-system,BlinkMacSystemFont,sans-serif;fill:#7E756D}</style>"
            "%s<text x=\"8\" y=\"57\">Mon</text><text x=\"8\" y=\"87\">Wed</text><text x=\"8\" y=\"117\">Fri</text>"
            "%s<text x=\"%d\" y=\"135\">Less</text>%s<text x=\"%d\" y=\"135\">More</text></svg>" %
            (width, height, width, height, "".join(month_labels), "".join(rects), width - 133, "".join(legend), width - 27))


def build_dashboard():
    manifest = _common.load_manifest()
    projects = _common.load_research_projects().get("projects", [])
    research_paths = _research_paths(projects)
    papers = [p for p in manifest.get("papers", []) if p.get("status") != "archived"]
    lines = ["## 我的研究", ""]
    if projects:
        lines += ["| 研究 | 状态 | 核心问题 | 关键词 |",
                  "|---|---|---|---|"]
        for project in projects:
            link = _wiki("Research/" + Path(research_paths[project["id"]]).stem,
                         project.get("name", project["id"]))
            keywords = " · ".join(str(x) for x in (project.get("keywords") or [])[:5])
            row = [link, project.get("status", "active"),
                   _short_text(project.get("research_question")), keywords]
            lines.append("| " + " | ".join(_md_table(value) for value in row) + " |")
        lines.append("")
    else:
        lines += ["暂无研究方向。需要添加时，请在对话中介绍你的研究目标与当前进展。", ""]
    total_minutes = sum(p.get("reading_time_minutes", 0) for p in papers)
    lines += ["## 阅读统计", "", "| 论文 | 阅读中 | 已完成 | 高亮 | 近似阅读时长 |",
              "|---:|---:|---:|---:|---:|",
              "| %d | %d | %d | %d | %s |" % (len(papers), sum(p.get("status") == "reading" for p in papers),
               sum(p.get("status") == "done" for p in papers), sum(p.get("annotation_count", 0) for p in papers), _format_minutes(total_minutes)),
              "", "## 阅读热力图", "", "![[Attachments/dashboard-reading-heatmap.svg]]", ""]
    heat_days = _heatmap_data(papers)
    today = datetime.now().date()
    start = today - timedelta(days=364)
    year_days = {d: m for d, m in heat_days.items() if d >= start.isoformat() and d <= today.isoformat() and m > 0}
    lines += ["过去一年共记录 **%d** 个阅读日，近似阅读 **%s**。" % (len(year_days), _format_minutes(sum(year_days.values()))), "",
              "## 论文列表", "", "| 论文 | 作者 | 年份 | 出版物 | Collection | 状态 | 高亮 | 阅读时长 |",
              "|---|---|---:|---|---|---|---:|---:|"]
    nodes = _collection_nodes(manifest)
    for paper in papers:
        meta = paper.get("metadata", {})
        rel = paper.get("obsidian_path") or desired_paths(manifest).get(paper["zotero_key"], "")
        link = _wiki(rel[:-3] if rel.endswith(".md") else rel, meta.get("title", ""))
        collection = " / ".join(_collection_path(paper, nodes))
        row = [_authors_short(meta.get("creators", [])), meta.get("publicationYear", ""), meta.get("venue", ""),
               collection, paper.get("status", ""), paper.get("annotation_count", 0), _format_minutes(paper.get("reading_time_minutes", 0))]
        lines.append("| " + _md_table(link) + " | " + " | ".join(_md_table(v) for v in row) + " |")
    return "\n".join(lines).rstrip() + "\n"


def write_all(key=None):
    _common.ensure_obsidian_dirs()
    manifest = _common.load_manifest()
    attachments = _common.OBSIDIAN_DIR / "Attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    selected = [p for p in manifest.get("papers", []) if key is None or p.get("zotero_key") == key]
    missing_paths = any(not p.get("obsidian_path") for p in selected)
    paths = desired_paths(manifest, strict=True) if missing_paths else {}
    for paper in selected:
        pkey = paper["zotero_key"]
        rel = paper.get("obsidian_path") or paths[pkey]
        out = _common.OBSIDIAN_DIR / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        rendered = build_paper(pkey)
        if out.exists():
            existing = out.read_text(encoding="utf-8")
            refreshed = _replace_frontmatter(existing, rendered)
            if refreshed != existing:
                out.write_text(refreshed, encoding="utf-8")
        else:
            out.write_text(rendered, encoding="utf-8")
        src = _common.PAPERS_DIR / (pkey + "_images")
        dst = _common.OBSIDIAN_DIR / _attachment_rel(paper, manifest)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            legacy = attachments / pkey
            if legacy.is_dir() and legacy.resolve() != dst.resolve():
                shutil.rmtree(legacy)
    _write_research_pages(_common.load_research_projects().get("projects", []))
    (attachments / "dashboard-reading-heatmap.svg").write_text(
        build_heatmap_svg([p for p in manifest.get("papers", []) if p.get("status") != "archived"], _common.load_config().get("default_accent", "blue")), encoding="utf-8")
    _common.OBSIDIAN_DASHBOARD_PATH.write_text(build_dashboard(), encoding="utf-8")


def write_dashboard_only():
    _common.ensure_obsidian_dirs()
    manifest = _common.load_manifest()
    attachments = _common.OBSIDIAN_DIR / "Attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    _write_research_pages(_common.load_research_projects().get("projects", []))
    (attachments / "dashboard-reading-heatmap.svg").write_text(
        build_heatmap_svg([p for p in manifest.get("papers", []) if p.get("status") != "archived"],
                          _common.load_config().get("default_accent", "blue")), encoding="utf-8")
    _common.OBSIDIAN_DASHBOARD_PATH.write_text(build_dashboard(), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Build Obsidian paper-notes vault")
    ap.add_argument("--key")
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--prepare-paths", action="store_true", help="explicitly migrate/persist title-based collection paths")
    ap.add_argument("--dashboard-only", action="store_true")
    args = ap.parse_args()
    if args.dashboard_only:
        write_dashboard_only()
    elif args.stdout:
        sys.stdout.write(build_paper(args.key) if args.key else build_dashboard())
    else:
        manifest = _common.load_manifest()
        for paper in manifest.get("papers", []):
            if args.key is None or paper.get("zotero_key") == args.key:
                if sync_edits._paper_markdown_path(paper):
                    sync_edits.sync_paper(paper["zotero_key"])
        sync_edits.sync_research()
        if args.prepare_paths:
            prepare_paths()
        write_all(args.key)
        sys.stderr.write("Wrote %s\n" % _common.OBSIDIAN_DIR)


if __name__ == "__main__":
    main()
