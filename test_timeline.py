import unittest
import pandas as pd
from timeline import build_timeline
from db import DEFAULT_CSV


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.read_csv(DEFAULT_CSV, parse_dates=['timestamp'])
        self.frame = self.frame[self.frame.service == 'data-ingestion'].copy()

    def test_injected_incident_and_observed_recovery(self):
        samples, episodes = build_timeline(self.frame)
        incident = episodes[episodes['First abnormal sample (UTC)'] == pd.Timestamp('2026-10-05 09:00')].iloc[0]
        self.assertEqual(incident['Last abnormal sample (UTC)'], pd.Timestamp('2026-10-05 19:00'))
        self.assertEqual(incident['Abnormal hourly samples'], 11)
        self.assertEqual(incident['First normal sample (UTC)'], pd.Timestamp('2026-10-05 20:00'))
        self.assertEqual(incident['Recovery status'], 'Observed return within thresholds')

    def test_window_boundary_does_not_invent_recovery(self):
        frame = self.frame[self.frame.timestamp.between('2026-10-05 09:00', '2026-10-05 19:00')]
        _, episodes = build_timeline(frame)
        self.assertEqual(len(episodes), 1)
        self.assertTrue(pd.isna(episodes.iloc[0]['First normal sample (UTC)']))
        self.assertIn('not observed', episodes.iloc[0]['Recovery status'])

    def test_gap_splits_episode(self):
        frame = self.frame[self.frame.timestamp.between('2026-10-05 09:00', '2026-10-05 20:00')]
        frame = frame[frame.timestamp != pd.Timestamp('2026-10-05 14:00')]
        _, episodes = build_timeline(frame)
        self.assertEqual(len(episodes), 2)
        self.assertIn('Unknown', episodes.iloc[0]['Recovery status'])

    def test_incomplete_normal_sample_cannot_prove_recovery(self):
        frame = self.frame[self.frame.timestamp.between('2026-10-05 19:00', '2026-10-05 20:00')].copy()
        frame.loc[frame.timestamp == pd.Timestamp('2026-10-05 20:00'), 'error_rate_pct'] = float('nan')
        _, episodes = build_timeline(frame)
        self.assertTrue(pd.isna(episodes.iloc[0]['First normal sample (UTC)']))

    def test_threshold_equality_empty_and_environment_isolation(self):
        frame = self.frame.iloc[:1].copy()
        for column, value in [('p95_latency_ms', 500), ('p99_latency_ms', 1000), ('error_rate_pct', 1), ('cpu_utilization_pct', 80), ('memory_utilization_pct', 80)]:
            frame[column] = value
        self.assertTrue(build_timeline(frame)[1].empty)
        self.assertTrue(build_timeline(frame.iloc[:0])[1].empty)
        frame.p95_latency_ms = 501
        other = frame.copy()
        other.environment = 'staging'
        self.assertEqual(len(build_timeline(pd.concat([frame, other]))[1]), 2)
