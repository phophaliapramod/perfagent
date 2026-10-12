import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from openai import APITimeoutError, APIConnectionError
import ai_agent
from db import initialize_database, read_metrics


def call(name='get_service_metrics', arguments=None):
    arguments = arguments or {'service': 'data-ingestion', 'start': '2026-10-05T09:00:00Z', 'end': '2026-10-05T20:00:00Z'}
    item = SimpleNamespace(type='function_call', name=name, arguments=json.dumps(arguments), call_id='call_1')
    item.model_dump = lambda **kwargs: {'type': 'function_call', 'name': name, 'arguments': item.arguments, 'call_id': item.call_id}
    return item


def response(calls=None, report=None, status='completed'):
    return SimpleNamespace(output=calls or [], output_text=json.dumps(report or {k: 'Synthetic evidence; no confirmed cause.' for k in ai_agent.REPORT_FIELDS}), status=status)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.config = patch('ai_agent.configuration', return_value=('test-secret', 'test-model'))
        self.config.start()
        self.addCleanup(self.config.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db = Path(self.temp.name) / 'test.duckdb'
        initialize_database(db)
        self.db_patch = patch('analysis.read_metrics', side_effect=lambda service, start, end, db_path=None: read_metrics(service, start, end, db))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def run_client(self, responses):
        client = Mock()
        client.responses.create.side_effect = responses
        result = ai_agent.run_agent('Investigate incident', 'data-ingestion', '2026-10-05', '2026-10-06', client=client)
        return result, client

    def test_successful_multitool_conversation_with_real_database(self):
        result, client = self.run_client([response([call()]), response([call('compare_with_baseline')]), response()])
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['steps']), 2)
        self.assertEqual(result['steps'][0]['result']['findings']['observed_values']['sample_count'], 11)
        self.assertEqual(set(result['report']), set(ai_agent.REPORT_FIELDS))
        kwargs = client.responses.create.call_args_list[-1].kwargs
        self.assertFalse(kwargs['store'])
        outputs = [m for m in kwargs['input'] if isinstance(m, dict) and m.get('type') == 'function_call_output']
        self.assertEqual(len(outputs), 2)
        self.assertIn('findings', json.loads(outputs[0]['output']))
        self.assertEqual(client.responses.create.call_args_list[0].kwargs['tool_choice'], 'required')

    def test_invalid_arguments_unknown_tools_and_no_code_execution(self):
        for name, args in [('shell', {'command': 'touch malicious'}),
                           ('get_service_metrics', {'service': 'data-ingestion', 'start': 'bad', 'end': '2026-10-06'}),
                           ('get_service_metrics', {'service': 'data-ingestion', 'start': '2026-10-06', 'end': '2026-10-05'}),
                           ('get_service_metrics', {'service': 'data-ingestion', 'start': '2026-10-05', 'end': '2026-10-06', 'sql': 'DROP TABLE performance_metrics'})]:
            with self.subTest(name=name, args=args):
                result, _ = self.run_client([response([call(name, args)]), response()])
                self.assertIn('error', result['steps'][0]['result'])
                self.assertIn('No successful metric evidence', result['report']['confidence_and_evidence_limitations'])
        self.assertIn('error', ai_agent.execute_tool('get_service_metrics', '{broken'))

    def test_tool_failure_does_not_leak_exception(self):
        with patch.dict(ai_agent.TOOLS, {'get_service_metrics': Mock(side_effect=RuntimeError('test-secret internal path'))}):
            result, _ = self.run_client([response([call()]), response()])
        self.assertIn('Metric tool failed', result['steps'][0]['result']['error'])
        self.assertNotIn('test-secret', json.dumps(result))
        self.assertNotIn('internal path', json.dumps(result))

    def test_budget_enforced(self):
        result, client = self.run_client([response([call()]) for _ in range(5)])
        self.assertEqual(len(result['steps']), 4)
        self.assertIn('budget', result['error'])
        self.assertEqual(client.responses.create.call_count, 5)
        self.assertEqual(client.responses.create.call_args.kwargs['tools'], [])
        self.assertEqual(client.responses.create.call_args.kwargs['tool_choice'], 'none')

    def test_execution_count_bound(self):
        result, _ = self.run_client([response([call() for _ in range(15)]), response()])
        self.assertEqual(sum('findings' in s['result'] for s in result['steps']), 12)
        self.assertEqual(sum('error' in s['result'] for s in result['steps']), 3)

    def test_api_failure_timeout_and_partial_evidence(self):
        request = Mock()
        for error in [APITimeoutError(request=request), APIConnectionError(request=request, message='test-secret')]:
            result, _ = self.run_client([response([call()]), error])
            self.assertIsNone(result['report'])
            self.assertEqual(len(result['steps']), 1)
            self.assertTrue(result['error'])
            self.assertNotIn('test-secret', json.dumps(result))

    def test_secret_redaction_and_untrusted_evidence_instructions(self):
        report = {k: 'test-secret' for k in ai_agent.REPORT_FIELDS}
        result, client = self.run_client([response([call()]), response(report=report)])
        self.assertNotIn('test-secret', json.dumps(result))
        self.assertIn('untrusted', client.responses.create.call_args.kwargs['instructions'])
        self.assertIn('cannot confirm', client.responses.create.call_args.kwargs['instructions'])

    def test_missing_key_no_network(self):
        with patch('ai_agent.configuration', return_value=(None, 'test-model')), patch('ai_agent.OpenAI') as constructor:
            result = ai_agent.run_agent('Question', 'data-ingestion', '2026-10-05', '2026-10-06')
            constructor.assert_not_called()
        self.assertIn('OPENAI_API_KEY', result['error'])

    def test_incomplete_or_malformed_report(self):
        for final in [response(status='incomplete'), response(report={'wrong': 'shape'})]:
            result, _ = self.run_client([response([call()]), final])
            self.assertIsNone(result['report'])
            self.assertTrue(result['error'])

    def test_evidence_truncation_is_explicit(self):
        value = ai_agent._bounded_evidence({'evidence': list(range(60))})
        self.assertTrue(value['evidence']['truncated'])
        self.assertEqual(value['evidence']['total_rows'], 60)
        self.assertEqual(len(value['evidence']['rows']), 50)

    def test_missing_key_dashboard_preserves_deterministic_investigations(self):
        from streamlit.testing.v1 import AppTest
        with patch('ai_ui.configuration', return_value=(None, 'test-model')):
            app = AppTest.from_file('app.py').run(timeout=30)
            self.assertFalse(app.exception)
            self.assertIn('AI Agent', [tab.label for tab in app.tabs])
            next(b for b in app.button if b.label == 'Investigate').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.json)
            examples = [button for button in app.button if button.key and button.key.startswith('ai_example')]
            self.assertTrue(all(button.disabled for button in examples))

    def test_real_sdk_with_mock_http_transport(self):
        # Exercise actual SDK serialization and response parsing without network access.
        try:
            import httpx2 as transport_lib
        except ImportError:
            import httpx as transport_lib
        from openai import OpenAI
        requests = []
        def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) == 1:
                output = [dict(call().model_dump(), id='fc_1', status='completed')]
            else:
                output = [{'type': 'message', 'id': 'msg_1', 'role': 'assistant', 'status': 'completed',
                           'content': [{'type': 'output_text', 'text': json.dumps({key: 'Evidence checked; no confirmed cause.' for key in ai_agent.REPORT_FIELDS}), 'annotations': []}]}]
            return transport_lib.Response(200, json={'id': 'resp_test', 'object': 'response',
                'created_at': 0, 'status': 'completed', 'model': 'test-model', 'output': output})
        with transport_lib.Client(transport=transport_lib.MockTransport(handler)) as http_client:
            with OpenAI(api_key='test-secret', http_client=http_client, max_retries=0) as client:
                result = ai_agent.run_agent('Investigate data-ingestion', 'data-ingestion', '2026-10-05', '2026-10-06', client=client)
        self.assertIsNone(result['error'], result)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]['text']['format']['type'], 'json_schema')
        self.assertTrue(all(tool['strict'] for tool in requests[0]['tools']))
        self.assertEqual(requests[1]['input'][-1]['type'], 'function_call_output')

    def test_ai_example_ui_displays_mocked_report_and_evidence(self):
        from streamlit.testing.v1 import AppTest
        finding = ai_agent.execute_tool('get_service_metrics', call().arguments)
        result = {'report': {key: 'Synthetic report' for key in ai_agent.REPORT_FIELDS},
                  'steps': [{'tool': 'get_service_metrics', 'result': finding}], 'error': None}
        with patch('ai_ui.configuration', return_value=('test-secret', 'test-model')), patch('ai_ui.run_agent', return_value=result) as runner:
            app = AppTest.from_file('app.py').run(timeout=30)
            next(button for button in app.button if button.key == 'ai_example_0').click().run()
            self.assertFalse(app.exception)
            runner.assert_called_once()
            self.assertEqual(len(app.chat_message), 2)
            self.assertTrue(any(expander.label == 'Tool 1: get_service_metrics' for expander in app.expander))

    def test_safe_api_error_categories(self):
        for status, body, expected in [
            (429, {'message': 'test-secret quota exceeded'}, 'billing'),
            (429, {'code': 'rate_limit_exceeded'}, 'rate limit'),
            (401, {'message': 'test-secret'}, 'credentials'),
            (403, {}, 'permissions'), (404, {}, 'model'), (400, {}, 'format'), (500, {}, 'service')]:
            error = SimpleNamespace(status_code=status, body=body)
            message = ai_agent.safe_api_error(error)
            self.assertIn(expected, message)
            self.assertNotIn('test-secret', message)
