"""Deterministic findings. Thresholds are heuristics, not production SLOs."""
import pandas as pd
from thresholds import get_thresholds
from db import read_metrics, DEFAULT_DB
from metrics import aggregate_metrics
from validation import validate_window, validate_threshold


def _finding(service, start, end, observed, comparison, evidence, interpretation):
    service, start, end = validate_window(service, start, end)
    return {'service': service, 'time_window': {'start_utc': str(start),
            'end_utc_exclusive': str(end)}, 'observed_values': observed,
            'comparison_values_or_thresholds': {**comparison, 'service_thresholds': get_thresholds(service)}, 'evidence': evidence,
            'possible_interpretation': interpretation,
            'observations': {'summary': observed, 'evidence': evidence},
            'hypotheses': ([{'statement': interpretation, 'status': 'unconfirmed'}]
                           if observed.get('samples_above_threshold', 0) > 0 else []),
            'confirmed_causes': []}


def _evidence(frame, columns):
    result = frame[['timestamp', 'environment', *columns]].copy()
    result['timestamp'] = result['timestamp'].astype(str) + ' UTC'
    return result.to_dict('records')


def get_service_metrics(service, start, end, db_path=DEFAULT_DB):
    frame = read_metrics(service, start, end, db_path)
    columns = ['throughput_rps', 'p95_latency_ms', 'p99_latency_ms', 'error_rate_pct',
               'cpu_utilization_pct', 'memory_utilization_pct']
    return _finding(service, start, end,
                    {'sample_count': len(frame), 'means': frame[columns].mean().dropna().to_dict(),
                     'aggregations': aggregate_metrics(frame)},
                    {}, _evidence(frame, columns),
                    'Hourly synthetic samples; no data in this window.' if frame.empty else
                    'Summary of the selected synthetic service and UTC window.')


def detect_latency_anomalies(service, start, end, db_path=DEFAULT_DB,
                             p95_threshold_ms=None, p99_threshold_ms=None):
    profile = get_thresholds(service)
    p95_threshold_ms = profile['p95_ms'] if p95_threshold_ms is None else p95_threshold_ms
    p99_threshold_ms = profile['p99_ms'] if p99_threshold_ms is None else p99_threshold_ms
    validate_threshold(p95_threshold_ms, 'P95 threshold')
    validate_threshold(p99_threshold_ms, 'P99 threshold')
    frame = read_metrics(service, start, end, db_path)
    hits = frame[(frame.p95_latency_ms > p95_threshold_ms) |
                 (frame.p99_latency_ms > p99_threshold_ms)]
    return _finding(service, start, end,
                    {'samples_above_threshold': len(hits), 'total_samples': len(frame)},
                    {'p95_threshold_ms': p95_threshold_ms, 'p99_threshold_ms': p99_threshold_ms},
                    _evidence(hits, ['p95_latency_ms', 'p99_latency_ms']),
                    'Elevated latency may indicate contention or slower dependencies; this does not establish a cause.'
                    if len(hits) else 'No latency threshold exceedances in available samples; an empty window cannot establish normal performance.')


def detect_error_spikes(service, start, end, db_path=DEFAULT_DB, threshold_pct=None):
    threshold_pct = get_thresholds(service)['errors_pct'] if threshold_pct is None else threshold_pct
    validate_threshold(threshold_pct, 'Error threshold', 100)
    frame = read_metrics(service, start, end, db_path)
    hits = frame[frame.error_rate_pct > threshold_pct]
    return _finding(service, start, end,
                    {'samples_above_threshold': len(hits), 'total_samples': len(frame)},
                    {'error_rate_threshold_pct': threshold_pct},
                    _evidence(hits, ['error_rate_pct']),
                    'Elevated errors warrant checking failures and dependencies; metrics alone do not identify the cause.'
                    if len(hits) else 'No error threshold exceedances in available samples; check sample count before interpreting.')


def analyze_resource_utilization(service, start, end, db_path=DEFAULT_DB,
                                 cpu_threshold_pct=None, memory_threshold_pct=None):
    profile = get_thresholds(service)
    cpu_threshold_pct = profile['cpu_pct'] if cpu_threshold_pct is None else cpu_threshold_pct
    memory_threshold_pct = profile['memory_pct'] if memory_threshold_pct is None else memory_threshold_pct
    validate_threshold(cpu_threshold_pct, 'CPU threshold', 100)
    validate_threshold(memory_threshold_pct, 'Memory threshold', 100)
    frame = read_metrics(service, start, end, db_path)
    columns = ['cpu_utilization_pct', 'memory_utilization_pct']
    hits = frame[(frame.cpu_utilization_pct > cpu_threshold_pct) |
                 (frame.memory_utilization_pct > memory_threshold_pct)]
    return _finding(service, start, end,
                    {'sample_count': len(frame), 'samples_above_threshold': len(hits),
                     'means_pct': frame[columns].mean().dropna().to_dict(),
                     'maxima_pct': frame[columns].max().dropna().to_dict()},
                    {'cpu_threshold_pct': cpu_threshold_pct, 'memory_threshold_pct': memory_threshold_pct},
                    _evidence(hits, columns),
                    'High utilization may coincide with resource pressure. Correlation with latency or errors does not prove causation.')


