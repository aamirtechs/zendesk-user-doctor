"""Tests for zendesk_user_doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import zendesk_user_doctor as doctor

AS_OF = datetime(2026, 11, 18, tzinfo=timezone.utc)

HEADER = ("user_id,name,email,role,email_verified,suspended,"
          "created_at,last_login,open_tickets,total_tickets,"
          "last_ticket_date\n")


def write_csv(body, directory=None):
    """Write body to a temp CSV file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False,
        dir=directory, encoding="utf-8")
    handle.write(body)
    handle.close()
    return handle.name


def row(user_id="U-1", name="Test User", email="test@example.com",
        role="end-user", verified="yes", suspended="no",
        created="2024-01-10", login="2026-11-15", open_tickets="0",
        total_tickets="5", last_ticket="2026-11-10"):
    """Build one CSV data row."""
    return ",".join((user_id, name, email, role, verified,
                     suspended, created, login, open_tickets,
                     total_tickets, last_ticket)) + "\n"


def run_cli(argv):
    """Run main with argv and capture stdout, return (code, text)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = doctor.main(argv)
    return code, buffer.getvalue()


def parse_and_audit(body, **kwargs):
    """Parse body and audit it, return (users, findings)."""
    path = write_csv(HEADER + body)
    try:
        users, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(users, AS_OF, **kwargs))
        return users, findings
    finally:
        os.unlink(path)


def rules(findings):
    """Return the sorted rule names of a finding list."""
    return sorted(item.rule for item in findings)


def findings_for(findings, user_id):
    """Return the findings for one user id."""
    return [item for item in findings
            if item.user == user_id]


class TestParsing(unittest.TestCase):
    """Timestamp, count, yes/no, email, and role parsing."""

    def test_parse_timestamp_iso(self):
        parsed = doctor.parse_timestamp("2026-11-17 10:00")
        self.assertEqual(parsed,
                         datetime(2026, 11, 17, 10, 0,
                                  tzinfo=timezone.utc))

    def test_parse_timestamp_zulu(self):
        parsed = doctor.parse_timestamp("2026-11-17T10:00:00Z")
        self.assertEqual(parsed,
                         datetime(2026, 11, 17, 10, 0,
                                  tzinfo=timezone.utc))

    def test_parse_timestamp_date_only(self):
        parsed = doctor.parse_timestamp("2026-11-17")
        self.assertEqual(parsed,
                         datetime(2026, 11, 17,
                                  tzinfo=timezone.utc))

    def test_parse_timestamp_day_month_year(self):
        parsed = doctor.parse_timestamp("17/11/2026")
        self.assertEqual(parsed,
                         datetime(2026, 11, 17,
                                  tzinfo=timezone.utc))

    def test_parse_timestamp_invalid(self):
        self.assertIsNone(doctor.parse_timestamp("not-a-date"))

    def test_parse_timestamp_empty(self):
        self.assertIsNone(doctor.parse_timestamp(""))
        self.assertIsNone(doctor.parse_timestamp(None))

    def test_parse_count_plain(self):
        self.assertEqual(doctor.parse_count("12"), 12)

    def test_parse_count_with_separator(self):
        self.assertEqual(doctor.parse_count("1,200"), 1200)

    def test_parse_count_invalid(self):
        self.assertIsNone(doctor.parse_count("abc"))
        self.assertIsNone(doctor.parse_count("-3"))
        self.assertIsNone(doctor.parse_count("1.5"))
        self.assertIsNone(doctor.parse_count(""))

    def test_parse_yes_no(self):
        self.assertTrue(doctor.parse_yes_no("yes"))
        self.assertTrue(doctor.parse_yes_no("verified"))
        self.assertTrue(doctor.parse_yes_no("TRUE"))
        self.assertFalse(doctor.parse_yes_no("no"))
        self.assertFalse(doctor.parse_yes_no("unverified"))
        self.assertIsNone(doctor.parse_yes_no("maybe"))
        self.assertIsNone(doctor.parse_yes_no(""))

    def test_normalize_email_case_insensitive(self):
        self.assertEqual(
            doctor.normalize_email("Alice@Example.com"),
            "alice@example.com")

    def test_normalize_role_variants(self):
        self.assertEqual(doctor.normalize_role("end user"),
                         "end-user")
        self.assertEqual(doctor.normalize_role("end_user"),
                         "end-user")
        self.assertEqual(doctor.normalize_role("customer"),
                         "end-user")
        self.assertEqual(doctor.normalize_role("Agent"), "agent")
        self.assertEqual(doctor.normalize_role("ADMIN"), "admin")
        self.assertEqual(doctor.normalize_role("superuser"), "")


class TestHeaderAndFileErrors(unittest.TestCase):
    """Header aliases, BOM handling, and file errors."""

    def test_missing_id_column(self):
        path = write_csv("name,email\nA,a@example.com\n")
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_missing_email_column(self):
        path = write_csv("user_id,name\nU-1,A\n")
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        path = write_csv("")
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            doctor.parse_csv("/nonexistent/users.csv", AS_OF)

    def test_bom_header(self):
        body = ("\ufeff" + HEADER
                + row(user_id="U-1", email="a@example.com"))
        path = write_csv(body)
        try:
            users, findings = doctor.parse_csv(path, AS_OF)
            self.assertEqual(len(users), 1)
            self.assertEqual(findings, [])
        finally:
            os.unlink(path)

    def test_header_aliases(self):
        header = ("id,full_name,email_address,user_role,is_verified,"
                  "is_suspended,created,last_sign_in,"
                  "open_ticket_count,ticket_count,"
                  "last_request_date\n")
        path = write_csv(header + row())
        try:
            users, findings = doctor.parse_csv(path, AS_OF)
            self.assertEqual(len(users), 1)
            self.assertEqual(findings, [])
        finally:
            os.unlink(path)

    def test_extra_columns_ignored(self):
        header = HEADER.rstrip("\n") + ",extra_note\n"
        path = write_csv(header + row().rstrip("\n") + ",hello\n")
        try:
            users, findings = doctor.parse_csv(path, AS_OF)
            self.assertEqual(len(users), 1)
            self.assertEqual(findings, [])
        finally:
            os.unlink(path)

    def test_blank_lines_skipped(self):
        path = write_csv(HEADER + "\n" + row() + "\n")
        try:
            users, findings = doctor.parse_csv(path, AS_OF)
            self.assertEqual(len(users), 1)
        finally:
            os.unlink(path)


class TestDataQuality(unittest.TestCase):
    """Malformed rows, duplicates, missing and invalid values."""

    def test_malformed_row_skipped(self):
        body = row() + row(user_id="U-2",
                           email="b@example.com") + ",extra\n"
        users, findings = parse_and_audit(body)
        self.assertEqual(len(users), 2)
        self.assertIn("malformed-row", rules(findings))

    def test_duplicate_user_id(self):
        body = row(user_id="U-1") + row(
            user_id="U-1", email="other@example.com")
        users, findings = parse_and_audit(body)
        self.assertIn("duplicate-user-id", rules(findings))

    def test_duplicate_email_case_insensitive(self):
        body = row(user_id="U-1", email="a@example.com") + row(
            user_id="U-2", email="A@EXAMPLE.COM")
        users, findings = parse_and_audit(body)
        self.assertIn("duplicate-email", rules(findings))

    def test_duplicate_email_first_occurrence_clean(self):
        body = row(user_id="U-1", email="a@example.com") + row(
            user_id="U-2", email="A@EXAMPLE.COM")
        users, findings = parse_and_audit(body)
        self.assertEqual(findings_for(findings, "U-1"), [])

    def test_missing_user_id(self):
        body = row(user_id="")
        users, findings = parse_and_audit(body)
        self.assertIn("missing-user-id", rules(findings))
        self.assertEqual(len(users), 1)

    def test_missing_email(self):
        body = row(email="")
        users, findings = parse_and_audit(body)
        self.assertIn("missing-email", rules(findings))

    def test_invalid_email(self):
        body = row(email="not-an-email")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-email", rules(findings))

    def test_invalid_email_no_dot(self):
        body = row(email="user@example")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-email", rules(findings))

    def test_invalid_role(self):
        body = row(role="superuser")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-role", rules(findings))

    def test_invalid_date_created(self):
        body = row(created="not-a-date")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-date", rules(findings))

    def test_invalid_date_last_login(self):
        body = row(login="yesterday-ish")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-date", rules(findings))

    def test_future_created_date(self):
        body = row(created="2026-12-05")
        users, findings = parse_and_audit(body)
        self.assertIn("future-timestamp", rules(findings))

    def test_future_last_login(self):
        body = row(login="2026-12-05")
        users, findings = parse_and_audit(body)
        self.assertIn("future-timestamp", rules(findings))

    def test_invalid_ticket_count(self):
        body = row(open_tickets="abc")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-ticket-count", rules(findings))

    def test_negative_ticket_count(self):
        body = row(open_tickets="-1")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-ticket-count", rules(findings))

    def test_open_exceeds_total(self):
        body = row(open_tickets="4", total_tickets="2")
        users, findings = parse_and_audit(body)
        self.assertIn("open-exceeds-total", rules(findings))

    def test_open_equal_total_ok(self):
        body = row(open_tickets="2", total_tickets="2")
        users, findings = parse_and_audit(body)
        self.assertNotIn("open-exceeds-total", rules(findings))

    def test_bad_value_row_still_audited(self):
        body = row(created="not-a-date", verified="no",
                   open_tickets="2")
        users, findings = parse_and_audit(body)
        self.assertIn("invalid-date", rules(findings))
        self.assertIn("unverified-email-open-tickets",
                      rules(findings))


class TestAuditRules(unittest.TestCase):
    """Unverified, suspended, and no-ticket rules."""

    def test_unverified_with_open_tickets_error(self):
        body = row(verified="no", open_tickets="2")
        users, findings = parse_and_audit(body)
        found = findings_for(findings, "U-1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rule,
                         "unverified-email-open-tickets")
        self.assertEqual(found[0].severity, "error")

    def test_unverified_no_open_tickets_warning(self):
        body = row(verified="no", open_tickets="0")
        users, findings = parse_and_audit(body)
        found = findings_for(findings, "U-1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rule, "unverified-email")
        self.assertEqual(found[0].severity, "warning")

    def test_unverified_error_flag_promotes(self):
        body = row(verified="no", open_tickets="0")
        users, findings = parse_and_audit(body,
                                          unverified_error=True)
        found = findings_for(findings, "U-1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rule, "unverified-email")
        self.assertEqual(found[0].severity, "error")

    def test_verified_with_open_tickets_clean(self):
        body = row(verified="yes", open_tickets="3")
        users, findings = parse_and_audit(body)
        self.assertEqual(findings, [])

    def test_suspended_with_open_tickets_error(self):
        body = row(suspended="yes", open_tickets="3")
        users, findings = parse_and_audit(body)
        found = findings_for(findings, "U-1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rule,
                         "suspended-with-open-tickets")
        self.assertEqual(found[0].severity, "error")

    def test_suspended_no_open_tickets_warning(self):
        body = row(suspended="yes", open_tickets="0")
        users, findings = parse_and_audit(body)
        found = findings_for(findings, "U-1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rule, "suspended-user")
        self.assertEqual(found[0].severity, "warning")

    def test_suspended_agent_with_open_tickets(self):
        body = row(role="agent", suspended="yes", open_tickets="2")
        users, findings = parse_and_audit(body)
        self.assertIn("suspended-with-open-tickets",
                      rules(findings))

    def test_no_tickets_old_account_warning(self):
        body = row(created="2023-03-01", open_tickets="0",
                   total_tickets="0")
        users, findings = parse_and_audit(body)
        self.assertIn("no-tickets-user", rules(findings))

    def test_no_tickets_new_account_clean(self):
        body = row(created="2026-11-15", open_tickets="0",
                   total_tickets="0")
        users, findings = parse_and_audit(body)
        self.assertNotIn("no-tickets-user", rules(findings))

    def test_no_tickets_stale_days_boundary(self):
        body = row(created="2026-08-19", open_tickets="0",
                   total_tickets="0")
        users, findings = parse_and_audit(body, stale_days=90)
        self.assertIn("no-tickets-user", rules(findings))
        users, findings = parse_and_audit(body, stale_days=2000)
        self.assertNotIn("no-tickets-user", rules(findings))

    def test_no_tickets_exact_boundary_not_flagged(self):
        body = row(created="2026-08-20", open_tickets="0",
                   total_tickets="0")
        users, findings = parse_and_audit(body, stale_days=90)
        self.assertNotIn("no-tickets-user", rules(findings))

    def test_tickets_present_no_warning(self):
        body = row(created="2023-03-01", open_tickets="0",
                   total_tickets="3")
        users, findings = parse_and_audit(body)
        self.assertNotIn("no-tickets-user", rules(findings))

    def test_missing_verified_column_skips_check(self):
        header = ("user_id,name,email,role,suspended,created_at,"
                  "last_login,open_tickets,total_tickets,"
                  "last_ticket_date\n")
        body = (header + ",".join(
            ("U-1", "Test User", "test@example.com", "end-user",
             "no", "2024-01-10", "2026-11-15", "2", "5",
             "2026-11-10")) + "\n")
        path = write_csv(body)
        try:
            users, findings = doctor.parse_csv(path, AS_OF)
            findings.extend(doctor.audit(users, AS_OF))
            self.assertEqual(findings, [])
        finally:
            os.unlink(path)


class TestSummaryAndOutput(unittest.TestCase):
    """Summary counts, per-role table, text and JSON output."""

    def test_summary_counts(self):
        body = (row(user_id="U-1", verified="no",
                    open_tickets="2")
                + row(user_id="U-2", email="b@example.com",
                      suspended="yes", open_tickets="1")
                + row(user_id="U-3", email="c@example.com"))
        users, findings = parse_and_audit(body)
        summary = doctor.summarize(users, findings, AS_OF)
        self.assertEqual(summary["users"], 3)
        self.assertEqual(summary["errors"], 2)
        self.assertEqual(summary["warnings"], 0)
        self.assertEqual(summary["clean_users"], 1)
        self.assertEqual(summary["unverified_emails"], 1)
        self.assertEqual(summary["suspended_with_open_tickets"], 1)
        self.assertEqual(summary["suspended_users"], 1)
        self.assertEqual(summary["open_tickets"], 3)
        self.assertEqual(summary["verified_rate"], 66.7)

    def test_per_role_table(self):
        body = (row(user_id="U-1", role="agent")
                + row(user_id="U-2", email="b@example.com",
                      role="admin", verified="no",
                      open_tickets="1"))
        users, findings = parse_and_audit(body)
        summary = doctor.summarize(users, findings, AS_OF)
        per_role = {item["role"]: item
                    for item in summary["per_role"]}
        self.assertEqual(per_role["agent"]["users"], 1)
        self.assertEqual(per_role["agent"]["errors"], 0)
        self.assertEqual(per_role["admin"]["users"], 1)
        self.assertEqual(per_role["admin"]["errors"], 1)

    def test_duplicate_id_blocks_both_rows(self):
        body = row(user_id="U-1") + row(
            user_id="U-1", email="other@example.com")
        users, findings = parse_and_audit(body)
        summary = doctor.summarize(users, findings, AS_OF)
        self.assertEqual(summary["clean_users"], 0)

    def test_text_output_clean(self):
        path = write_csv(HEADER + row())
        try:
            code, text = run_cli([path, "--as-of", "2026-11-18"])
            self.assertEqual(code, 0)
            self.assertIn("All users clean.", text)
            self.assertIn("Users: 1, findings: 0", text)
        finally:
            os.unlink(path)

    def test_json_output(self):
        path = write_csv(HEADER + row(verified="no",
                                      open_tickets="1"))
        try:
            code, text = run_cli([path, "--as-of", "2026-11-18",
                                  "--json"])
            self.assertEqual(code, 0)
            report = json.loads(text)
            self.assertEqual(report["users"], 1)
            self.assertEqual(report["errors"], 1)
            self.assertEqual(report["findings"][0]["rule"],
                             "unverified-email-open-tickets")
        finally:
            os.unlink(path)

    def test_out_file(self):
        path = write_csv(HEADER + row())
        out_path = path + ".out"
        try:
            code, text = run_cli([path, "--as-of", "2026-11-18",
                                  "--out", out_path])
            self.assertEqual(code, 0)
            self.assertEqual(text, "")
            with open(out_path, encoding="utf-8") as handle:
                self.assertIn("All users clean.", handle.read())
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)


class TestCliExitCodes(unittest.TestCase):
    """--check, --strict, and bad argument handling."""

    def test_check_exit_1_on_error(self):
        path = write_csv(HEADER + row(verified="no",
                                      open_tickets="1"))
        try:
            code, _ = run_cli([path, "--as-of", "2026-11-18",
                               "--check"])
            self.assertEqual(code, 1)
        finally:
            os.unlink(path)

    def test_check_exit_0_on_warnings(self):
        path = write_csv(HEADER + row(verified="no",
                                      open_tickets="0"))
        try:
            code, _ = run_cli([path, "--as-of", "2026-11-18",
                               "--check"])
            self.assertEqual(code, 0)
        finally:
            os.unlink(path)

    def test_strict_exit_1_on_warnings(self):
        path = write_csv(HEADER + row(verified="no",
                                      open_tickets="0"))
        try:
            code, _ = run_cli([path, "--as-of", "2026-11-18",
                               "--check", "--strict"])
            self.assertEqual(code, 1)
        finally:
            os.unlink(path)

    def test_check_exit_0_clean(self):
        path = write_csv(HEADER + row())
        try:
            code, _ = run_cli([path, "--as-of", "2026-11-18",
                               "--check"])
            self.assertEqual(code, 0)
        finally:
            os.unlink(path)

    def test_negative_stale_days(self):
        path = write_csv(HEADER + row())
        try:
            code, _ = run_cli([path, "--stale-days", "-1"])
            self.assertEqual(code, 2)
        finally:
            os.unlink(path)

    def test_bad_as_of(self):
        path = write_csv(HEADER + row())
        try:
            code, _ = run_cli([path, "--as-of", "not-a-date"])
            self.assertEqual(code, 2)
        finally:
            os.unlink(path)

    def test_missing_file_exit_2(self):
        code, _ = run_cli(["/nonexistent/users.csv"])
        self.assertEqual(code, 2)

    def test_stale_days_flag_changes_output(self):
        body = row(created="2023-03-01", open_tickets="0",
                   total_tickets="0")
        path = write_csv(HEADER + body)
        try:
            code, text = run_cli([path, "--as-of", "2026-11-18",
                                  "--stale-days", "2000"])
            self.assertEqual(code, 0)
            self.assertIn("findings: 0", text)
        finally:
            os.unlink(path)

    def test_unverified_error_flag_changes_output(self):
        path = write_csv(HEADER + row(verified="no",
                                      open_tickets="0"))
        try:
            code, text = run_cli([path, "--as-of", "2026-11-18",
                                  "--check", "--unverified-error"])
            self.assertEqual(code, 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
