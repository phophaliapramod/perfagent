import unittest
import tempfile
from pathlib import Path
from db import initialize_database
from analysis import EXAMPLE_QUESTIONS, investigate


class ServiceAnswerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'test.duckdb'
        initialize_database(self.db)

    def test_every_question_for_every_service(self):
        for service in ['checkout-api', 'data-ingestion', 'reporting-service']:
            for question in EXAMPLE_QUESTIONS:
                with self.subTest(service=service, question=question):
                    result = investigate(question, service, '2026-10-05', '2026-10-06', self.db)
                    self.assertEqual(result['service'], service)
                    self.assertTrue(result['answer'])
                    self.assertIn(service, ' '.join(result['answer']))
                    self.assertEqual(len(result['key_metrics']), 6)
                    self.assertEqual(result['confirmed_causes'], [])
                    self.assertTrue(result['recommended_actions'])
                    if service != 'data-ingestion':
                        self.assertNotIn('data-ingestion', ' '.join(result['answer']))

    def test_incident_vs_other_services(self):
        question = 'Which hours had slow requests?'
        result = investigate(question, 'data-ingestion', '2026-10-05T09:00:00', '2026-10-05T20:00:00', self.db)
        text = ' '.join(result['answer'])
        self.assertIn('11 of 11', text)
        self.assertIn('981.10 ms', text)
        self.assertIn('2026-10-05 09:00:00 UTC', text)
        self.assertIn('2026-10-05 19:00:00 UTC', text)
        for service in ['checkout-api', 'reporting-service']:
            result = investigate(question, service, '2026-10-05', '2026-10-06', self.db)
            self.assertEqual(result['observed_values']['samples_above_threshold'], 0)
            self.assertIn('No matching exceedances', ' '.join(result['answer']))

    def test_missing_baseline_and_empty_results(self):
        for service in ['checkout-api', 'data-ingestion', 'reporting-service']:
            result = investigate('Compare with baseline', service, '2026-10-01', '2026-10-08', self.db)
            self.assertIn(f'No preceding baseline samples exist for {service}', ' '.join(result['answer']))
            self.assertTrue(result['key_metrics'])
        for question in EXAMPLE_QUESTIONS:
            result = investigate(question, 'missing-service', '2026-10-05', '2026-10-06', self.db)
            self.assertIn('No samples were found', result['answer'][0])
            self.assertEqual(result['key_metrics'], [])

    def test_switching_service_updates_answer_ui(self):
        from streamlit.testing.v1 import AppTest
        from unittest.mock import patch
        with patch('ai_ui.configuration', return_value=(None, 'test-model')):
            app = AppTest.from_file('app.py').run(timeout=30)
            next(b for b in app.button if b.label == 'Investigate').click().run()
            for service in ['data-ingestion', 'reporting-service', 'checkout-api']:
                next(w for w in app.selectbox if w.label == 'Service').select(service).run()
                self.assertFalse(app.exception)
                finding = app.session_state['investigation_question']
                self.assertTrue(finding)
                text = ' '.join(element.value for element in app.markdown)
                self.assertIn(service, text)
                self.assertIn('No preceding baseline samples exist for ' + service, text)
