import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _common
import manage_reading_list


class OutputLayoutTest(unittest.TestCase):
    def test_legacy_html_artifacts_migrate_under_html(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            papers = root / "papers"
            papers.mkdir()
            (root / "dashboard.html").write_text("dashboard", encoding="utf-8")
            (papers / "ABCDEFGH.html").write_text("paper", encoding="utf-8")
            (root / "research").mkdir()
            (root / "research" / "Demo.html").write_text("research", encoding="utf-8")
            (root / "fonts").mkdir()
            (root / "fonts" / "fonts.css").write_text("fonts", encoding="utf-8")

            html = root / "html"
            values = {
                "OUTPUT_DIR": root,
                "PAPERS_DIR": papers,
                "HTML_DIR": html,
                "HTML_PAPERS_DIR": html / "papers",
                "HTML_RESEARCH_DIR": html / "research",
                "DASHBOARD_PATH": html / "dashboard.html",
                "FONTS_DST": html / "fonts",
            }
            with patch.multiple(_common, **values):
                _common.ensure_output_dirs()

            self.assertEqual((html / "dashboard.html").read_text(), "dashboard")
            self.assertEqual((html / "papers/ABCDEFGH.html").read_text(), "paper")
            self.assertEqual((html / "research/Demo.html").read_text(), "research")
            self.assertEqual((html / "fonts/fonts.css").read_text(), "fonts")
            self.assertFalse((root / "dashboard.html").exists())
            self.assertFalse((papers / "ABCDEFGH.html").exists())

    def test_figures_are_copied_into_html_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            papers = root / "papers"
            html_papers = root / "html/papers"
            source = papers / "ABCDEFGH_images"
            source.mkdir(parents=True)
            (source / "figure.png").write_bytes(b"figure")
            with patch.multiple(
                _common,
                PAPERS_DIR=papers,
                HTML_PAPERS_DIR=html_papers,
            ):
                _common.copy_html_figures("ABCDEFGH")
            self.assertEqual(
                (html_papers / "ABCDEFGH_images/figure.png").read_bytes(), b"figure"
            )

    def test_zotero_free_obsidian_rebuild_skips_collection_migration(self):
        calls = []
        with patch.object(
            _common, "load_config",
            return_value={"output_mode": "obsidian", "connect_zotero": False},
        ), patch.object(manage_reading_list, "_run_script",
                        side_effect=lambda script, *args: calls.append((script, args))):
            manage_reading_list._rebuild_outputs(sync_first=False)

        self.assertEqual(calls, [(manage_reading_list.BUILD_MARKDOWN, ())])

    def test_remove_cleans_titled_obsidian_note_attachments_and_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            papers = root / "papers"
            obsidian = root / "obsidian"
            html_papers = root / "html/papers"
            values = {
                "OUTPUT_DIR": root,
                "PAPERS_DIR": papers,
                "MANIFEST_PATH": root / "reading-list.json",
                "HTML_DIR": root / "html",
                "HTML_PAPERS_DIR": html_papers,
                "HTML_RESEARCH_DIR": root / "html/research",
                "DASHBOARD_PATH": root / "html/dashboard.html",
                "FONTS_DST": root / "html/fonts",
                "OBSIDIAN_DIR": obsidian,
                "OBSIDIAN_PAPERS_DIR": obsidian / "Papers",
                "OBSIDIAN_RESEARCH_DIR": obsidian / "Research",
                "OBSIDIAN_DASHBOARD_PATH": obsidian / "Dashboard.md",
                "CONFIG_PATH": root / "litreader.config.json",
            }
            with patch.multiple(_common, **values), patch.object(
                manage_reading_list, "_rebuild_outputs"
            ):
                _common.ensure_output_dirs()
                note_rel = "Papers/Collection/Paper title.md"
                note = obsidian / note_rel
                note.parent.mkdir(parents=True)
                note.write_text("note", encoding="utf-8")
                attachment = obsidian / "Attachments/Collection/Paper title/figure.png"
                attachment.parent.mkdir(parents=True)
                attachment.write_bytes(b"figure")
                state = papers / "ABCDEFGH.field-state.json"
                state.write_text("{}", encoding="utf-8")
                _common.MANIFEST_PATH.write_text(
                    '{"papers":[{"zotero_key":"ABCDEFGH",'
                    '"obsidian_path":"Papers/Collection/Paper title.md"}]}',
                    encoding="utf-8",
                )

                manage_reading_list.cmd_remove(
                    Namespace(key="ABCDEFGH", keep_edits=False)
                )

                self.assertFalse(note.exists())
                self.assertFalse(attachment.parent.exists())
                self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
