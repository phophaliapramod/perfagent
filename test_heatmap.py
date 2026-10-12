import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from db import initialize_database, read_all_service_metrics
from degradation_heatmap import build_heatmap
from thresholds import DEFAULTS, save_thresholds


class HeatmapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'test.duckdb'
        initialize_database(self.db)
        self.patch = patch('thresholds.CONFIG_PATH', Path(self.temp.name) / 'limits.json')
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.services = ['checkout-api', 'data-ingestion', 'reporting-service']

    def test_incident_and_all_services_read(self):
        frame = read_all_service_metrics('2026-10-05', '2026-10-06', self.db)
        self.assertEqual(len(frame), 72)
        fig = build_heatmap(frame, self.services, '2026-10-05', '2026-10-06', 'data-ingestion')
        trace = fig.data[0]
        self.assertEqual(len(trace.z), 3)
        self.assertEqual(trace.z[1][9], 2)
        self.assertEqual(trace.z[1][10], 3)
        self.assertEqual(trace.z[1][20], 0)
        self.assertIn('(selected)', trace.y[1])
        self.assertIn('862.70 ms', trace.text[1][9])

    def test_missing_evidence_and_service_thresholds(self):
        frame = read_all_service_metrics('2026-10-05', '2026-10-06', self.db)
        save_thresholds('checkout-api', {**DEFAULTS, 'p95_ms': 0})
        fig = build_heatmap(frame, self.services, '2026-10-05', '2026-10-06')
        self.assertEqual(fig.data[0].z[0][0], 1)
        frame = frame[~((frame.service == 'checkout-api') & (frame.timestamp == pd.Timestamp('2026-10-05')))].copy()
        frame.loc[(frame.service == 'checkout-api') & (frame.timestamp == pd.Timestamp('2026-10-05 01:00')), 'error_rate_pct'] = float('nan')
        fig = build_heatmap(frame, self.services, '2026-10-05', '2026-10-06')
        self.assertEqual(fig.data[0].z[0][0], -1)
        self.assertEqual(fig.data[0].z[0][1], -1)
        with self.assertRaises(ValueError):
            read_all_service_metrics('2026-10-06', '2026-10-05', self.db)
