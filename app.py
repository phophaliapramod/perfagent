"""PerfAgent Stage 1: synthetic performance dashboard without an LLM."""
from datetime import datetime, time, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from db import initialize_database, dataset_summary, read_metrics, read_all_service_metrics
from analysis import EXAMPLE_QUESTIONS, investigate
from metrics import aggregate_metrics
from ai_ui import render_ai_agent
from timeline import render_timeline
from degradation_heatmap import render_heatmap
from investigation_ui import render_investigation
from thresholds import get_thresholds, save_thresholds, DEFAULTS, threshold_caption

st.set_page_config(page_title='PerfAgent', page_icon='📊', layout='wide')
st.title('PerfAgent')
st.caption('PerfAgent • Deterministic dashboard + optional AI investigations • Synthetic data • All timestamps UTC')
try:
    initialize_database()
    services, first, last, total = dataset_summary()
except Exception as exc:
    st.error(f'Unable to initialize local metrics: {exc}. Check data/performance_metrics.csv and database write permissions.')
    st.stop()
if not services or first is None:
    st.warning('The metrics dataset is empty. Add samples to the CSV and restart.')
    st.stop()

with st.sidebar:
    st.header('Shared filters')
    service = st.selectbox('Service', services)
    try:
        profile = get_thresholds(service)
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        st.stop()
    with st.expander('Service thresholds'):
        st.caption('Saved per service. Initial values are demonstration heuristics, not established SLOs. Samples strictly above a limit are flagged.')
        with st.form(f'thresholds_{service}'):
            limits = {}
            for key, label in [('p95_ms', 'P95 latency limit (ms)'), ('p99_ms', 'P99 latency limit (ms)'),
                               ('errors_pct', 'Error rate limit (%)'), ('cpu_pct', 'CPU limit (%)'),
                               ('memory_pct', 'Memory limit (%)')]:
                limits[key] = st.number_input(label, min_value=0.0,
                    max_value=100.0 if key.endswith('_pct') else None,
                    value=profile[key], key=f'threshold_{service}_{key}',
                    step=0.1 if key == 'errors_pct' else 1.0)
            apply = st.form_submit_button('Save service thresholds')
            reset = st.form_submit_button('Reset this service to defaults')
        if apply or reset:
            try:
                save_thresholds(service, DEFAULTS if reset else limits)
                if reset:
                    for key in DEFAULTS:
                        del st.session_state[f'threshold_{service}_{key}']
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(f'Thresholds could not be saved: {exc}')
    dates = st.date_input('Date range (UTC, both dates included)',
                          value=(first.date(), last.date()), min_value=first.date(), max_value=last.date())
    st.caption(f'{total:,} synthetic samples in the local database')
if not isinstance(dates, (tuple, list)) or len(dates) != 2:
    st.info('Select a start and end date to view metrics.')
    st.stop()
start = datetime.combine(dates[0], time.min)
end = datetime.combine(dates[1] + timedelta(days=1), time.min)
try:
    frame = read_metrics(service, start, end)
except Exception as exc:
    st.error(f'Unable to read metrics: {exc}')
    st.stop()
if frame.empty:
    st.warning('No samples match this service and UTC date range. Choose another window.')
    st.stop()
st.caption(f'{service} • {start:%Y-%m-%d %H:%M} UTC to {end:%Y-%m-%d %H:%M} UTC (end exclusive) • {len(frame):,} samples')
overview, trends, investigations, raw, ai_tab, timeline_tab = st.tabs(['Overview', 'Performance Trends', 'Investigations', 'Raw Data', 'AI Agent', 'Incident Timeline'])
with overview:
    try:
        render_heatmap(read_all_service_metrics(start, end), services, start, end, service)
    except (ValueError, OSError) as exc:
        st.error(f'Heatmap unavailable: {exc}')
    st.subheader('Selected window')
    metrics = aggregate_metrics(frame)
    def kpi(column, label, value, unit=''):
        column.metric(label, f'{value:,.1f}' if value is not None else 'N/A')
        column.caption(unit)
    cols = st.columns(3)
    kpi(cols[0], 'Worst hourly P95', metrics['worst_hourly_p95_ms'], 'milliseconds (ms)')
    kpi(cols[1], 'Worst hourly P99', metrics['worst_hourly_p99_ms'], 'milliseconds (ms)')
    kpi(cols[2], 'Mean throughput', metrics['mean_throughput_rps'], 'requests per second (req/s)')
    cols = st.columns(2)
    for column, label, key in [(cols[0], 'Mean hourly error rate', 'mean_hourly_error_rate_pct'),
                               (cols[1], 'Request-weighted error rate', 'request_weighted_error_rate_pct')]:
        value = metrics[key]
        column.metric(label, f'{value:.2f}%' if value is not None else 'N/A')
    st.info('Latency cards show the maximum observed hourly percentile, not pooled request-level percentiles. '
            'The hourly mean error rate is unweighted; the request-weighted rate is '
            'Σ(hourly error rate × request count) / Σ(request count), using valid samples with positive request counts. '
            'It is approximate because the source hourly rates are rounded.')
    cols = st.columns(3)
    cols[0].metric('Requests', f'{metrics["request_count"] / 1_000_000:.2f} M')
    cols[0].caption(f'{metrics["request_count"]:,} requests total')
    cols[1].metric('Mean CPU', f'{frame.cpu_utilization_pct.mean():.1f}%')
    cols[2].metric('Mean memory', f'{frame.memory_utilization_pct.mean():.1f}%')
    st.caption('Synthetic observations are for exploration. Coincident latency, errors, and utilization do not establish root cause.')


