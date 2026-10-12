"""Shared overview aggregation; rates are percentages, throughput is req/s."""
import math


def aggregate_metrics(frame):
    def number(value):
        return float(value) if value is not None and math.isfinite(float(value)) else None
    valid = frame.dropna(subset=['error_rate_pct', 'request_count'])
    valid = valid[valid.request_count > 0]
    count = valid.request_count.sum()
    return {
        'worst_hourly_p95_ms': number(frame.p95_latency_ms.max()),
        'worst_hourly_p99_ms': number(frame.p99_latency_ms.max()),
        'mean_throughput_rps': number(frame.throughput_rps.mean()),
        'mean_hourly_error_rate_pct': number(frame.error_rate_pct.mean()),
        'request_weighted_error_rate_pct': number((valid.error_rate_pct * valid.request_count).sum() / count) if count > 0 else None,
        'request_count': int(frame.request_count.sum()),
        'mean_cpu_pct': number(frame.cpu_utilization_pct.mean()),
        'mean_memory_pct': number(frame.memory_utilization_pct.mean()),
    }