def compare_with_baseline(service, start, end, db_path=DEFAULT_DB):
    """Compare with the equally long immediately preceding window, without overlap."""
    service, start, end = validate_window(service, start, end)
    if end <= start:
        raise ValueError('End must be after start.')
    baseline_start = start - (end - start)
    current = read_metrics(service, start, end, db_path)
    baseline = read_metrics(service, baseline_start, start, db_path)
    columns = ['p95_latency_ms', 'p99_latency_ms', 'throughput_rps', 'error_rate_pct',
               'cpu_utilization_pct', 'memory_utilization_pct']
    comparisons = []
    for metric in columns:
        observed, reference = current[metric].mean(), baseline[metric].mean()
        comparisons.append({'metric': metric,
            'observed_mean': None if pd.isna(observed) else float(observed),
            'baseline_mean': None if pd.isna(reference) else float(reference),
            'change_pct': None if pd.isna(observed) or pd.isna(reference) or reference == 0
                          else float((observed - reference) / reference * 100)})
    return _finding(service, start, end, {'sample_count': len(current)},
                    {'baseline_start_utc': str(baseline_start), 'baseline_end_utc_exclusive': str(start),
                     'baseline_sample_count': len(baseline),
                     'baseline_evidence': _evidence(baseline, columns),
                     'current_evidence': _evidence(current, columns)}, comparisons,
                    'Comparison uses available hourly samples in the preceding equal-duration window; it is not an established healthy baseline.'
                    if not baseline.empty and not current.empty else
                    'Insufficient current or preceding-window data for a baseline comparison. Select a later or narrower window.')


def investigate_degradation(service, start, end, db_path=DEFAULT_DB):
    """Combine timestamped symptoms and baseline; never infer a confirmed cause."""
    frame = read_metrics(service, start, end, db_path)
    baseline = compare_with_baseline(service, start, end, db_path)
    profile = get_thresholds(service)
    latency = (frame.p95_latency_ms > profile['p95_ms']) | (frame.p99_latency_ms > profile['p99_ms'])
    errors = frame.error_rate_pct > profile['errors_pct']
    cpu = frame.cpu_utilization_pct > profile['cpu_pct']
    memory = frame.memory_utilization_pct > profile['memory_pct']
    evidence = frame.copy()
    evidence['high_latency'] = latency
    evidence['high_errors'] = errors
    evidence['high_cpu'] = cpu
    evidence['high_memory'] = memory
    evidence['timestamp'] = evidence.timestamp.astype(str) + ' UTC'
    result = _finding(service, start, end,
        {'sample_count': len(frame), 'high_latency_hours': int(latency.sum()),
         'high_error_hours': int(errors.sum()), 'high_cpu_hours': int(cpu.sum()),
         'high_memory_hours': int(memory.sum()),
         'latency_and_errors_hours': int((latency & errors).sum()),
         'latency_and_cpu_hours': int((latency & cpu).sum()),
         'aggregations': aggregate_metrics(frame)},
        {'thresholds': profile,
         'baseline': baseline}, evidence.to_dict('records'),
        'Check overlapping symptoms and baseline changes below. Correlation does not confirm a cause.'
        if len(frame) else 'No data in the selected service/window; no conclusion is possible.')
    result['hypotheses'] = []
    if (latency & cpu).any():
        result['hypotheses'].append({'statement': 'CPU pressure may contribute during overlapping high-latency hours.',
                                     'status': 'unconfirmed', 'evidence_hours': int((latency & cpu).sum())})
    if latency.any():
        result['hypotheses'].append({'statement': 'Slower dependencies or workload changes could explain latency; these metrics cannot distinguish them.', 'status': 'unconfirmed'})
    result['recommended_actions'] = [
        'Inspect failure logs and dependency timing for the listed UTC hours.',
        'Compare request mix and deployment history with the preceding baseline.',
        'Check CPU profiles, queue depth, and memory/GC telemetry before attributing a cause.']
    return result


EXAMPLE_QUESTIONS = {
    'What degraded, and which signals coincided?': investigate_degradation,
    'What changed compared with the preceding baseline?': compare_with_baseline,
    'Which hours had slow requests?': detect_latency_anomalies,
    'Which hours had elevated errors?': detect_error_spikes,
    'Was CPU or memory under pressure?': analyze_resource_utilization,
    'Summarize the selected service': get_service_metrics,
}
_LEGACY_QUESTIONS = {
    'Summarize this service': get_service_metrics,
    'When was latency high?': detect_latency_anomalies,
    'When did errors spike?': detect_error_spikes,
    'Was CPU or memory utilization high?': analyze_resource_utilization,
    'How does this window compare with the baseline?': compare_with_baseline,
}


def investigate(question, service, start, end, db_path=DEFAULT_DB):
    """Deterministic intent matching; service/window ALWAYS come from sidebar."""
    import re
    normalized = question.strip().lower().rstrip('?')
    function = next((fn for example, fn in {**EXAMPLE_QUESTIONS, **_LEGACY_QUESTIONS}.items()
                     if normalized == example.lower().rstrip('?')), None)
    words = set(re.findall(r'[a-z]+[0-9]*', normalized))
    if function is not None:
        pass
    elif words & {'cause', 'why', 'incident', 'degraded', 'degradation', 'correlated', 'coincided'}:
        function = investigate_degradation
    elif words & {'baseline', 'compare', 'comparison', 'changed', 'before'}:
        function = compare_with_baseline
    elif words & {'latency', 'slow', 'slower', 'p95', 'p99'}:
        function = detect_latency_anomalies
    elif words & {'error', 'errors', 'failures'}:
        function = detect_error_spikes
    elif words & {'cpu', 'memory', 'resource', 'utilization'}:
        function = analyze_resource_utilization
    elif words & {'summary', 'summarize', 'throughput', 'requests'}:
        function = get_service_metrics
    else:
        raise ValueError('Question not recognized. Ask about degradation, latency, errors, resources, or baseline changes, or select an example. These rules use only the sidebar service and UTC dates.')
    finding = function(service, start, end, db_path)
    from troubleshooting import build_answer
    finding.update(build_answer(function.__name__, finding, read_metrics(service, start, end, db_path)))
    finding['question_type'] = function.__name__
    return finding
