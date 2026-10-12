"""Run with python -m unittest -v test_foundation.py."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
import duckdb
from db import initialize_database, read_metrics
from analysis import (get_service_metrics, detect_latency_anomalies, detect_error_spikes,
                      analyze_resource_utilization, compare_with_baseline, investigate)


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'test.duckdb'
        initialize_database(self.db)
        self.start = datetime(2026, 10, 5)
        self.end = datetime(2026, 10, 6)

    def test_import_is_idempotent(self):
        self.assertEqual(initialize_database(self.db), 504)
        self.assertEqual(initialize_database(self.db), 504)
        with duckdb.connect(str(self.db), read_only=True) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM (SELECT DISTINCT timestamp, service, environment FROM performance_metrics)').fetchone()[0], 504)

    def test_filters_and_parameters(self):
        rows = read_metrics('data-ingestion', self.start, self.end, self.db)
        self.assertEqual(len(rows), 24)
        self.assertTrue((rows.timestamp < self.end).all())
        self.assertTrue(read_metrics("' OR 1=1 --", self.start, self.end, self.db).empty)

    def test_findings_and_incident(self):
        for function in [get_service_metrics, detect_latency_anomalies, detect_error_spikes,
                         analyze_resource_utilization, compare_with_baseline]:
            finding = function('data-ingestion', self.start, self.end, self.db)
            self.assertEqual(set(finding), {'service', 'time_window', 'observed_values',
                             'comparison_values_or_thresholds', 'evidence', 'possible_interpretation',
                             'observations', 'hypotheses', 'confirmed_causes'})
        for function in [detect_latency_anomalies, detect_error_spikes, analyze_resource_utilization]:
            finding = function('data-ingestion', self.start, self.end, self.db)
            self.assertGreater(finding['observed_values']['samples_above_threshold'], 0)
        baseline = compare_with_baseline('data-ingestion', self.start, self.end, self.db)
        self.assertEqual(baseline['comparison_values_or_thresholds']['baseline_sample_count'], 24)
        self.assertGreater(baseline['evidence'][0]['change_pct'], 0)

    def test_empty_and_missing_baseline(self):
        result = compare_with_baseline('data-ingestion', datetime(2026, 10, 1), datetime(2026, 10, 2), self.db)
        self.assertEqual(result['comparison_values_or_thresholds']['baseline_sample_count'], 0)
        self.assertIsNone(result['evidence'][0]['baseline_mean'])
        self.assertEqual(get_service_metrics('missing', self.start, self.end, self.db)['observed_values']['sample_count'], 0)
        with self.assertRaises(ValueError):
            investigate('unrecognized question xyz', 'data-ingestion', self.start, self.end, self.db)
        with self.assertRaises(FileNotFoundError):
            initialize_database(self.db, Path(self.temp.name) / 'missing.csv')


if __name__ == '__main__':
    unittest.main()
