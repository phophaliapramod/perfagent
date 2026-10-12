import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import analysis
import agent_tools
from db import initialize_database, read_metrics
from metrics import aggregate_metrics


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'metrics.duckdb'
        initialize_database(self.db)
        original = read_metrics
        self.patch = patch('analysis.read_metrics', side_effect=lambda s, a, b, db=None: original(s, a, b, self.db))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.start = '2026-10-05T09:00:00Z'
        self.end = '2026-10-05T20:00:00Z'

    def test_all_tool_schemas_and_empty_results(self):
        keys = {'service', 'time_window', 'observed_values', 'comparison_values_or_thresholds',
                'evidence', 'possible_interpretation', 'observations', 'hypotheses', 'confirmed_causes'}
        for service in ['data-ingestion', 'missing']:
            for name, function in agent_tools.TOOLS.items():
                with self.subTest(service=service, tool=name):
                    result = function(service, self.start, self.end)
                    self.assertEqual(set(result), keys)
                    self.assertEqual(result['confirmed_causes'], [])
                    self.assertIsInstance(result['observations'], dict)
                    self.assertIsInstance(result['hypotheses'], list)
                    self.assertIsInstance(result['evidence'], list)
                    json.dumps(result, allow_nan=False)
                    if service == 'missing':
                        self.assertEqual(result['observed_values'].get('sample_count', result['observed_values'].get('total_samples')), 0)

    def test_invalid_windows_for_every_tool_and_analysis(self):
        for functions in [agent_tools.TOOLS, analysis.EXAMPLE_QUESTIONS]:
            for function in functions.values():
                for start, end in [('bad', self.end), (self.end, self.start), (self.start, self.start)]:
                    with self.subTest(function=function.__name__, start=start):
                        with self.assertRaises(ValueError):
                            function('data-ingestion', start, end)
        for service in ['', None, 3]:
            with self.assertRaises(ValueError):
                agent_tools.get_service_metrics(service, self.start, self.end)

    def test_threshold_validation(self):
        for value in [True, -1, float('nan'), float('inf'), '80', 101]:
            with self.assertRaises(ValueError):
                agent_tools.detect_error_spikes('data-ingestion', self.start, self.end, value)
        with self.assertRaises(TypeError):
            agent_tools.get_service_metrics('data-ingestion', self.start, self.end, sql='DROP TABLE performance_metrics')

    def test_incident_and_healthy_baseline(self):
        # Incident is 09:00 through 19:00 inclusive. Previous equal window is 22:00–09:00.
        for function in [agent_tools.detect_latency_anomalies, agent_tools.detect_error_spikes,
                         agent_tools.analyze_resource_utilization]:
            result = function('data-ingestion', self.start, self.end)
            expected = 4 if function == agent_tools.analyze_resource_utilization else 11
            self.assertEqual(result['observed_values']['samples_above_threshold'], expected)
            self.assertEqual(len(result['evidence']), expected)
            self.assertIn('timestamp', result['evidence'][0])
        baseline = agent_tools.compare_with_baseline('data-ingestion', self.start, self.end)
        self.assertEqual(baseline['comparison_values_or_thresholds']['baseline_sample_count'], 11)
        rows = baseline['comparison_values_or_thresholds']['baseline_evidence']
        self.assertTrue(all(r['cpu_utilization_pct'] < 80 and r['error_rate_pct'] < 1
                            and r['p95_latency_ms'] < 500 and r['p99_latency_ms'] < 1000
                            for r in rows))
        for metric in ['p95_latency_ms', 'p99_latency_ms', 'error_rate_pct', 'cpu_utilization_pct']:
            comparison = next(r for r in baseline['evidence'] if r['metric'] == metric)
            self.assertGreater(comparison['observed_mean'], comparison['baseline_mean'])
        print('Incident comparison:', baseline['evidence'])

    def test_aggregation_weighting_and_empty(self):
        frame = pd.DataFrame({'p95_latency_ms': [100, 400], 'p99_latency_ms': [200, 800],
                              'throughput_rps': [10, 30], 'error_rate_pct': [1, 9],
                              'request_count': [900, 100], 'cpu_utilization_pct': [20, 40],
                              'memory_utilization_pct': [30, 50]})
        result = aggregate_metrics(frame)
        self.assertEqual(result['worst_hourly_p95_ms'], 400)
        self.assertEqual(result['worst_hourly_p99_ms'], 800)
        self.assertEqual(result['mean_throughput_rps'], 20)
        self.assertAlmostEqual(result['request_weighted_error_rate_pct'], 1.8)
        self.assertEqual(result['mean_hourly_error_rate_pct'], 5)
        self.assertIsNone(aggregate_metrics(frame.iloc[:0])['request_weighted_error_rate_pct'])
        frame.request_count = 0
        self.assertIsNone(aggregate_metrics(frame)['request_weighted_error_rate_pct'])

    def test_timezone_normalization(self):
        utc = agent_tools.get_service_metrics('data-ingestion', self.start, self.end)
        offset = agent_tools.get_service_metrics('data-ingestion', '2026-10-05T02:00:00-07:00', '2026-10-05T13:00:00-07:00')
        self.assertEqual(utc, offset)
