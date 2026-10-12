"""Hourly threshold episodes, with explicit gaps and unobserved recovery."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from thresholds import get_thresholds, threshold_caption

SIGNALS = {
    'P95 latency': ('p95_latency_ms', 500, 'ms'),
    'P99 latency': ('p99_latency_ms', 1000, 'ms'),
    'Errors': ('error_rate_pct', 1, '%'),
    'CPU': ('cpu_utilization_pct', 80, '%'),
    'Memory': ('memory_utilization_pct', 80, '%'),
}
def configured_signals(frame):
    profile = get_thresholds(frame.service.iloc[0]) if not frame.empty else get_thresholds('')
    return {label: (column, profile[key], unit) for (label, (column, _, unit)), key
            in zip(SIGNALS.items(), ['p95_ms', 'p99_ms', 'errors_pct', 'cpu_pct', 'memory_pct'])}


EPISODE_COLUMNS = ['Environment', 'First abnormal sample (UTC)', 'Last abnormal sample (UTC)',
                   'Abnormal hourly samples', 'Signals observed', 'First normal sample (UTC)', 'Recovery status']


def build_timeline(frame):
    """Group consecutive abnormal hourly samples within each environment.

    Threshold equality is normal. Missing values cannot establish normality;
    missing hours split episodes and cannot establish recovery.
    """
    samples = frame.copy().sort_values(['environment', 'timestamp']).reset_index(drop=True)
    samples['timestamp'] = pd.to_datetime(samples.timestamp)
    for label, (column, threshold, _) in configured_signals(frame).items():
        samples[label] = samples[column] > threshold
    columns = [signal[0] for signal in SIGNALS.values()]
    samples['Signals'] = samples.apply(lambda row: ', '.join(label for label in SIGNALS if row[label]), axis=1) if len(samples) else pd.Series(dtype=str)
    samples['State'] = 'Within thresholds'
    samples.loc[samples[columns].isna().any(axis=1), 'State'] = 'Incomplete evidence'
    samples.loc[samples[list(SIGNALS)].any(axis=1), 'State'] = 'Abnormal'
    episodes = []
    for environment, group in samples.groupby('environment', sort=True):
        group = group.reset_index(drop=True)
        active = []
        def finish(next_row=None):
            if not active:
                return
            last = active[-1]
            adjacent = next_row is not None and next_row['timestamp'] - last['timestamp'] == pd.Timedelta(hours=1)
            recovered = adjacent and next_row['State'] == 'Within thresholds'
            status = 'Observed return within thresholds' if recovered else (
                'Unknown: missing hour or incomplete evidence' if next_row is not None else 'Recovery not observed in selected window')
            signals = [label for label in SIGNALS if any(row[label] for row in active)]
            episodes.append({'Environment': environment,
                'First abnormal sample (UTC)': active[0]['timestamp'],
                'Last abnormal sample (UTC)': last['timestamp'],
                'Abnormal hourly samples': len(active), 'Signals observed': ', '.join(signals),
                'First normal sample (UTC)': next_row['timestamp'] if recovered else pd.NaT,
                'Recovery status': status})
            active.clear()
        for _, row in group.iterrows():
            if active and (row['timestamp'] - active[-1]['timestamp'] != pd.Timedelta(hours=1) or row['State'] != 'Abnormal'):
                finish(row)
            if row['State'] == 'Abnormal':
                active.append(row)
        finish()
    return samples, pd.DataFrame(episodes, columns=EPISODE_COLUMNS)


def render_timeline(frame):
    st.subheader('Incident timeline')
    st.caption('Synthetic threshold episodes • UTC • ' + threshold_caption(frame.service.iloc[0]))
    samples, episodes = build_timeline(frame)
    cols = st.columns(3)
    cols[0].metric('Threshold episodes', len(episodes))
    cols[1].metric('Abnormal hourly samples', int((samples.State == 'Abnormal').sum()))
    cols[2].metric('Latency + error samples', int(((samples['P95 latency'] | samples['P99 latency']) & samples.Errors).sum()))
    st.info('Episodes group consecutive abnormal hourly samples. First and last samples are observations, not exact incident onset or duration. Recovery means the next consecutive sample is within all thresholds; missing hours and incomplete samples cannot prove recovery. Correlated signals do not confirm a cause.')
    environments = list(samples.environment.unique())
    environment = st.selectbox('Timeline environment', environments, key='timeline_environment') if len(environments) > 1 else environments[0]
    selected = samples[samples.environment == environment]
    selected_episodes = episodes[episodes.Environment == environment]
    fig = go.Figure()
    for label, (column, threshold, unit) in configured_signals(frame).items():
        valid = selected[selected[column].notna()]
        fig.add_trace(go.Scatter(x=valid.timestamp, y=[label] * len(valid), mode='markers',
            marker={'size': 9, 'color': ['#dc2626' if value > threshold else '#94a3b8' for value in valid[column]]},
            customdata=valid[[column]].values,
            hovertemplate=f'%{{x|%Y-%m-%d %H:%M}} UTC<br>{label}: %{{customdata[0]:.2f}} {unit}<br>Threshold: > {threshold:g} {unit}<extra></extra>',
            name=label, showlegend=False))
    for _, episode in selected_episodes.iterrows():
        fig.add_vrect(x0=episode['First abnormal sample (UTC)'],
                      x1=episode['Last abnormal sample (UTC)'] + pd.Timedelta(hours=1),
                      fillcolor='#fee2e2', opacity=0.45, line_width=0, layer='below')
    fig.update_layout(height=400, xaxis_title='Hourly sample timestamp (UTC)', yaxis_title=None,
                      yaxis={'categoryorder': 'array', 'categoryarray': list(reversed(SIGNALS))})
    st.plotly_chart(fig, width='stretch')
    st.caption('Red points exceed thresholds; gray points are within thresholds. Shading covers abnormal sample bins, not verified continuous incident duration. Missing values have no marker.')
    if episodes.empty:
        st.success('No threshold episodes detected in available samples.')
    else:
        st.markdown('**Detected episodes**')
        st.dataframe(episodes, width='stretch', hide_index=True)
    if len(selected) > 1 and (selected.timestamp.diff().dropna() > pd.Timedelta(hours=1)).any():
        st.warning('This environment has missing hourly samples. Gaps split episodes and leave recovery uncertain.')
    if (selected.State == 'Incomplete evidence').any():
        st.warning('Some hourly samples have incomplete metric evidence; they cannot establish normal performance.')
    if not episodes.empty or (selected.State == 'Incomplete evidence').any():
        with st.expander('Hourly evidence (selected environment)', expanded=False):
            evidence = selected[['timestamp', 'environment', 'State', 'Signals', *[v[0] for v in SIGNALS.values()]]].copy()
            evidence['timestamp'] = evidence.timestamp.astype(str) + ' UTC'
            st.dataframe(evidence, width='stretch', hide_index=True)
            st.download_button('Download timeline evidence CSV', evidence.to_csv(index=False),
                               'incident_timeline.csv', 'text/csv')
