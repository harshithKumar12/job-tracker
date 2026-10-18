"""Scheduled, append-only monitoring with stdout alerts and no sender."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import Config
from .email_fetcher import fetch_threads
from .pipeline import print_digest, process_threads
from .sample_data import load_sample_data


def run_once(
    cfg: Config,
    *,
    now: datetime | None = None,
    fetcher: Callable[[Config], list] = fetch_threads,
) -> list:
    current = now or datetime.now(timezone.utc)
    if cfg.has_any_imap_credentials and not cfg.has_imap_credentials:
        raise RuntimeError("Set both IMAP_USERNAME and IMAP_PASSWORD for live monitoring.")
    live = cfg.has_imap_credentials
    try:
        threads = fetcher(cfg) if live else load_sample_data(current)
        applications = process_threads(threads, cfg, now=current)
    except Exception as exc:
        _append_log(
            cfg,
            {
                "timestamp": current.isoformat(),
                "mode": "live" if live else "offline",
                "outcome": "error",
                "error_type": type(exc).__name__,
            },
        )
        raise
    alerts = [
        {
            "company": application.company,
            "role": application.role,
            "business_days_elapsed": application.business_days_elapsed,
        }
        for application in applications
        if application.needs_follow_up
    ]
    record = {
        "timestamp": current.isoformat(),
        "mode": "live" if live else "offline",
        "outcome": "ok",
        "application_count": len(applications),
        "follow_up_count": len(alerts),
        "alerts": alerts,
    }
    _append_log(cfg, record)
    for alert in alerts:
        print(
            f"Follow-up alert: {alert['company'] or '?'} - {alert['role'] or '?'} "
            f"({alert['business_days_elapsed']} business days)"
        )
    return applications


def _append_log(cfg: Config, record: dict) -> None:
    log_path = Path(cfg.monitoring_log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, sort_keys=True) + "\n")


def main() -> int:
    cfg = Config.from_env()
    if not cfg.monitoring_enabled:
        print("Monitoring is disabled; set MONITORING_ENABLED=true to enable it.")
        return 0
    while True:
        try:
            print_digest(run_once(cfg))
        except Exception as exc:
            print(f"Monitoring run failed: {type(exc).__name__}")
        try:
            time.sleep(cfg.monitoring_interval_minutes * 60)
        except KeyboardInterrupt:
            print("Monitoring stopped.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
