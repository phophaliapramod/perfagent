"""Validated persistent service thresholds; defaults are demonstration heuristics."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from validation import validate_threshold

CONFIG_PATH = Path(__file__).resolve().parent / 'thresholds.json'
DEFAULTS = {'p95_ms': 500.0, 'p99_ms': 1000.0, 'errors_pct': 1.0, 'cpu_pct': 80.0, 'memory_pct': 80.0}


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != set(DEFAULTS):
        raise ValueError('Threshold profile must contain P95, P99, errors, CPU, and memory limits.')
    return {key: float(validate_threshold(value, key, 100 if key.endswith('_pct') else None))
            for key, value in profile.items()}


def load_profiles(path=None):
    target = Path(path) if path is not None else CONFIG_PATH
    if not target.exists():
        return {}
    try:
        profiles = json.loads(target.read_text())
        if not isinstance(profiles, dict):
            raise ValueError('Expected service profiles.')
        return {service: validate_profile(profile) for service, profile in profiles.items()}
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid thresholds.json. Correct its profiles or restore the file before investigating.') from exc


def get_thresholds(service, path=None):
    return load_profiles(path).get(service, DEFAULTS.copy())


def save_thresholds(service, profile, path=None):
    if not isinstance(service, str) or not service.strip():
        raise ValueError('A service is required.')
    profile = validate_profile(profile)
    target = Path(path) if path is not None else CONFIG_PATH
    profiles = load_profiles(target)
    profiles[service] = profile
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', dir=target.parent, suffix='.json', delete=False) as file:
            temporary = file.name
            json.dump(profiles, file, indent=2, allow_nan=False)
            file.write('\n')
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return profile


def threshold_caption(service):
    p = get_thresholds(service)
    return (f'{service}: P95 > {p["p95_ms"]:g} ms; P99 > {p["p99_ms"]:g} ms; '
            f'errors > {p["errors_pct"]:g}%; CPU > {p["cpu_pct"]:g}%; memory > {p["memory_pct"]:g}%.')
