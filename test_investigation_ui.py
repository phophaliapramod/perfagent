import unittest
import pandas as pd
from db import DEFAULT_CSV
from investigation_ui import summarize_window, comparison_table


class InvestigationReportTests(unittest.TestCase):
    def test_incident_summary_and_no_data(self):
        frame = pd.read_csv(DEFAULT_CSV, parse_dates=['timestamp'])
        selected = frame[(frame.service == 'data-ingestion') & frame.timestamp.between('2026-10-05 09:00', '2026-10-05 19:00')]
        result = summarize_window(selected)
        self.assertEqual(result['severity'], 'High (heuristic)')
        self.assertEqual(result['abnormal_samples'], 11)
        self.assertEqual(result['overlap_samples'], 11)
        self.assertEqual(result['episode_count'], 1)
        self.assertEqual(summarize_window(selected.iloc[:0])['severity'], 'Insufficient data')
        normal = frame[(frame.service == 'data-ingestion') & frame.timestamp.between('2026-10-04 22:00', '2026-10-05 08:00')].copy()
        self.assertEqual(summarize_window(normal)['severity'], 'No threshold exceedances')
        normal['error_rate_pct'] = float('nan')
        self.assertEqual(summarize_window(normal)['severity'], 'Insufficient data')

    def test_baseline_units_and_missing_values(self):
        table = comparison_table({'evidence': [{'metric': 'throughput_rps', 'observed_mean': 120, 'baseline_mean': None, 'change_pct': None}]})
        self.assertEqual(table.iloc[0]['Selected window'], '120.00 req/s')
        self.assertEqual(table.iloc[0]['Preceding baseline'], 'Unavailable')
