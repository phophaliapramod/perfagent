"""Cross-service hourly degradation signals, not a causal or SLO score."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from thresholds import get_thresholds

METRICS = ['p95_latency_ms', 'p99_latency_ms', 'error_rate_pct', 'cpu_utilization_pct', 'memory_utilization_pct']


def build_heatmap(frame, services, start, end, selected_service=None):
    hours = pd.date_range(start, end, freq='h', inclusive='left')
    environments = sorted(frame.environment.unique()) if not frame.empty else ['production']
    scores, hover, labels = [], [], []
    for service in services:
        profile = get_thresholds(service)
        for environment in environments:
            rows = frame[(frame.service == service) & (frame.environment == environment)].set_index('timestamp')
            # Keep environments separate: a healthy environment must not hide another's signals.
            values, details = [], []
            for timestamp in hours:
                prefix = f'{service} · {environment}<br>{timestamp:%Y-%m-%d %H:%M} UTC'
                if timestamp not in rows.index:
                    values.append(-1); details.append(prefix + '<br>No hourly sample available')
                    continue
                row = rows.loc[timestamp]
                signals = []
                if row.p95_latency_ms > profile['p95_ms'] or row.p99_latency_ms > profile['p99_ms']:
                    signals.append('Latency')
                for name, column, key in [('Errors', 'error_rate_pct', 'errors_pct'),
                                          ('CPU', 'cpu_utilization_pct', 'cpu_pct'),
                                          ('Memory', 'memory_utilization_pct', 'memory_pct')]:
                    if row[column] > profile[key]: signals.append(name)
                missing = row[METRICS].isna().any()
                values.append(-1 if missing else len(signals))
                detail = prefix + '<br>' + ('Incomplete metric evidence' if missing else f'{len(signals)} of 4 signal groups above thresholds')
                detail += '<br>Observed exceedances: ' + (', '.join(signals) or 'none')
                for label, column, key, unit in [('P95', 'p95_latency_ms', 'p95_ms', 'ms'),
                        ('P99', 'p99_latency_ms', 'p99_ms', 'ms'), ('Errors', 'error_rate_pct', 'errors_pct', '%'),
                        ('CPU', 'cpu_utilization_pct', 'cpu_pct', '%'), ('Memory', 'memory_utilization_pct', 'memory_pct', '%')]:
                    value = 'missing' if pd.isna(row[column]) else f'{row[column]:.2f} {unit}'
                    detail += f'<br>{label}: {value} · limit > {profile[key]:g} {unit}'
                details.append(detail)
            scores.append(values); hover.append(details)
            labels.append(f'{service} / {environment}' + (' (selected)' if service == selected_service else ''))
    fig = go.Figure(go.Heatmap(x=hours, y=labels, z=scores, text=hover,
        hovertemplate='%{text}<extra></extra>', zmin=-1, zmax=4, xgap=1, ygap=5,
        colorscale=[[0, '#64748b'], [.099, '#64748b'], [.1, '#d1fae5'], [.299, '#d1fae5'],
                    [.3, '#fde68a'], [.499, '#fde68a'], [.5, '#fb923c'], [.699, '#fb923c'],
                    [.7, '#ef4444'], [.899, '#ef4444'], [.9, '#991b1b'], [1, '#991b1b']],
        colorbar={'title': 'Signals', 'tickvals': [-1, 0, 1, 2, 3, 4],
                  'ticktext': ['Missing', '0', '1', '2', '3', '4']}))
    fig.update_layout(height=max(320, len(labels)*65+170), xaxis_title='Hourly sample timestamp (UTC)',
                      yaxis={'autorange': 'reversed'}, margin={'l': 20, 'r': 20, 't': 15, 'b': 45})
    return fig


def render_heatmap(frame, services, start, end, selected_service):
    st.subheader('Service degradation heatmap')
    st.caption('All services in the selected date range. The sidebar service remains selected for the other views.')
    st.plotly_chart(build_heatmap(frame, services, start, end, selected_service), width='stretch')
    st.caption('Each cell is one hourly sample. Color counts affected signal groups: latency (P95 or P99), errors, CPU, and memory, using saved service-specific thresholds. Green = 0; yellow through red = 1–4; gray = missing or incomplete evidence. Hover for values and limits. Counts indicate threshold exceedances, not comparable business severity or a confirmed cause.')
