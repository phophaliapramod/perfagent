"""Readable deterministic reports, backed by the shared filtered samples."""
import json
import pandas as pd
import streamlit as st
from timeline import build_timeline, SIGNALS
from agent_tools import _json_safe

METRIC_LABELS = {
    'p95_latency_ms': ('Mean hourly P95', 'ms'),
    'p99_latency_ms': ('Mean hourly P99', 'ms'),
    'throughput_rps': ('Mean throughput', 'req/s'),
    'error_rate_pct': ('Mean hourly error rate', '%'),
    'cpu_utilization_pct': ('Mean CPU', '%'),
    'memory_utilization_pct': ('Mean memory', '%'),
}


def summarize_window(frame):
    samples, episodes = build_timeline(frame)
    abnormal = samples[samples.State == 'Abnormal']
    overlap = (samples['P95 latency'] | samples['P99 latency']) & samples.Errors
    incomplete = frame[[v[0] for v in SIGNALS.values()]].isna().any(axis=1)
    if frame.empty:
        severity = 'Insufficient data'
        summary = 'No samples are available in the selected window.'
    elif overlap.any():
        severity = 'High (heuristic)'
        summary = f'Latency and errors exceeded thresholds together in {int(overlap.sum())} hourly samples. {len(episodes)} threshold episodes were detected.'
    elif not abnormal.empty:
        severity = 'Elevated (heuristic)'
        summary = f'{len(abnormal)} of {len(samples)} hourly samples exceeded at least one threshold across {len(episodes)} episodes.'
    elif incomplete.any():
        severity = 'Insufficient data'
        summary = 'No exceedances were observed, but incomplete samples prevent establishing normal performance.'
    else:
        severity = 'No threshold exceedances'
        summary = f'No configured threshold exceedances were observed in {len(samples)} available hourly samples.'
    return {'severity': severity, 'summary': summary, 'sample_count': len(samples),
            'abnormal_samples': len(abnormal), 'episode_count': len(episodes),
            'first_abnormal_utc': None if abnormal.empty else str(abnormal.timestamp.min()),
            'last_abnormal_utc': None if abnormal.empty else str(abnormal.timestamp.max()),
            'overlap_samples': int(overlap.sum()), 'episodes': episodes}


def comparison_table(baseline):
    rows = []
    def value(number, unit):
        return 'Unavailable' if number is None or pd.isna(number) else f'{number:,.2f} {unit}'
    for item in baseline['evidence']:
        label, unit = METRIC_LABELS.get(item['metric'], (item['metric'], ''))
        rows.append({'Metric': label, 'Selected window': value(item['observed_mean'], unit),
                     'Preceding baseline': value(item['baseline_mean'], unit),
                     'Relative change': value(item['change_pct'], '%')})
    return pd.DataFrame(rows)


def render_investigation(finding, frame):
    context = summarize_window(frame)
    st.markdown('**Window finding**')
    st.write(context['summary'])
    cols = st.columns(3)
    cols[0].markdown('**Window severity**')
    cols[0].write(context['severity'])
    cols[1].metric('Abnormal samples', f"{context['abnormal_samples']} / {context['sample_count']}")
    cols[2].metric('Threshold episodes', context['episode_count'])
    st.caption('Severity is a demonstration rule: high = latency and errors exceed thresholds in the same sample; elevated = another exceedance. It is not a production incident classification. Sample counts include separate environments. No exceedance is not proof of health.')
    if context['first_abnormal_utc']:
        st.caption(f"First abnormal sample: {context['first_abnormal_utc']} UTC • Last abnormal sample: {context['last_abnormal_utc']} UTC")
    st.markdown('**Question finding**')
    st.caption(f"{finding['service']} • {finding['time_window']['start_utc']} UTC to {finding['time_window']['end_utc_exclusive']} UTC (end exclusive)")
    observed = finding['observed_values']
    for paragraph in finding.get('answer', [finding['possible_interpretation']]):
        st.write(paragraph)
    if finding.get('key_metrics'):
        with st.expander('Measured values for this service'):
            st.dataframe(pd.DataFrame(finding['key_metrics']), width='stretch', hide_index=True)
    comparison = finding['comparison_values_or_thresholds']
    baseline = comparison.get('baseline')
    if 'baseline_sample_count' in comparison:
        baseline = finding
    if baseline:
        st.markdown('**Baseline changes**')
        values = baseline['comparison_values_or_thresholds']
        st.caption(f"Baseline: {values['baseline_start_utc']} UTC to {values['baseline_end_utc_exclusive']} UTC (end exclusive) • {values['baseline_sample_count']} samples")
        st.dataframe(comparison_table(baseline), width='stretch', hide_index=True)
        if not values['baseline_sample_count']:
            st.warning(
                f"The preceding baseline ({values['baseline_start_utc']} UTC to "
                f"{values['baseline_end_utc_exclusive']} UTC, end exclusive) contains no samples for this service. "
                'The baseline uses the same duration immediately before your selected window. '
                f'Keep {finding["service"]} selected and choose a later or narrower window. '
                'For this dataset, October 5–5 compares October 5 with October 4 for any of the three services. '
                'Your current-window findings and Incident Timeline remain valid without a baseline.')
        else:
            st.caption('Changes compare unweighted hourly means. A preceding window is not automatically healthy; relative error-rate change is not a percentage-point difference.')
    if 'latency_and_errors_hours' in observed:
        st.markdown('**Correlated signals**')
        st.write(f"Latency + errors: {observed['latency_and_errors_hours']} samples. Latency + CPU: {observed['latency_and_cpu_hours']} samples.")
    st.markdown('**Hypotheses — unconfirmed**')
    if finding['hypotheses']:
        for hypothesis in finding['hypotheses']:
            st.write('• ' + hypothesis['statement'])
    else:
        st.caption('This investigation does not establish a cause or rank hypotheses.')
    st.caption('Confirmed causes: none. Aggregate synthetic metrics cannot confirm a root cause.')
    actions = finding.get('recommended_actions') or [
        'Inspect the timestamped evidence and Incident Timeline for affected samples.',
        'Check read-only logs, dependency timings, and workload changes for those UTC periods.',
        'Compare with a complete baseline before attributing a cause.']
    st.markdown('**Suggested troubleshooting checks**')
    for index, action in enumerate(actions, 1):
        st.write(f'{index}. {action}')
    with st.expander('Affected episodes and hourly evidence'):
        if not context['episodes'].empty:
            st.dataframe(context['episodes'], width='stretch', hide_index=True)
        if finding['evidence']:
            st.dataframe(pd.DataFrame(finding['evidence']), width='stretch', hide_index=True)
        else:
            st.info('No evidence rows matched this investigation.')
        if baseline:
            for label in ['current_evidence', 'baseline_evidence']:
                rows = baseline['comparison_values_or_thresholds'].get(label, [])
                if rows:
                    st.caption(label.replace('_', ' ').capitalize())
                    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    with st.expander('Structured findings (JSON)'):
        safe = _json_safe(finding)
        st.json(safe)
        st.download_button('Download investigation JSON', json.dumps(safe, indent=2, allow_nan=False),
                           'investigation.json', 'application/json')