def chart(columns, title, unit, height=450, markers=False):
    melted = frame.melt(id_vars=['timestamp', 'environment'], value_vars=columns,
                        var_name='Metric', value_name=unit)
    fig = px.line(melted, x='timestamp', y=unit, color='Metric', line_dash='environment',
                  title=title, markers=markers, labels={'timestamp': 'Timestamp (UTC)'})
    fig.update_layout(legend_title_text='Metric', hovermode='x unified', height=height)
    if markers:
        fig.update_traces(marker_size=6, line_width=2)
    threshold_keys = {'p95_latency_ms': 'p95_ms', 'p99_latency_ms': 'p99_ms',
                      'error_rate_pct': 'errors_pct', 'cpu_utilization_pct': 'cpu_pct',
                      'memory_utilization_pct': 'memory_pct'}
    for column in columns:
        if column in threshold_keys:
            limit = profile[threshold_keys[column]]
            fig.add_hline(y=limit, line_dash='dot', line_color='#d97706',
                          annotation_text=f'{column.split("_")[0].upper()} limit {limit:g}',
                          annotation_position='top left')

    st.plotly_chart(fig, width='stretch')


with trends:
    chart(['p95_latency_ms', 'p99_latency_ms'], 'Latency trends', 'Latency (ms)')
    chart(['throughput_rps'], 'Throughput', 'Throughput (req/s)', height=520, markers=True)
    chart(['error_rate_pct'], 'Error rate', 'Error rate (%)', height=520, markers=True)
    chart(['cpu_utilization_pct'], 'CPU utilization', 'CPU utilization (%)', height=520, markers=True)
    chart(['memory_utilization_pct'], 'Memory utilization', 'Memory utilization (%)', height=520, markers=True)
with investigations:
    st.subheader('Investigations')
    st.write('Ask about degradation, latency, errors, resources, or baseline changes. These deterministic rules use the sidebar service and UTC dates; dates or service names typed in the question do not change the filters. No LLM or API key is involved.')
    st.caption(threshold_caption(service) + ' Edit these limits in the sidebar.')
    example = st.selectbox('Example troubleshooting questions', list(EXAMPLE_QUESTIONS))
    with st.form('investigation'):
        question = st.text_input('Question (leave blank to use the selected example)')
        submitted = st.form_submit_button('Investigate')
    # Results are recomputed on reruns so changing shared filters cannot leave stale evidence.
    if submitted:
        st.session_state['investigation_question'] = question.strip() or example
    if 'investigation_question' in st.session_state:
        st.write(f"**Question:** {st.session_state['investigation_question']}")
        try:
            finding = investigate(st.session_state['investigation_question'], service, start, end)
            render_investigation(finding, frame)
        except ValueError as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error(f'Investigation could not run: {exc}')
with raw:
    st.subheader('Raw synthetic metrics')
    display = frame.copy()
    display['timestamp'] = display.timestamp.astype(str) + ' UTC'
    st.dataframe(display, width='stretch', hide_index=True)
    st.download_button('Download filtered CSV', display.to_csv(index=False),
                       file_name=f'{service}_metrics.csv', mime='text/csv')

with ai_tab:
    render_ai_agent(service, start, end)

with timeline_tab:
    render_timeline(frame)
