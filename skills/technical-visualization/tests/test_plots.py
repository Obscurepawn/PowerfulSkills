"""Regression tests for public CSV/config behavior and reproducible bundles."""
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
HAS_PLOTTING_DEPS = bool(importlib.util.find_spec('matplotlib') and importlib.util.find_spec('numpy'))

class PlotCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def run_plot(self, kind, data, config, success=True, name='result'):
        if not HAS_PLOTTING_DEPS:
            self.skipTest('matplotlib/numpy not installed in current interpreter')
        source = self.root / 'data.csv'
        config_file = self.root / 'config.json'
        source.write_text(data, encoding='utf-8')
        config_file.write_text(json.dumps(config), encoding='utf-8')
        out = self.root / name
        result = subprocess.run([sys.executable, str(SCRIPTS / f'plot_{kind}.py'), '--input', str(source), '--config', str(config_file), '--output', str(out)], capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stderr)
        return out, result

    def test_help_and_missing_dependencies_exit_cleanly_without_traceback(self):
        for kind in ('benchmark', 'quant'):
            help_res = subprocess.run([sys.executable, '-S', str(SCRIPTS / f'plot_{kind}.py'), '--help'], capture_output=True, text=True)
            self.assertEqual(help_res.returncode, 0, help_res.stderr)
            self.assertIn('--input', help_res.stdout)

            source = self.root / f'{kind}.csv'
            cfg = self.root / f'{kind}.json'
            source.write_text('series,x,run,value\nA,1,1,10\n', encoding='utf-8')
            cfg.write_text('{}', encoding='utf-8')
            miss_res = subprocess.run([sys.executable, '-S', str(SCRIPTS / f'plot_{kind}.py'), '--input', str(source), '--config', str(cfg), '--output', str(self.root / f'out-{kind}')], capture_output=True, text=True)
            self.assertEqual(miss_res.returncode, 2, miss_res.stderr)
            self.assertIn('missing plotting dependency', miss_res.stderr)
            self.assertNotIn('Traceback', miss_res.stderr)
    def benchmark_config(self, **changes):
        return dict(title='Test benchmark', source='Synthetic test fixture', data_kind='synthetic', metric='Latency', unit='ms', x_label='Workers', **changes)
    def quant_config(self, **changes):
        return dict(title='Test returns', source='Synthetic test fixture', data_kind='synthetic', return_basis='net', frequency='trading-day', cost_note='Fixture returns after hypothetical costs', **changes)
    def test_drawdown_includes_initial_wealth(self):
        out, _ = self.run_plot('quant', 'date,series,return\n2026-01-01,A,-0.1\n2026-01-02,A,0.05\n2026-01-03,A,-0.2\n', self.quant_config())
        rows = list(csv.DictReader((out / 'derived.csv').read_text().splitlines()))
        self.assertAlmostEqual(float(rows[0]['nav']), 0.9)
        self.assertAlmostEqual(float(rows[0]['drawdown']), -0.1)
        self.assertAlmostEqual(float(rows[-1]['nav']), 0.756)
        self.assertAlmostEqual(float(rows[-1]['drawdown']), -0.244)
    def test_benchmark_summary_and_bundle_hashes(self):
        out, _ = self.run_plot('benchmark', 'series,x,run,value\nA,1,1,10\nA,1,2,12\nA,1,3,20\n', self.benchmark_config())
        row = next(csv.DictReader((out / 'derived.csv').read_text().splitlines()))
        self.assertEqual(float(row['center']), 12)
        self.assertEqual((float(row['lower']), float(row['upper'])), (10, 20))
        manifest = json.loads((out / 'manifest.json').read_text())
        for item in manifest['inputs'] + manifest['outputs']:
            self.assertEqual(hashlib.sha256((out / item['path']).read_bytes()).hexdigest(), item['sha256'])
        self.assertIn('<text', (out / 'figure.svg').read_text())
        self.assertIn('SYNTHETIC', (out / 'caption.txt').read_text())
    def test_quant_rejects_unsorted_dates_without_output(self):
        out, result = self.run_plot('quant', 'date,series,return\n2026-01-02,A,0.1\n2026-01-01,A,0.2\n', self.quant_config(), False)
        self.assertIn('strictly increasing', result.stderr)
        self.assertFalse(out.exists())
    def test_quant_rejects_alignment_missing_value_and_total_loss(self):
        cases = ['date,series,return\n2026-01-01,A,0.1\n2026-01-02,B,0.2\n', 'date,series,return\n2026-01-01,A,nan\n', 'date,series,return\n2026-01-01,A,-1\n']
        for data in cases:
            with self.subTest(data=data):
                self.run_plot('quant', data, self.quant_config(), False)
    def test_quant_zero_volatility_and_incomplete_windows_are_blank(self):
        out, _ = self.run_plot('quant', 'date,series,return\n2026-01-01,A,0.01\n2026-01-02,A,0.01\n2026-01-03,A,0.01\n', self.quant_config(rolling_window=2, periods_per_year=252, risk_free_per_period=0))
        rows = list(csv.DictReader((out / 'derived.csv').read_text().splitlines()))
        self.assertTrue(all(row['rolling_sharpe'] == '' for row in rows))
    def test_bootstrap_requires_independent_runs_and_multiple_observations(self):
        data = 'series,x,run,value\nA,1,1,10\nA,1,2,12\n'
        _, result = self.run_plot('benchmark', data, self.benchmark_config(interval='bootstrap95'), False)
        self.assertIn('independent_runs', result.stderr)
        self.run_plot('benchmark', 'series,x,run,value\nA,1,1,10\n', self.benchmark_config(interval='bootstrap95', independent_runs=True), False)
    def test_benchmark_rejects_duplicate_nonfinite_and_nonpositive_log(self):
        for data, config in [('series,x,run,value\nA,1,1,10\nA,1,1,20\n', self.benchmark_config()), ('series,x,run,value\nA,1,1,inf\n', self.benchmark_config()), ('series,x,run,value\nA,1,1,0\n', self.benchmark_config(y_scale='log'))]:
            with self.subTest(data=data):
                self.run_plot('benchmark', data, config, False)
    def test_nonempty_output_is_preserved(self):
        output = self.root / 'result'
        output.mkdir()
        (output / 'keep.txt').write_text('keep')
        self.run_plot('benchmark', 'series,x,run,value\nA,1,1,10\n', self.benchmark_config(), False)
        self.assertEqual((output / 'keep.txt').read_text(), 'keep')
    def test_rolling_sharpe_uses_sample_std_and_explicit_frequency(self):
        data = 'date,series,return\n2026-01-01,A,0.01\n2026-01-02,A,0.03\n2026-01-03,A,-0.02\n'
        out, _ = self.run_plot('quant', data, self.quant_config(rolling_window=2, periods_per_year=12, risk_free_per_period=0.001))
        rows = list(csv.DictReader((out / 'derived.csv').read_text().splitlines()))
        expected = math.sqrt(12) * 0.019 / math.sqrt(0.0002)
        self.assertEqual(rows[0]['rolling_sharpe'], '')
        self.assertAlmostEqual(float(rows[1]['rolling_sharpe']), expected)
    def test_bootstrap_is_replayable_and_has_ordered_bounds(self):
        data = 'series,x,run,value\nA,1,1,10\nA,1,2,12\nA,1,3,20\n'
        config = self.benchmark_config(interval='bootstrap95', independent_runs=True, seed=97, bootstrap_samples=1000)
        out, _ = self.run_plot('benchmark', data, config, name='first')
        other, _ = self.run_plot('benchmark', data, config, name='second')
        self.assertEqual((out / 'derived.csv').read_bytes(), (other / 'derived.csv').read_bytes())
        row = next(csv.DictReader((out / 'derived.csv').read_text().splitlines()))
        self.assertLessEqual(float(row['lower']), float(row['center']))
        self.assertLessEqual(float(row['center']), float(row['upper']))
    def test_constant_decimal_window_does_not_create_huge_sharpe(self):
        data = 'date,series,return\n2026-01-01,A,0.1\n2026-01-02,A,0.1\n2026-01-03,A,0.1\n'
        out, _ = self.run_plot('quant', data, self.quant_config(rolling_window=3, periods_per_year=252, risk_free_per_period=0))
        rows = list(csv.DictReader((out / 'derived.csv').read_text().splitlines()))
        self.assertEqual(rows[-1]['rolling_sharpe'], '')
    def test_invalid_benchmark_enum_types_are_clean_data_errors(self):
        data = 'series,x,run,value\nA,1,1,10\n'
        for key, value in [('statistic', []), ('interval', {}), ('y_scale', [])]:
            with self.subTest(key=key):
                _, result = self.run_plot('benchmark', data, self.benchmark_config(**{key: value}), False)
                self.assertIn(f'error: {key} must be', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
    def test_unknown_config_key_is_rejected(self):
        self.run_plot('benchmark', 'series,x,run,value\nA,1,1,10\n', self.benchmark_config(intervall='range'), False)
    def test_replay_from_copied_bundle(self):
        out, _ = self.run_plot('quant', 'date,series,return\n2026-01-01,A,0.01\n2026-01-02,A,-0.02\n', self.quant_config())
        manifest = json.loads((out / 'manifest.json').read_text())
        command = manifest['command']
        command[0] = sys.executable
        rerun = subprocess.run(command, cwd=out, capture_output=True, text=True)
        self.assertEqual(rerun.returncode, 0, rerun.stdout + rerun.stderr)
        replayed = (out / command[-1]).resolve()
        self.assertEqual((out / 'derived.csv').read_bytes(), (replayed / 'derived.csv').read_bytes())
        self.assertEqual((out / 'figure.svg').read_bytes(), (replayed / 'figure.svg').read_bytes())

if __name__ == '__main__':
    unittest.main()
