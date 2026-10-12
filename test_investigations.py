import unittest
import tempfile
from pathlib import Path
from db import initialize_database
from analysis import investigate


class InvestigationTests(unittest.TestCase):
    def test_incident_profile_and_natural_wording(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.duckdb'
            initialize_database(db)
            result = investigate('Why was the service slow?', 'data-ingestion', '2026-10-05T09:00:00', '2026-10-05T20:00:00', db)
            self.assertEqual(result['observed_values']['high_latency_hours'], 11)
            self.assertEqual(result['observed_values']['latency_and_errors_hours'], 11)
            self.assertEqual(result['observed_values']['latency_and_cpu_hours'], 4)
            self.assertEqual(result['confirmed_causes'], [])
            self.assertTrue(result['recommended_actions'])
            for question in ['Show slow requests', 'Check errors please', 'Compare with baseline', 'CPU pressure?', 'Summarize requests']:
                self.assertTrue(investigate(question, 'data-ingestion', '2026-10-05', '2026-10-06', db)['evidence'])
