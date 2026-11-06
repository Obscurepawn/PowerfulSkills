"""Behavior checks for architecture validation and portable rendering."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "render_architecture.py"


def load_module():
    spec = importlib.util.spec_from_file_location("render_architecture", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example():
    return {
        "title": "Example request path", "data_kind": "proposed",
        "source": "Illustrative design for renderer validation",
        "boundaries": [{"id": "backend", "label": "Backend process"}],
        "nodes": [{"id": "client", "label": "Client"},
                  {"id": "api", "label": "API", "boundary": "backend"}],
        "edges": [{"from": "client", "to": "api", "kind": "sync", "label": "HTTP request"}],
    }


class ArchitectureContractTests(unittest.TestCase):
    def setUp(self):
        self.renderer = load_module()

    def test_unknown_endpoint_is_rejected(self):
        spec = example()
        spec["edges"][0]["to"] = "missing"
        with self.assertRaisesRegex(ValueError, "endpoint"):
            self.renderer.validate_spec(spec)

    def test_duplicate_node_is_rejected(self):
        spec = example()
        spec["nodes"].append(copy.deepcopy(spec["nodes"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.renderer.validate_spec(spec)

    def test_observed_edges_and_nodes_require_evidence(self):
        spec = example()
        spec["data_kind"] = "observed"
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.renderer.validate_spec(spec)
        for node in spec["nodes"]:
            node["evidence"] = "repository abc123: app.py:10"
        for edge in spec["edges"]:
            edge["evidence"] = "repository abc123: client.py:20"
        self.renderer.validate_spec(spec)

    def test_unknown_boundary_and_injected_attributes_are_rejected(self):
        for mutate in (lambda s: s["nodes"][0].update(boundary="missing"),
                       lambda s: s["nodes"][0].update(image="/private/file.png")):
            spec = example()
            mutate(spec)
            with self.assertRaises(ValueError):
                self.renderer.validate_spec(spec)

    def test_wrong_endpoint_and_boundary_types_are_rejected_cleanly(self):
        for mutate in (lambda s: s["edges"][0].update({"from": []}),
                       lambda s: s["edges"][0].update({"kind": {}}),
                       lambda s: s["nodes"][0].update({"boundary": []})):
            spec = example()
            mutate(spec)
            with self.assertRaises(ValueError):
                self.renderer.validate_spec(spec)

    def test_nonempty_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            out.mkdir()
            sentinel = out / "keep.txt"
            sentinel.write_text("user content")
            src = Path(td) / "spec.json"
            src.write_text(json.dumps(example()))
            with self.assertRaisesRegex(ValueError, "nonempty"):
                self.renderer.render(src, out)
            self.assertEqual(sentinel.read_text(), "user content")

    @unittest.skipUnless(shutil.which("dot"), "Graphviz dot not available")
    def test_render_bundle_is_editable_hashed_and_replayable(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "spec.json"
            spec = example()
            spec["nodes"][0]["label"] = 'Client "quoted" \\N <literal>'
            src.write_text(json.dumps(spec), encoding="utf-8")
            out = Path(td) / "bundle"
            self.renderer.render(src, out)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["kind"], "architecture")
            self.assertIn("<text", (out / "architecture.svg").read_text())
            self.assertIn("PROPOSED", (out / "architecture.svg").read_text())
            self.assertTrue((out / "architecture.pdf").read_bytes().startswith(b"%PDF-"))
            self.assertTrue((out / "architecture.png").read_bytes().startswith(b"\x89PNG"))
            for item in manifest["inputs"] + manifest["outputs"]:
                self.assertEqual(hashlib.sha256((out / item["path"]).read_bytes()).hexdigest(), item["sha256"])
            replay = [sys.executable] + manifest["command"][1:]
            result = subprocess.run(replay, cwd=out, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((out / "architecture.dot").read_text(), (out / "replay" / "architecture.dot").read_text())


if __name__ == "__main__":
    unittest.main()
