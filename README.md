# PerfAgent

**Week 1 project submission — Agentic AI Certification: The Gen Academy**

PerfAgent is a performance troubleshooting dashboard built incrementally with Codex. It helps engineers identify degraded periods, compare metrics with a baseline, and inspect correlated signals using synthetic service data.

The dashboard, investigations, and incident timeline work without an API key or AI credits. An optional OpenAI tool-calling agent is implemented and tested with mocked responses. Live requests were blocked by API quota/billing limits; successful live AI investigations have not been verified.

## Features

- **Overview:** worst observed hourly P95/P99, throughput, request totals, resource utilization, and both hourly-mean and request-weighted error rates.
- **Service degradation heatmap:** all services across the selected UTC date range, with hover evidence and missing-data indicators.
- **Performance Trends:** interactive latency, throughput, error, CPU, and memory charts with hourly markers and threshold reference lines.
- **Investigations:** six deterministic troubleshooting questions, service-specific answers, baseline comparisons, unconfirmed hypotheses, suggested checks, and JSON export.
- **Incident Timeline:** threshold episodes, coincident signals, observed recovery, and downloadable hourly evidence.
- **Service thresholds:** independently saved P95/P99, error, CPU, and memory limits for each service.
- **Raw Data:** filtered evidence and CSV download.
- **AI Agent:** optional chat, bounded tool calling, structured reports, safe errors, and read-only investigation tools.

Shared service and inclusive calendar-date filters control the deterministic views. All timestamps are UTC. The heatmap intentionally shows all services within that date range.

## Quick start

Use Python 3.12 or newer. From the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

On Windows, activate with `.venv\Scripts\activate` instead. Open the local URL printed by Streamlit.

The application creates `perfagent.duckdb` automatically from the supplied CSV. Repeated imports do not duplicate samples: `(timestamp, service, environment)` is the primary key. Existing samples are retained when their keys already exist; edited CSV records are not automatically overwritten.

## Demonstrate the injected incident

1. Select **data-ingestion**.
2. Set both dates to **October 5, 2026**.
3. Inspect the Overview heatmap and Performance Trends.
4. In Investigations, choose **What degraded, and which signals coincided?** and click **Investigate**.
5. Open Incident Timeline to inspect the abnormal hours and observed recovery.

With the default thresholds, latency and errors coincide in all 11 incident samples from 09:00 through 19:00 UTC. CPU exceeds 80% in four of those samples. The next sample at 20:00 UTC returns within thresholds. These are hourly observations, not exact onset times or proof of a root cause.

## Dataset and metric definitions

`data/performance_metrics.csv` contains **504 synthetic hourly rows**: three services with 168 samples each, from October 1 through October 7, 2026. The services are `checkout-api`, `data-ingestion`, and `reporting-service`. The `production` environment is a synthetic label; no production monitoring system is connected.

Fields include UTC timestamp, service, environment, throughput (req/s), P95/P99 latency (ms), error rate (%), CPU/memory utilization (%), and request count. Naive timestamps are interpreted as UTC.

- Worst hourly P95/P99 means the maximum observed hourly percentile. It is not a percentile pooled across requests.
- Mean latency and utilization values are unweighted means of hourly observations.
- Request-weighted error rate is `sum(hourly_error_rate_pct * request_count) / sum(request_count)`, using valid samples with positive counts. Rounded source rates make it approximate.
- A baseline is the immediately preceding equal-duration window, with no overlap. It is not automatically healthy. Selecting the full dataset can leave no preceding baseline; a later or shorter window provides a comparison.
- SQL time windows are start-inclusive and end-exclusive; the UI includes both selected calendar dates.

## Thresholds and evidence

Expand **Service thresholds** in the sidebar and save limits for the selected service. Values persist locally in `thresholds.json`; reset affects only that service. Local profiles are ignored by Git so submissions and tests begin with the documented defaults.

Default demonstration limits are P95 500 ms, P99 1,000 ms, errors 1%, CPU 80%, and memory 80%. Strictly greater values count as exceedances. These are heuristics, not established production SLOs.

The heatmap counts four affected signal groups: latency (P95 or P99), errors, CPU, and memory. Green means zero exceedances; yellow through red means one to four; gray means missing or incomplete evidence. Counts are not equivalent business severity across services.

Severity is high when latency and errors exceed their limits in the same sample, elevated for other exceedances, and insufficient when no conclusion is possible. Missing hours split timeline episodes; incomplete evidence cannot establish recovery. Correlation does not prove causation.

## Optional OpenAI setup

```sh
cp .env.example .env
```

Edit `.env` privately to set `OPENAI_API_KEY`. `OPENAI_MODEL` defaults to `gpt-4.1-mini`; use a model you can access that supports Responses, function calling, and structured outputs. Existing process environment variables take precedence. Restart Streamlit after changing credentials.

Only an explicit chat or example submission makes an API request. Prompts and selected evidence are sent to OpenAI. Never commit `.env` or paste credentials into chat. No key is needed for deterministic features.

The agent exposes only five validated tools: `get_service_metrics`, `detect_latency_anomalies`, `detect_error_spikes`, `analyze_resource_utilization`, and `compare_with_baseline`. It has four tool rounds, at most 12 executions, a 31-day maximum query window, and a 30-second timeout per API request with automatic retries disabled. Tool queries are read-only and parameterized. No arbitrary SQL, shell, Python, or production-operation tool is exposed. Database content is treated as untrusted evidence.

## Validation

```sh
python -m compileall -q . -x '/\.venv/'
python -m unittest -v
```

The latest validated suite has **42 tests** covering database loading and duplicate prevention, metric aggregation, incident detection, invalid parameters, empty results, baseline comparison, tool schemas, agent errors and limits, secret redaction, mocked SDK transport, Streamlit views, thresholds, service isolation, timeline gaps/recovery, and heatmap evidence.

Tests require no OpenAI credits and make no live API requests. A GitHub Actions workflow runs the suite on pushes and pull requests.

## Project structure

| File | Responsibility |
|---|---|
| `app.py` | Streamlit layout, filters, and charts |
| `db.py` | DuckDB initialization and parameterized reads |
| `analysis.py` / `troubleshooting.py` | Deterministic findings and service-specific answers |
| `metrics.py` / `validation.py` | Shared aggregation and input validation |
| `thresholds.py` | Validated persistent service profiles |
| `timeline.py` | Hourly episodes and recovery observations |
| `degradation_heatmap.py` | All-service Overview heatmap |
| `investigation_ui.py` | Readable evidence reports and exports |
| `agent_tools.py` | Validated read-only tool interfaces |
| `ai_agent.py` / `ai_ui.py` | Optional OpenAI agent and chat |
| `test_*.py` | Automated regression tests |
| `docs/PerfAgent_Project_Documentation.docx` | Course write-up: overview, dataset, prompts, iterations, and learnings |

## Development observations and limitations

The project evolved through foundation, validated tools, optional AI integration, and evidence-focused UX iterations. A local Ollama/Qwen3 experiment timed out and slowed the 8 GB machine; it was stopped and uninstalled and is not part of this submission.

The current dataset is synthetic and hourly. Deterministic question matching uses sidebar filters; it does not extract dates or services from free text. The application does not confirm causes, connect to live monitoring, or perform production operations. Live Monitoring Integration was requested but remains unimplemented pending a provider and endpoint. Future extensions include selectable healthy baselines, slowest-hours ranking, CSV upload, and data-quality checks.

## References

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI API error guidance](https://developers.openai.com/api/docs/guides/error-codes)
