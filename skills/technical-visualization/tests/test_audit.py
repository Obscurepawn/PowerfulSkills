"""Behavioral checks for portable bundles and rendered-artifact validation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_bundle import audit_bundle


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        svg = self.root / 'figure.svg'
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text x="5" y="20">Label</text></svg>')
        source = self.root / 'source.py'
        source.write_text('# reproducible source\n')
        self.manifest = {
            'schema_version': 1, 'kind': 'benchmark', 'data_kind': 'observed',
            'inputs': [self.entry(source, role='code')],
            'outputs': [self.entry(svg)], 'parameters': {},
            'environment': {'python': 'test'}, 'command': ['python', 'source.py'],
            'warnings': [], 'checks': {},
        }

    def entry(self, path, **extra):
        return dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **extra)

    def audit(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        return audit_bundle(self.root)

    def test_changed_input_fails_integrity(self):
        (self.root / 'source.py').write_text('changed')
        result = self.audit()
        self.assertEqual(result['automatic_status'], 'fail')
        self.assertTrue(any(i['check'] == 'sha256' for i in result['issues']))

    def test_paths_cannot_escape_bundle(self):
        self.manifest['inputs'][0]['path'] = '../outside.py'
        self.assertTrue(any(i['check'] == 'path' for i in self.audit()['issues']))

    def test_outlined_svg_does_not_pass_editability(self):
        path = self.root / 'figure.svg'
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0L1 1"/></svg>')
        self.manifest['outputs'] = [self.entry(path)]
        self.assertTrue(any(i['check'] == 'svg-text' for i in self.audit()['issues']))

    def test_misaligned_panels_are_reported(self):
        path = self.root / 'layout.json'
        path.write_text(json.dumps({'units':'pt','figure':{'width':500,'height':400},
            'panels':[{'id':'a','bounds':[40,220,450,380]}, {'id':'b','bounds':[70,30,450,190]}],
            'comparison_groups':[{'axis':'x','panels':['a','b']}]}))
        self.manifest['outputs'].append(self.entry(path))
        self.assertTrue(any(i['check'] == 'panel-alignment' for i in self.audit()['issues']))

    def test_hidden_or_definition_text_cannot_satisfy_data_label(self):
        fragments = [
            '<text display="none">SYNTHETIC</text>',
            '<g style="visibility: hidden"><text>SYNTHETIC</text></g>',
            '<g opacity="0"><text>SYNTHETIC</text></g>',
            '<g style="opacity: 0.0 !important"><text>SYNTHETIC</text></g>',
            '<defs><text>SYNTHETIC</text></defs>',
            '<clipPath id="clip"><text>SYNTHETIC</text></clipPath>',
            '<mask id="mask"><text>SYNTHETIC</text></mask>',
            '<text>Example <tspan style="display:none">SYNTHETIC</tspan></text>',
        ]
        self.manifest['data_kind'] = 'synthetic'
        path = self.root / 'figure.svg'
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                                '<text x="5" y="20">Label</text>' + fragment + '</svg>')
                self.manifest['outputs'] = [self.entry(path)]
                checks = {i['check'] for i in self.audit()['issues']}
                self.assertIn('data-label', checks)
                self.assertIn('svg-visibility', checks)

    def test_visible_nested_text_label_is_recognized(self):
        path = self.root / 'figure.svg'
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                        '<defs><path id="shape" d="M0 0L1 1"/></defs>'
                        '<g><text x="5" y="20">SYN<tspan>THETIC</tspan> example</text></g></svg>')
        self.manifest['data_kind'] = 'synthetic'
        self.manifest['outputs'] = [self.entry(path)]
        checks = {i['check'] for i in self.audit()['issues']}
        self.assertNotIn('data-label', checks)
        self.assertNotIn('svg-visibility', checks)

    def test_data_bundles_require_layout_output(self):
        for kind in ('benchmark', 'quant'):
            with self.subTest(kind=kind):
                self.manifest['kind'] = kind
                issues = self.audit()['issues']
                self.assertTrue(any(i['check'] == 'missing-layout' and i['level'] == 'fail' for i in issues))
        self.manifest['kind'] = 'architecture'
        self.assertFalse(any(i['check'] == 'missing-layout' for i in self.audit()['issues']))

    def test_malformed_manifest_is_failure_not_traceback(self):
        self.manifest['outputs'] = 'invalid'
        self.assertEqual(self.audit()['automatic_status'], 'fail')


if __name__ == '__main__':
    unittest.main()
