# Agent Job Tracker

An offline-safe notebook and CLI that reads job-application email threads,
classifies their status, flags applications needing a follow-up after 10
business days, and prints a grounded follow-up **draft**. It never sends mail.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
python -m pip install -r requirements.txt
python -m pip install -e .

copy .env.example .env          # optional; leave credentials unset for offline mode
python -m agent_job_tracker
jupyter notebook job_tracker.ipynb
```

The CLI and `job_tracker.ipynb` use six local sample threads when IMAP
credentials are not configured. With no `GEMINI_API_KEY`, status inference and
drafting use deterministic local rules, so this flow requires no network or
credentials.

## CLI and notebook flows

```bash
python -m agent_job_tracker
python -m agent_job_tracker.monitor
```

The one-shot CLI uses offline data when both `IMAP_USERNAME` and
`IMAP_PASSWORD` are absent. Supplying only one of them is an error; it never
silently substitutes sample data for a partially configured live run.

Live IMAP reads use TLS and select the configured folder read-only. The local
job-thread classifier runs before either Gemini call, so non-job mail is not
sent to the model. Gemini failures and quota errors fall back to local status
and draft rules. There is no SMTP client or send path.

## Monitoring

Set `MONITORING_ENABLED=true` before running the monitor. Each iteration
appends one JSON object to `MONITORING_LOG_FILE` and prints follow-up alerts to
stdout. The monitor uses the same offline sample fallback when no IMAP
credentials are configured, and records `"mode": "offline"` in that case.
It does not send mail or require a notifier.

## Environment reference

| Key | Purpose | Default |
| --- | --- | --- |
| `IMAP_HOST` | IMAP server | `imap.gmail.com` |
| `IMAP_PORT` | IMAP TLS port | `993` |
| `IMAP_USERNAME` | Live mailbox username | unset |
| `IMAP_PASSWORD` | Live mailbox/app password | unset |
| `IMAP_FOLDER` | Mailbox to read | `INBOX` |
| `IMAP_DAYS_BACK` | Search window | `60` |
| `GEMINI_API_KEY` | Optional status/draft model access | unset |
| `GEMINI_MODEL` | Gemini model; blank auto-discovers | `gemini-1.5-flash` |
| `MONITORING_ENABLED` | Enable scheduled monitor | `false` |
| `MONITORING_INTERVAL_MINUTES` | Monitor interval | `60` |
| `MONITORING_LOG_FILE` | JSONL run log | `./monitoring/runs.jsonl` |
| `MONITORING_ALERT_DAYS` | Follow-up threshold | `10` |

## Project layout

```text
job-tracker/
├── .env.example
├── requirements.txt
├── pyproject.toml
├── README.md
├── job_tracker.ipynb
├── src/agent_job_tracker/
│   ├── __main__.py          # python -m agent_job_tracker
│   ├── config.py
│   ├── business_days.py
│   ├── email_fetcher.py     # TLS, read-only IMAP, MIME parsing, threading
│   ├── thread_classifier.py # local privacy gate
│   ├── status_inference.py
│   ├── follow_up_drafter.py
│   ├── pipeline.py
│   ├── monitor.py
│   └── sample_data.py
└── tests/
```

`Job_Tracker_Complete.ipynb` is the original exploratory notebook kept for
reference; `job_tracker.ipynb` is the documented package-backed entry point.

## Validation

```bash
python -m unittest discover -s tests -v
```

The tests cover all offline statuses, privacy filtering before inference,
thread deduplication, read-only live IMAP selection using a fake server,
monitor JSONL output, configuration boundaries, and business-day math.
