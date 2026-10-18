"""One-shot CLI: offline by default, IMAP only when both credentials exist."""

from __future__ import annotations

from .config import Config
from .email_fetcher import fetch_threads
from .pipeline import print_digest, process_threads
from .sample_data import load_sample_data


def run_once(cfg: Config | None = None) -> int:
    config = cfg or Config.from_env()
    if config.has_any_imap_credentials and not config.has_imap_credentials:
        raise RuntimeError("Set both IMAP_USERNAME and IMAP_PASSWORD, or leave both unset for offline mode.")
    if config.has_imap_credentials:
        threads = fetch_threads(config)
        print("Using live IMAP data.")
    else:
        threads = load_sample_data()
        print("Using offline sample data (IMAP credentials not configured).")
    print_digest(process_threads(threads, config))
    return 0


def main() -> int:
    try:
        return run_once()
    except Exception as exc:
        print(f"Job tracker failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
