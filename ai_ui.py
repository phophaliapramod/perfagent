"""Streamlit AI chat; API calls only occur on explicit chat/example submission."""
import pandas as pd
import streamlit as st
from ai_agent import configuration, run_agent

EXAMPLES = [
    'Investigate data-ingestion on October 5, 2026, 09:00–20:00 UTC. Compare with the preceding baseline and rank hypotheses.',
    'For data-ingestion on October 5, 2026, which latency, errors, and CPU signals coincide? Show timestamped evidence.',
]


def _result(result):
    if result.get('error'):
        st.warning(result['error'])
    if result.get('report'):
        for name, content in result['report'].items():
            st.markdown(f'**{name.replace("_", " ").capitalize()}**')
            st.write(content)
    for index, step in enumerate(result.get('steps', []), 1):
        with st.expander(f'Tool {index}: {step["tool"]}'):
            findings = step['result'].get('findings')
            if not findings:
                st.warning(step['result']['error'])
                continue
            st.json({k: v for k, v in findings.items() if k not in ['evidence', 'observations', 'comparison_values_or_thresholds']})
            if findings['evidence']:
                st.dataframe(pd.DataFrame(findings['evidence']), width='stretch', hide_index=True)
            else:
                st.caption('No evidence rows matched this query.')
            comparison = findings['comparison_values_or_thresholds']
            st.json({k: v for k, v in comparison.items() if not k.endswith('_evidence')})
            for label in ['current_evidence', 'baseline_evidence']:
                if comparison.get(label):
                    st.caption(label.replace('_', ' ').capitalize())
                    st.dataframe(pd.DataFrame(comparison[label]), width='stretch', hide_index=True)


def render_ai_agent(service, start, end):
    st.subheader('AI troubleshooting agent')
    st.caption('Uses the OpenAI API and synthetic read-only evidence. Defaults to sidebar filters; explicit services and UTC windows in your question override them. Historical reports retain their original windows.')
    key, model = configuration()
    enabled = bool(key)
    st.caption(f'Model: {model} • Maximum 4 tool rounds / 12 tool executions • 30-second timeout per API request')
    if not enabled:
        st.info('Set OPENAI_API_KEY in your environment or local .env, then restart Streamlit. Deterministic investigations remain available.')
    if st.button('Clear AI chat'):
        st.session_state['ai_chat'] = []
    chat = st.session_state.setdefault('ai_chat', [])
    prompt = None
    for index, example in enumerate(EXAMPLES):
        if st.button(example, key=f'ai_example_{index}', disabled=not enabled):
            prompt = example
    for message in chat:
        with st.chat_message(message['role']):
            if message['role'] == 'user':
                st.write(message['content'])
            else:
                _result(message['result'])
    typed = st.chat_input('Ask about performance, a service, and a UTC window', disabled=not enabled, key='ai_question')
    prompt = typed or prompt
    if prompt:
        # Redact the configured secret even if a user accidentally pastes it.
        if key:
            prompt = prompt.replace(key, '[REDACTED]')
        history = [{'role': m['role'], 'content': m.get('content') or m['result'].get('report')}
                   for m in chat[-8:]]
        chat.append({'role': 'user', 'content': prompt})
        with st.chat_message('user'):
            st.write(prompt)
        with st.chat_message('assistant'):
            with st.status('Investigating synthetic metrics…', expanded=True) as status:
                result = run_agent(prompt, service, start, end, history,
                                   on_step=lambda step: st.write(f"{step['tool']}: {'completed' if 'findings' in step['result'] else 'failed'}"))
                status.update(label='Investigation complete' if not result['error'] else 'Investigation needs attention',
                              state='complete' if not result['error'] else 'error', expanded=False)
            _result(result)
        chat.append({'role': 'assistant', 'result': result})
