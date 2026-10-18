from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_job_tracker.business_days import between
from agent_job_tracker.config import Config
from agent_job_tracker.email_fetcher import consolidate_threads, fetch_threads
from agent_job_tracker.models import EmailMessage, StatusInference
from agent_job_tracker.monitor import run_once as monitor_run_once
from agent_job_tracker.pipeline import process_threads
from agent_job_tracker.sample_data import load_sample_data


UTC = timezone.utc
NOW = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)


class TrackerFlowTests(unittest.TestCase):
    def test_offline_fixture_covers_all_statuses_and_draft_boundaries(self) -> None:
        cfg = Config(monitoring_alert_days=10)

        applications = process_threads(load_sample_data(NOW), cfg, now=NOW)

        self.assertEqual(
            {application.status for application in applications},
            {"applied", "interview_scheduled", "rejected", "offer", "no_response", "unclear"},
        )
        terminal = {application.status: application for application in applications if application.status in {"offer", "rejected"}}
        self.assertTrue(all(not application.needs_follow_up for application in terminal.values()))
        self.assertTrue(all(application.draft_subject for application in applications if application.needs_follow_up))

    def test_non_job_thread_is_filtered_before_inference(self) -> None:
        job = EmailMessage(
            "job",
            "recruiter@example.com",
            "me@example.com",
            "Interview for backend role",
            NOW - timedelta(days=20),
            "Can we schedule an interview?",
        )
        receipt = EmailMessage(
            "receipt",
            "store@example.com",
            "me@example.com",
            "Order confirmation",
            NOW - timedelta(days=20),
            "Your payment receipt is attached.",
        )
        cfg = Config()
        expected = StatusInference("interview_scheduled", 0.9, ["test"])

        with patch("agent_job_tracker.pipeline.infer_status", return_value=expected) as infer:
            applications = process_threads(consolidate_threads([job, receipt]), cfg, now=NOW)

        self.assertEqual(len(applications), 1)
        self.assertEqual(infer.call_count, 1)
        self.assertEqual(applications[0].status, "interview_scheduled")

    def test_message_id_deduplication_and_reply_threading(self) -> None:
        root = EmailMessage(
            "<root@example.com>",
            "me@example.com",
            "recruiter@example.com",
            "Application - Backend role",
            NOW - timedelta(days=3),
            "Thanks for applying.",
        )
        duplicate = EmailMessage(
            "<root@example.com>",
            "me@example.com",
            "recruiter@example.com",
            "Application - Backend role",
            NOW - timedelta(days=3),
            "Thanks for applying.",
        )
        reply = EmailMessage(
            "<reply@example.com>",
            "recruiter@example.com",
            "me@example.com",
            "Re: Application - Backend role",
            NOW - timedelta(days=1),
            "We would like to schedule an interview.",
            in_reply_to="<root@example.com>",
        )

        threads = consolidate_threads([root, duplicate, reply])

        self.assertEqual(len(threads), 1)
        self.assertEqual(len(threads[0].messages), 2)
        self.assertEqual(threads[0].last_contact, reply.date)

    def test_distinct_message_id_roots_do_not_merge_on_subject_alone(self) -> None:
        messages = [
            EmailMessage("<one@example.com>", "a@example.com", "me@example.com", "Application", NOW, "one"),
            EmailMessage("<two@example.com>", "b@example.com", "me@example.com", "Application", NOW, "two"),
        ]

        threads = consolidate_threads(messages)

        self.assertEqual(len(threads), 2)

    def test_live_fetch_selects_mailbox_read_only(self) -> None:
        raw_message = (
            b"Date: Fri, 28 Aug 2026 12:00:00 +0000\r\n"
            b"Message-ID: <live@example.com>\r\n"
            b"From: recruiter@example.com\r\n"
            b"To: me@example.com\r\n"
            b"Subject: Interview for backend role\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Can we schedule an interview?\r\n"
        )

        class FakeImap:
            def __init__(self, *_args, **_kwargs):
                self.select_args = None

            def login(self, *_args):
                return "OK", [b"logged in"]

            def select(self, *args, **kwargs):
                self.select_args = (args, kwargs)
                return "OK", [b"1"]

            def search(self, *_args):
                return "OK", [b"1"]

            def fetch(self, *_args):
                return "OK", [(b"1 (RFC822)", raw_message)]

            def logout(self):
                return "OK", [b"logged out"]

        cfg = Config(imap_username="user@example.com", imap_password="secret")
        fake_imap = FakeImap()
        with patch("agent_job_tracker.email_fetcher.imaplib.IMAP4_SSL", return_value=fake_imap):
            threads = fetch_threads(cfg)

        self.assertEqual(len(threads), 1)
        self.assertEqual(fake_imap.select_args, (("INBOX",), {"readonly": True}))

    def test_monitor_appends_jsonl_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            log_file = str(Path(directory) / "runs.jsonl")
            cfg = Config(monitoring_log_file=log_file, monitoring_alert_days=10)

            applications = monitor_run_once(cfg, now=NOW)

            self.assertEqual(len(applications), 6)
            record = json.loads(Path(log_file).read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["mode"], "offline")
            self.assertEqual(record["application_count"], 6)
            self.assertEqual(record["follow_up_count"], 3)

    def test_config_reads_documented_values_and_ignores_example_placeholders(self) -> None:
        cfg = Config.from_env(
            {
                "IMAP_HOST": "mail.example.test",
                "IMAP_PORT": "993",
                "IMAP_USERNAME": "you@example.test",
                "IMAP_PASSWORD": "your_app_password",
                "IMAP_DAYS_BACK": "14",
                "GEMINI_API_KEY": "your_gemini_api_key_here",
                "GEMINI_MODEL": "gemini-test",
                "MONITORING_ENABLED": "true",
                "MONITORING_INTERVAL_MINUTES": "15",
                "MONITORING_LOG_FILE": "./tmp/runs.jsonl",
                "MONITORING_ALERT_DAYS": "12",
            }
        )

        self.assertEqual(cfg.imap_host, "mail.example.test")
        self.assertEqual(cfg.imap_days_back, 14)
        self.assertIsNone(cfg.imap_password)
        self.assertIsNone(cfg.gemini_api_key)
        self.assertTrue(cfg.monitoring_enabled)
        self.assertEqual(cfg.monitoring_interval_minutes, 15)
        self.assertEqual(cfg.monitoring_alert_days, 12)
        self.assertFalse(cfg.has_imap_credentials)

    def test_partial_imap_credentials_are_not_treated_as_offline(self) -> None:
        cfg = Config(imap_username="user@example.com")

        self.assertTrue(cfg.has_any_imap_credentials)
        self.assertFalse(cfg.has_imap_credentials)

    def test_business_days_handles_year_boundary_and_explicit_holidays(self) -> None:
        self.assertEqual(between("2026-12-31", "2027-01-04"), 1)
        self.assertEqual(
            between("2026-08-27", "2026-08-28", holidays={datetime(2026, 8, 28).date()}),
            0,
        )


if __name__ == "__main__":
    unittest.main()
