"""Service-specific deterministic answers derived only from returned evidence."""
import pandas as pd
from metrics import aggregate_metrics

LABELS = {'p95_latency_ms': ('hourly P95', 'ms'), 'p99_latency_ms': ('hourly P99', 'ms'),
          'throughput_rps': ('throughput', 'req/s'), 'error_rate_pct': ('hourly error rate', '%'),
          'cpu_utilization_pct': ('CPU utilization', '%'), 'memory_utilization_pct': ('memory utilization', '%')}


def number(value, unit=''):
    if value is None or pd.isna(value):
        return 'unavailable'
    return f'{value:,.2f} {unit}'.strip()


def build_answer(kind, finding, frame):
    """Use the selected service/window for every answer, including normal windows."""
    service = finding['service']
    count = len(frame)
    answer = []
    actions = []
    metrics = aggregate_metrics(frame)
    if not count:
        return {'answer': [f'No samples were found for {service} in the selected UTC window. No performance conclusion is possible.'],
                'recommended_actions': ['Choose a service and date range with available data.'], 'key_metrics': []}
    obs = finding['observed_values']
    comparison = finding['comparison_values_or_thresholds']
    if kind == 'get_service_metrics':
        answer.append(f'{service}: {count} hourly samples and {metrics["request_count"]:,} requests were recorded.')
        answer.append(f'Mean throughput was {number(metrics["mean_throughput_rps"], "req/s")}. Worst observed hourly P95/P99 were {number(metrics["worst_hourly_p95_ms"], "ms")} / {number(metrics["worst_hourly_p99_ms"], "ms")}.')
        answer.append(f'Request-weighted error rate was {number(metrics["request_weighted_error_rate_pct"], "%")}; unweighted hourly mean was {number(metrics["mean_hourly_error_rate_pct"], "%")}.')
        actions = ['Use latency, error, or resource questions to locate threshold exceedances in this window.']
    elif kind in ['detect_latency_anomalies', 'detect_error_spikes', 'analyze_resource_utilization']:
        hits = obs['samples_above_threshold']
        answer.append(f'{service}: {hits} of {count} hourly samples exceeded the thresholds for this question.')
        if kind == 'detect_latency_anomalies':
            answer.append(f'Worst observed hourly P95 was {number(metrics["worst_hourly_p95_ms"], "ms")} (threshold > {number(comparison["p95_threshold_ms"], "ms")}); P99 was {number(metrics["worst_hourly_p99_ms"], "ms")} (threshold > {number(comparison["p99_threshold_ms"], "ms")}).')
            actions = ['Inspect request and dependency timings at the listed slow samples.', 'Compare workload mix and latency against a complete preceding baseline.']
        elif kind == 'detect_error_spikes':
            answer.append(f'Peak hourly error rate was {number(frame.error_rate_pct.max(), "%")} against a > {number(comparison["error_rate_threshold_pct"], "%")} threshold. Request-weighted error rate was {number(metrics["request_weighted_error_rate_pct"], "%")}.')
            actions = ['Inspect error types, status codes, and dependency failures at the listed UTC samples.']
        else:
            cpu_hits = int((frame.cpu_utilization_pct > comparison['cpu_threshold_pct']).sum())
            memory_hits = int((frame.memory_utilization_pct > comparison['memory_threshold_pct']).sum())
            answer.append(f'CPU: mean {number(metrics["mean_cpu_pct"], "%")}, peak {number(frame.cpu_utilization_pct.max(), "%")}; {cpu_hits} samples above {number(comparison["cpu_threshold_pct"], "%")}.')
            answer.append(f'Memory: mean {number(metrics["mean_memory_pct"], "%")}, peak {number(frame.memory_utilization_pct.max(), "%")}; {memory_hits} samples above {number(comparison["memory_threshold_pct"], "%")}.')
            actions = ['Check CPU profiles, queue depth, and memory/GC telemetry during resource exceedances; aggregate utilization cannot establish saturation or a leak.']
        if hits:
            timestamps = [row['timestamp'] for row in finding['evidence']]
            answer.append(f'First matching sample: {min(timestamps)}. Last matching sample: {max(timestamps)}. These bounds do not imply a continuous incident.')
        else:
            answer.append('No matching exceedances were observed. This does not rule out smaller changes, missing evidence, or request-level problems.')
            actions = ['Compare the observed values with service-specific SLOs and the preceding baseline before assuming normal performance.']
    elif kind == 'investigate_degradation':
        answer.append(f'{service}: high latency in {obs["high_latency_hours"]} of {count} samples, errors in {obs["high_error_hours"]}, CPU in {obs["high_cpu_hours"]}, and memory in {obs["high_memory_hours"]}.')
        answer.append(f'Latency and errors coincided in {obs["latency_and_errors_hours"]} samples; latency and CPU in {obs["latency_and_cpu_hours"]}.')
        if not any(obs[key] for key in ['high_latency_hours', 'high_error_hours', 'high_cpu_hours', 'high_memory_hours']):
            answer.append('No configured threshold exceedances were observed for this service. Baseline shifts may still be present; this is not proof of health.')
        actions = finding.get('recommended_actions', []) if finding['hypotheses'] else ['Review service SLOs and baseline changes; no threshold-based root-cause hypothesis is supported by this window.']
    baseline = finding if kind == 'compare_with_baseline' else comparison.get('baseline')
    if baseline:
        baseline_values = baseline['comparison_values_or_thresholds']
        baseline_count = baseline_values['baseline_sample_count']
        if baseline_count:
            answer.append(f'{service}: comparing {count} current samples with {baseline_count} preceding-window samples.')
            for row in baseline['evidence']:
                label, unit = LABELS[row['metric']]
                if row['change_pct'] is not None:
                    direction = 'increased' if row['change_pct'] > 0 else 'decreased' if row['change_pct'] < 0 else 'was unchanged'
                    change = f' by {abs(row["change_pct"]):.1f}%' if row['change_pct'] else ''
                    answer.append(f'Mean {label} {direction}{change}: {number(row["baseline_mean"], unit)} → {number(row["observed_mean"], unit)}.')
                else:
                    answer.append(f'Mean {label}: baseline {number(row["baseline_mean"], unit)}, selected window {number(row["observed_mean"], unit)}; relative change unavailable.')
            if baseline_count != count:
                answer.append('The windows have different sample counts; coverage is unequal, so compare cautiously.')
            if kind == 'compare_with_baseline':
                actions = ['Check whether the preceding window is representative and healthy before interpreting its means as a baseline.']
        else:
            answer.append(f'No preceding baseline samples exist for {service} in {baseline_values["baseline_start_utc"]} to {baseline_values["baseline_end_utc_exclusive"]} UTC (end exclusive). Current-window measurements are still available.')
            actions = [f'Keep {service} selected and choose a later or shorter date range so the preceding equal-duration window overlaps available data.'] + actions
    missing = int(frame[[*LABELS]].isna().any(axis=1).sum())
    if missing:
        answer.append(f'{missing} hourly samples have missing metric values. Missing values do not count as exceedances and cannot establish normality.')
    key_metrics = [{'Metric': label, 'Observed hourly mean': number(frame[column].mean(), unit),
                    'Observed hourly peak': number(frame[column].max(), unit)}
                   for column, (label, unit) in LABELS.items()]
    return {'answer': answer, 'recommended_actions': actions, 'key_metrics': key_metrics}
