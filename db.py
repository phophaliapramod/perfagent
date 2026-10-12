"""Local ingestion and read-only, parameterized access to synthetic metrics."""
from pathlib import Path
import duckdb
from validation import validate_window

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'perfagent.duckdb'
DEFAULT_CSV = ROOT / 'data' / 'performance_metrics.csv'
COLUMNS = ['timestamp', 'service', 'environment', 'throughput_rps', 'p95_latency_ms',
           'p99_latency_ms', 'error_rate_pct', 'cpu_utilization_pct',
           'memory_utilization_pct', 'request_count']


def initialize_database(db_path=DEFAULT_DB, csv_path=DEFAULT_CSV):
    """Import atomically; each timestamp/service/environment identifies one sample."""
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f'Synthetic metrics CSV not found: {csv_path}')
    with duckdb.connect(str(db_path)) as conn:
        conn.execute('BEGIN TRANSACTION')
        try:
            conn.execute('''CREATE TABLE IF NOT EXISTS performance_metrics (
                timestamp TIMESTAMP NOT NULL, service VARCHAR NOT NULL,
                environment VARCHAR NOT NULL, throughput_rps DOUBLE,
                p95_latency_ms DOUBLE, p99_latency_ms DOUBLE, error_rate_pct DOUBLE,
                cpu_utilization_pct DOUBLE, memory_utilization_pct DOUBLE,
                request_count BIGINT,
                PRIMARY KEY (timestamp, service, environment))''')
            conn.execute('''INSERT INTO performance_metrics
                SELECT timestamp::TIMESTAMP, service, environment, throughput_rps,
                       p95_latency_ms, p99_latency_ms, error_rate_pct,
                       cpu_utilization_pct, memory_utilization_pct, request_count
                FROM read_csv_auto(?) ON CONFLICT DO NOTHING''', [str(csv_path)])
            count = conn.execute('SELECT COUNT(*) FROM performance_metrics').fetchone()[0]
            conn.execute('COMMIT')
            return count
        except Exception:
            conn.execute('ROLLBACK')
            raise


def read_metrics(service, start, end, db_path=DEFAULT_DB):
    """UTC window is start-inclusive, end-exclusive."""
    service, start, end = validate_window(service, start, end)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        return conn.execute('''SELECT * FROM performance_metrics
            WHERE service = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp, environment''', [service, start, end]).fetchdf()


def dataset_summary(db_path=DEFAULT_DB):
    with duckdb.connect(str(db_path), read_only=True) as conn:
        services = [r[0] for r in conn.execute(
            'SELECT DISTINCT service FROM performance_metrics ORDER BY service').fetchall()]
        first, last, count = conn.execute(
            'SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM performance_metrics').fetchone()
    return services, first, last, count


def read_all_service_metrics(start, end, db_path=DEFAULT_DB):
    """Read all services for a parameterized UTC window, for cross-service views."""
    _, start, end = validate_window('all-services', start, end)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        return conn.execute('''SELECT * FROM performance_metrics
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY service, environment, timestamp''', [start, end]).fetchdf()
