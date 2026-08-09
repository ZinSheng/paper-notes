import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _common
import build_markdown
import manage_reading_list
import sync_edits


class MarkdownSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        _common.OUTPUT_DIR = root
        _common.PAPERS_DIR = root / "papers"
        _common.MANIFEST_PATH = root / "reading-list.json"
        _common.RESEARCH_PATH = root / "research-projects.json"
        _common.HTML_DIR = root / "html"
        _common.HTML_PAPERS_DIR = _common.HTML_DIR / "papers"
        _common.HTML_RESEARCH_DIR = _common.HTML_DIR / "research"
        _common.DASHBOARD_PATH = _common.HTML_DIR / "dashboard.html"
        _common.FONTS_DST = _common.HTML_DIR / "fonts"
        _common.OBSIDIAN_DIR = root / "obsidian"
        _common.OBSIDIAN_PAPERS_DIR = _common.OBSIDIAN_DIR / "Papers"
        _common.OBSIDIAN_RESEARCH_DIR = _common.OBSIDIAN_DIR / "Research"
        _common.OBSIDIAN_DASHBOARD_PATH = _common.OBSIDIAN_DIR / "Dashboard.md"
        _common.CONFIG_PATH = root / "litreader.config.json"
        _common.ensure_output_dirs()
        _common.ensure_obsidian_dirs()
        self.key = "ABCDEFGH"
        self.paper = {"zotero_key": self.key, "status": "reading",
                      "obsidian_path": "Papers/Paper.md",
                      "metadata": {"title": "Paper", "creators": []}}
        _common.MANIFEST_PATH.write_text(json.dumps({"papers": [self.paper]}), encoding="utf-8")
        summary = {
            "reading_guide": {"background": "old background", "question": "question",
                              "approach": "approach", "main_findings": "findings",
                              "insight": "insight", "limitations": "limits"},
            "limitations_and_threats": ["risk"], "reproduction_conditions": "cost",
            "relevance_to_my_work": "relevance", "open_questions": ["open"],
            "custom_notes": "notes", "key_quotes": [{"text": "quote", "note": "note"}],
        }
        sections = {"sections": [{"heading": "1 Intro", "level": 2,
                                  "summary": "section summary", "analysis": "section analysis"}]}
        (_common.PAPERS_DIR / (self.key + ".summary.json")).write_text(json.dumps(summary), encoding="utf-8")
        (_common.PAPERS_DIR / (self.key + ".sections.json")).write_text(json.dumps(sections), encoding="utf-8")
        note = _common.OBSIDIAN_DIR / self.paper["obsidian_path"]
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(build_markdown.build_paper(self.key), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_paper_markdown_is_authoritative_and_custom_content_survives(self):
        path = _common.OBSIDIAN_DIR / self.paper["obsidian_path"]
        text = path.read_text(encoding="utf-8")
        text = text.replace("old background", "edited **background** with $x_i$")
        text = text.replace("### 成本与复现条件\ncost", "### 用户改名的成本\ncost")
        text += "\n## 我的自定义章节\n\nkeep me\n"
        path.write_text(text, encoding="utf-8")

        result = sync_edits.sync_paper(self.key)
        summary = json.loads((_common.PAPERS_DIR / (self.key + ".summary.json")).read_text())
        self.assertEqual(summary["reading_guide"]["background"], "edited **background** with $x_i$")
        self.assertEqual(summary["reproduction_conditions"], "")
        self.assertIn("cost", result["cleared_fields"])
        build_markdown.write_all(self.key)
        self.assertIn("我的自定义章节", path.read_text(encoding="utf-8"))

    def test_duplicate_heading_is_ambiguous_and_preserves_json(self):
        path = _common.OBSIDIAN_DIR / self.paper["obsidian_path"]
        text = path.read_text(encoding="utf-8") + "\n### 研究背景\n\nduplicate\n"
        path.write_text(text, encoding="utf-8")
        result = sync_edits.sync_paper(self.key)
        summary = json.loads((_common.PAPERS_DIR / (self.key + ".summary.json")).read_text())
        self.assertEqual(summary["reading_guide"]["background"], "old background")
        self.assertIn("guide_background", result["ambiguous_fields"])

    def test_existing_note_refreshes_research_frontmatter_and_preserves_body(self):
        project = {"id": "project-a", "name": "Project A", "status": "active"}
        _common.RESEARCH_PATH.write_text(json.dumps({"projects": [project]}), encoding="utf-8")
        manifest = json.loads(_common.MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["papers"][0]["research_context_id"] = "project-a"
        _common.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")
        path = _common.OBSIDIAN_DIR / self.paper["obsidian_path"]
        path.write_text(path.read_text(encoding="utf-8") + "\n## User section\n\nkeep me\n",
                        encoding="utf-8")

        build_markdown.write_all(self.key)

        text = path.read_text(encoding="utf-8")
        self.assertIn('research_context: "Project A"', text)
        self.assertIn("## User section\n\nkeep me", text)

    def test_section_and_quote_children_round_trip(self):
        path = _common.OBSIDIAN_DIR / self.paper["obsidian_path"]
        text = path.read_text(encoding="utf-8")
        text = text.replace("section summary", "edited section summary")
        text = text.replace("section analysis", "edited section analysis")
        text = text.replace("##### 原文\nquote", "##### 原文\nverbatim edited quote")
        text = text.replace("##### 说明\nnote", "##### 说明\nquote explanation")
        path.write_text(text, encoding="utf-8")
        sync_edits.sync_paper(self.key)
        sections = json.loads((_common.PAPERS_DIR / (self.key + ".sections.json")).read_text())
        summary = json.loads((_common.PAPERS_DIR / (self.key + ".summary.json")).read_text())
        self.assertEqual(sections["sections"][0]["summary"], "edited section summary")
        self.assertEqual(sections["sections"][0]["analysis"], "edited section analysis")
        self.assertEqual(summary["key_quotes"][0]["text"], "verbatim edited quote")
        self.assertEqual(summary["key_quotes"][0]["note"], "quote explanation")

    def test_legacy_markers_are_consumed_and_removed(self):
        path = _common.OBSIDIAN_DIR / self.paper["obsidian_path"]
        text = path.read_text(encoding="utf-8")
        text = text.replace("old background",
                            "%% paper-notes:field:guide_background:start %%\nlegacy edit\n"
                            "%% paper-notes:field:guide_background:end %%")
        path.write_text(text, encoding="utf-8")
        sync_edits.sync_paper(self.key)
        summary = json.loads((_common.PAPERS_DIR / (self.key + ".summary.json")).read_text())
        self.assertEqual(summary["reading_guide"]["background"], "legacy edit")
        self.assertNotIn("%% paper-notes:field", path.read_text(encoding="utf-8"))

    def test_research_markdown_updates_project(self):
        project = {"id": "project-a", "name": "Project A", "status": "active",
                   "research_question": "old", "background": "b", "method_or_design": "m",
                   "data_or_materials": "d", "current_challenges": "c", "keywords": ["k"],
                   "field_updated_at": {}}
        _common.RESEARCH_PATH.write_text(json.dumps({"projects": [project]}), encoding="utf-8")
        path = _common.OBSIDIAN_RESEARCH_DIR / "Project A.md"
        page = build_markdown.build_research(project).replace("research_id: \"project-a\"\n", "")
        path.write_text(page.replace("\nold\n", "\nnew question\n"), encoding="utf-8")
        result = sync_edits.sync_research()
        saved = json.loads(_common.RESEARCH_PATH.read_text())["projects"][0]
        self.assertTrue(result["changed"])
        self.assertEqual(saved["research_question"], "new question")
        self.assertIn("research_question", saved["field_updated_at"])
        self.assertIn('research_id: "project-a"', path.read_text(encoding="utf-8"))

    def test_research_context_prompt_follows_setting(self):
        project = {"id": "project-a", "name": "Project A", "status": "active",
                   "research_question": "Question"}
        _common.RESEARCH_PATH.write_text(json.dumps({"projects": [project]}), encoding="utf-8")
        cfg = dict(_common.DEFAULT_CONFIG, initialized=True, use_research_context=True)
        _common.save_config(cfg)
        output = io.StringIO()
        with redirect_stdout(output):
            ready = manage_reading_list._research_selection_ready(None)
        response = json.loads(output.getvalue())
        self.assertFalse(ready)
        self.assertEqual(response["next_step"], "repeat_add_with_research")
        self.assertEqual(response["research_projects"][0]["id"], "project-a")
        self.assertTrue(manage_reading_list._research_selection_ready("none"))
        self.assertTrue(manage_reading_list._research_selection_ready("project-a"))

        cfg["use_research_context"] = False
        _common.save_config(cfg)
        self.assertTrue(manage_reading_list._research_selection_ready(None))


if __name__ == "__main__":
    unittest.main()
