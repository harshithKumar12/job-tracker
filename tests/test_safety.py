"""Regression tests for observed offline and live-boundary failures."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage as MimeMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_job_tracker import monitor
from agent_job_tracker.config import Config
from agent_job_tracker.email_fetcher import _parse_message, consolidate_threads, fetch_threads
from agent_job_tracker.models import EmailMessage
from agent_job_tracker.pipeline import process_threads
from agent_job_tracker.status_inference import infer_status

NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)


def message(body="Received your application.", **kwargs):
    values = dict(
        message_id="<application@example.test>",
        from_="careers@acme.test",
        to="me@example.test",
        subject="Acme - Engineer - Application",
        date=NOW - timedelta(days=20),
        body=body,
    )
    values.update(kwargs)
    return EmailMessage(**values)


class MailSafetyTests(unittest.TestCase):
    def test_multipart_body_does_not_crash_or_include_attached_mail(self):
        mail = MimeMessage()
        mail["Date"] = "Fri, 28 Aug 2026 12:00:00 +0000"
        mail.set_content("Received your application.")
        mail.add_alternative("<p>Received your application.</p>", subtype="html")
        attachment = MimeMessage()
        attachment.set_content("PRIVATE ATTACHMENT")
        mail.add_attachment(attachment)
        parsed = _parse_message(mail)
        self.assertEqual(parsed.body.strip(), "Received your application.")
        self.assertNotIn("PRIVATE", parsed.body)

    def test_html_only_body_is_readable_and_excludes_scripts(self):
        mail = MimeMessage()
        mail.set_content("<script>PRIVATE CODE</script><p>Application &amp; interview</p>", subtype="html")
        body = _parse_message(mail).body
        self.assertIn("Application & interview", body)
        self.assertNotIn("<p>", body)
        self.assertNotIn("PRIVATE", body)

    def test_missing_root_references_link_siblings(self):
        first = message(message_id="<reply-one>", references="<absent-root>")
        second = message(message_id="<reply-two>", references="<absent-root> <reply-one>")
        # The common root can be outside IMAP_DAYS_BACK; order must not matter.
        third = message(message_id="<reply-three>", references="<absent-root>", subject="Interview plan")
        self.assertEqual(len(consolidate_threads([third, second, first])), 1)

    def test_idless_subject_fallback_does_not_mix_companies_or_blank_subjects(self):
        first = message(message_id="")
        reply = message(message_id="", subject="Re: Re: Acme - Engineer - Application")
        other_company = message(message_id="", from_="careers@other.test")
        blank_one = message(message_id="", subject="")
        blank_two = message(message_id="", subject="")
        threads = consolidate_threads([first, reply, other_company, blank_one, blank_two])
        self.assertEqual(sorted(len(thread.messages) for thread in threads), [1, 2, 2])
        self.assertEqual(len({thread.thread_id for thread in threads}), 3)

    def test_context_retains_newest_message_with_hard_size_limit(self):
        old = message("Old application " + "x" * 20_000)
        latest = message("We regret to inform you that your application was rejected.",
                         message_id="<new>", references=old.message_id, date=NOW)
        thread = consolidate_threads([old, latest])[0]
        corpus = thread.as_text_corpus(max_chars=500)
        self.assertLessEqual(len(corpus), 500)
        self.assertIn("application was rejected", corpus)

    def test_search_and_fetch_failures_do_not_masquerade_as_empty_inboxes(self):
        cfg = Config(imap_username="me@example.test", imap_password="fake")
        for stage in ("select", "search", "fetch"):
            with self.subTest(stage=stage):
                imap = MagicMock()
                imap.login.return_value = ("OK", [])
                imap.select.return_value = ("NO", []) if stage == "select" else ("OK", [])

                def uid(command, *args):
                    if command == "search":
                        return ("NO", []) if stage == "search" else ("OK", [b"123"])
                    return "NO", []

                imap.uid.side_effect = uid
                # Exercise the original sequence-number code too, until repaired.
                imap.search.return_value = ("NO", []) if stage == "search" else ("OK", [b"123"])
                imap.fetch.return_value = ("NO", [])
                with patch("agent_job_tracker.email_fetcher.imaplib.IMAP4_SSL", return_value=imap):
                    with self.assertRaises(RuntimeError):
                        fetch_threads(cfg)
                imap.logout.assert_called_once()


class InferenceSafetyTests(unittest.TestCase):
    def test_generic_offer_or_application_words_do_not_pass_privacy_gate(self):
        private = [
            message("Special offer! Buy now.", subject="Your newsletter"),
            message("Unfortunately your reservation was cancelled.", subject="Travel update"),
            message("Your loan application was approved.", subject="Loan application"),
            message("Interview with a famous actor.", subject="Weekly digest"),
        ]
        with patch("agent_job_tracker.pipeline.infer_status") as infer:
            self.assertEqual(process_threads(consolidate_threads([
                replace(mail, message_id=f"<private-{i}>") for i, mail in enumerate(private)
            ]), Config(gemini_api_key="fake"), now=NOW), [])
        infer.assert_not_called()

    def test_latest_decisive_message_overrides_stale_offer_and_quotes(self):
        old = message("We are pleased to extend an offer.")
        latest = message(
            "We have decided to move forward with another candidate.\n"
            "On Monday the recruiter wrote:\n> We are pleased to extend an offer.",
            message_id="<decision>", references=old.message_id, date=NOW,
        )
        status = infer_status(consolidate_threads([old, latest])[0], Config())
        self.assertEqual(status.status, "rejected")

    def test_uncertain_status_is_manual_review_without_follow_up_draft(self):
        thread = consolidate_threads([message("An update about your application for the Engineer role.")])[0]
        application = process_threads([thread], Config(), now=NOW)[0]
        self.assertEqual(application.status, "unclear")
        self.assertFalse(application.needs_follow_up)
        self.assertIsNone(application.draft_body)

    def test_terminal_status_does_not_trigger_alerts_even_when_old(self):
        for body in ("We are pleased to extend an offer.", "Your application was rejected."):
            with self.subTest(body=body):
                thread = consolidate_threads([message(body)])[0]
                application = process_threads([thread], Config(), now=NOW)[0]
                self.assertFalse(application.needs_follow_up)
                self.assertIsNone(application.draft_body)

    def test_follow_up_ten_day_boundary_and_tones(self):
        # Friday-to-Friday intervals: 9, 10, 14, 15, 30, 31 business days.
        for elapsed, days_ago, expected_tone in (
            (9, 11, None), (10, 14, "warm"), (14, 18, "warm"),
            (15, 21, "firm"), (30, 42, "firm"), (31, 43, "closing"),
        ):
            with self.subTest(elapsed=elapsed):
                thread = consolidate_threads([message(date=NOW - timedelta(days=days_ago))])[0]
                application = process_threads([thread], Config(), now=NOW)[0]
                self.assertEqual(application.business_days_elapsed, elapsed)
                self.assertEqual(application.draft_tone, expected_tone)


class MonitorSafetyTests(unittest.TestCase):
    def test_failed_run_is_logged_without_secrets_then_can_recover(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "runs.jsonl"
            cfg = Config(imap_username="me@example.test", imap_password="fake",
                         monitoring_log_file=str(path))
            failing = MagicMock(side_effect=RuntimeError("password=PRIVATE"))
            with self.assertRaises(RuntimeError):
                monitor.run_once(cfg, now=NOW, fetcher=failing)
            monitor.run_once(cfg, now=NOW, fetcher=lambda _: [])
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([record["outcome"] for record in records], ["error", "ok"])
            self.assertNotIn("PRIVATE", path.read_text(encoding="utf-8"))

    def test_disabled_monitor_does_no_work(self):
        with patch.object(Config, "from_env", return_value=Config()), \
             patch.object(monitor, "run_once") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(monitor.main(), 0)
        run.assert_not_called()

    def test_enabled_monitor_recovers_from_failure_and_stops_on_interrupt(self):
        cfg = Config(monitoring_enabled=True, monitoring_interval_minutes=2)
        with patch.object(Config, "from_env", return_value=cfg), \
             patch.object(monitor, "run_once", side_effect=[RuntimeError("PRIVATE"), []]) as run, \
             patch.object(monitor.time, "sleep", side_effect=[None, KeyboardInterrupt]) as sleep, \
             contextlib.redirect_stdout(io.StringIO()) as output, \
             contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(monitor.main(), 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(sleep.call_args.args, (120,))
        self.assertNotIn("PRIVATE", output.getvalue() + error.getvalue())


if __name__ == "__main__":
    unittest.main()
