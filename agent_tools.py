"""Allowlisted read-only interfaces. No SQL, shell, or database-path parameters.

Inputs: service string and ISO-8601 start/end (naive timestamps mean UTC).
Outputs: strict JSON-compatible findings. Unknown services return empty findings.
Raises ValueError on invalid parameters. Application owns database initialization.
"""
import json
import math
import analysis
from validation import validate_window, validate_threshold


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _run(function, service, start, end, **kwargs):
    service, start, end = validate_window(service, start, end)
    result = _json_safe(function(service, start, end, **kwargs))
    json.dumps(result, allow_nan=False)
    return result


def get_service_metrics(service, start, end):
    return _run(analysis.get_service_metrics, service, start, end)


def detect_latency_anomalies(service, start, end, p95_threshold_ms=None, p99_threshold_ms=None):
    return _run(analysis.detect_latency_anomalies, service, start, end,
                p95_threshold_ms=None if p95_threshold_ms is None else validate_threshold(p95_threshold_ms, 'P95 threshold'),
                p99_threshold_ms=None if p99_threshold_ms is None else validate_threshold(p99_threshold_ms, 'P99 threshold'))


def detect_error_spikes(service, start, end, threshold_pct=None):
    return _run(analysis.detect_error_spikes, service, start, end,
                threshold_pct=None if threshold_pct is None else validate_threshold(threshold_pct, 'Error threshold', 100))


def analyze_resource_utilization(service, start, end, cpu_threshold_pct=None, memory_threshold_pct=None):
    return _run(analysis.analyze_resource_utilization, service, start, end,
                cpu_threshold_pct=None if cpu_threshold_pct is None else validate_threshold(cpu_threshold_pct, 'CPU threshold', 100),
                memory_threshold_pct=None if memory_threshold_pct is None else validate_threshold(memory_threshold_pct, 'Memory threshold', 100))


def compare_with_baseline(service, start, end):
    return _run(analysis.compare_with_baseline, service, start, end)


TOOLS = {function.__name__: function for function in (
    get_service_metrics, detect_latency_anomalies, detect_error_spikes,
    analyze_resource_utilization, compare_with_baseline)}
