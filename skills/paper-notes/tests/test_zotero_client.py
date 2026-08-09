import argparse
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _common
import zotero


class BundledZoteroClientTest(unittest.TestCase):
    def test_bundled_path_and_read_only_command_surface(self):
        self.assertEqual(_common.zotero_py_path(), SCRIPTS / "zotero.py")
        self.assertTrue(_common.zotero_py_path().is_file())
        self.assertEqual(zotero.COMMANDS, ("search", "get"))
        help_text = zotero.build_parser().format_help()
        for forbidden in ("delete", "update", "add-doi", "fetch-pdfs", "upload"):
            self.assertNotIn(forbidden, help_text)

    def test_search_json_matches_existing_wrapper_contract(self):
        args = argparse.Namespace(
            query="paper", limit=5, sort="relevance", type=None, json=True
        )
        response = ([
            {"data": {"key": "ABCDEFGH", "itemType": "journalArticle", "title": "Paper"}},
            {"data": {"key": "IJKLMNOP", "itemType": "attachment", "title": "PDF"}},
        ], {"Total-Results": "2"})
        output = io.StringIO()
        with patch.object(_common, "get_zotero_config", return_value=("key", "/users/1")), \
             patch.object(_common, "api_get_json", return_value=response), \
             redirect_stdout(output):
            zotero.cmd_search(args)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["total"], "2")
        self.assertEqual([item["key"] for item in payload["items"]], ["ABCDEFGH"])

    def test_get_json_returns_item_data(self):
        args = argparse.Namespace(key="ABCDEFGH", json=True)
        response = ({"data": {"key": "ABCDEFGH", "title": "Paper", "collections": ["COLL0001"]}}, {})
        output = io.StringIO()
        with patch.object(_common, "get_zotero_config", return_value=("key", "/users/1")), \
             patch.object(_common, "api_get_json", return_value=response), \
             redirect_stdout(output):
            zotero.cmd_get(args)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["key"], "ABCDEFGH")
        self.assertEqual(payload["collections"], ["COLL0001"])


if __name__ == "__main__":
    unittest.main()
