import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from thresholds import DEFAULTS, get_thresholds, save_thresholds
from db import initialize_database, read_metrics
from analysis import investigate, investigate_degradation
from investigation_ui import summarize_window
from timeline import build_timeline
import agent_tools


class ServiceThresholdTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'thresholds.json'
        self.db = Path(self.temp.name) / 'metrics.duckdb'
        initialize_database(self.db)
        self.profile_patch = patch('thresholds.CONFIG_PATH', self.config)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)

    def test_persistence_and_service_isolation(self):
        low = {**DEFAULTS, 'p95_ms': 200.0}
        save_thresholds('checkout-api', low)
        self.assertEqual(get_thresholds('checkout-api')['p95_ms'], 200)
        self.assertEqual(get_thresholds('reporting-service'), DEFAULTS)
        save_thresholds('reporting-service', {**DEFAULTS, 'errors_pct': .1})
        self.assertEqual(get_thresholds('checkout-api')['p95_ms'], 200)
        save_thresholds('checkout-api', DEFAULTS)
        self.assertEqual(get_thresholds('checkout-api'), DEFAULTS)

    def test_validation_and_corrupt_config(self):
        for value in [-1, float('nan'), float('inf'), True, 101]:
            with self.assertRaises(ValueError):
                save_thresholds('checkout-api', {**DEFAULTS, 'cpu_pct': value})
        with self.assertRaises(ValueError):
            save_thresholds('checkout-api', {'p95_ms': 200})
        self.config.write_text('{broken')
        with self.assertRaises(ValueError):
            get_thresholds('checkout-api')

    def test_consistent_investigation_timeline_severity_and_tools(self):
        frame = read_metrics('checkout-api', '2026-10-05', '2026-10-06', self.db)
        self.assertEqual(investigate('Which hours had slow requests?', 'checkout-api', '2026-10-05', '2026-10-06', self.db)['observed_values']['samples_above_threshold'], 0)
        save_thresholds('checkout-api', {**DEFAULTS, 'p95_ms': 200})
        samples, episodes = build_timeline(frame)
        expected = int((frame.p95_latency_ms > 200).sum())
        finding = investigate('Which hours had slow requests?', 'checkout-api', '2026-10-05', '2026-10-06', self.db)
        self.assertEqual(finding['observed_values']['samples_above_threshold'], expected)
        self.assertEqual(int((samples.State == 'Abnormal').sum()), expected)
        self.assertEqual(summarize_window(frame)['abnormal_samples'], expected)
        self.assertEqual(investigate_degradation('checkout-api', '2026-10-05', '2026-10-06', self.db)['observed_values']['high_latency_hours'], expected)
        original = read_metrics
        with patch('analysis.read_metrics', side_effect=lambda s, a, b, db=None: original(s, a, b, self.db)):
            self.assertEqual(agent_tools.detect_latency_anomalies('checkout-api', '2026-10-05', '2026-10-06')['observed_values']['samples_above_threshold'], expected)
            self.assertEqual(agent_tools.detect_latency_anomalies('checkout-api', '2026-10-05', '2026-10-06', p95_threshold_ms=500)['observed_values']['samples_above_threshold'], 0)

    def test_sidebar_save_and_service_switch(self):
        from streamlit.testing.v1 import AppTest
        with patch('ai_ui.configuration', return_value=(None, 'test-model')):
            app = AppTest.from_file('app.py').run(timeout=30)
            next(w for w in app.number_input if w.label == 'P95 latency limit (ms)').set_value(200)
            next(b for b in app.button if b.label == 'Save service thresholds').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(get_thresholds('checkout-api')['p95_ms'], 200)
            next(w for w in app.selectbox if w.label == 'Service').select('reporting-service').run()
            self.assertFalse(app.exception)
            self.assertEqual(next(w for w in app.number_input if w.label == 'P95 latency limit (ms)').value, 500)
            next(w for w in app.selectbox if w.label == 'Service').select('checkout-api').run()
            self.assertEqual(next(w for w in app.number_input if w.label == 'P95 latency limit (ms)').value, 200)
            next(b for b in app.button if b.label == 'Reset this service to defaults').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(get_thresholds('checkout-api'), DEFAULTS)
