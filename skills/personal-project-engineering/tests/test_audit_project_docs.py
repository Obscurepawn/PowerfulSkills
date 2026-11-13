"""Unit tests for personal-project-engineering document auditor."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_project_docs import audit_repo


class AuditProjectDocsTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.repo = Path(td.name)

    def test_clean_repo_passes(self):
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "guide.md").write_text("# Setup Guide\n\nDetails.\n", encoding="utf-8")
        (self.repo / "package.json").write_text(json.dumps({"scripts": {"test": "pytest"}}), encoding="utf-8")
        (self.repo / "README.md").write_text(
            "# Demo\n\nSee [Guide](docs/guide.md#setup-guide).\n\n```sh\nnpm run test\n```\n",
            encoding="utf-8",
        )
        report = audit_repo(self.repo)
        self.assertEqual(report["issue_count"], 0, report["issues"])

    def test_detects_dead_links_anchors_placeholders_and_missing_npm_scripts(self):
        (self.repo / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
        (self.repo / "README.md").write_text(
            "# {{项目名}}\n\n"
            "See [Missing](docs/missing.md) and [Bad Anchor](#nonexistent).\n\n"
            "```sh\nnpm run test-e2e\n```\n",
            encoding="utf-8",
        )
        report = audit_repo(self.repo)
        checks = {item["check"] for item in report["issues"]}
        self.assertEqual(checks, {"placeholder", "dead-link", "dead-anchor", "npm-script"})


if __name__ == "__main__":
    unittest.main()
