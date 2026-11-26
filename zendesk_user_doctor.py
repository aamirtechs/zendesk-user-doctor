"""Zendesk end-user audit CLI.

Reads a Zendesk end-user CSV export (from the Zendesk
admin center user export, or a support team's user
spreadsheet) and audits every user for the problems
that quietly break support: duplicate users (the same
email twice, or the same user id twice), unverified
email addresses, suspended users who still have open
tickets, and users who never opened a ticket at all.
It also prints a verified rate, a suspended count, and
a per-role table, so a support manager can see at a
glance which users need chasing and which accounts are
safe to clean up.

A support inbox lives or dies on reaching the right
person. A reply sent to an unverified address never
arrives, a suspended user with open tickets keeps a
queue stuck, and a user list full of duplicates means
the same person gets two different answers. Zendesk
itself will not flag any of this in the export. This
tool is that audit: it ranks the users in the export
alone, and never touches a live Zendesk API.

Each problem is a finding with a user id, a rule name,
a severity (error or warning), and a message. Errors
are duplicate users, unverified emails on users with
open tickets, suspended users with open tickets, and
data that cannot be trusted; warnings are unverified
emails with no open tickets, suspended users with no
open tickets, and old accounts that never opened a
ticket. --check exits 1 when any error is found, and
--strict also fails on warnings.

Dates are parsed defensively. A bad date or ticket
count is reported as a finding and the row is still
audited on the fields that did parse, so one bad row
never crashes the run.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 zendesk_user_doctor.py examples/users.csv
    python3 zendesk_user_doctor.py users.csv --json --check
    python3 zendesk_user_doctor.py users.csv --as-of 2026-11-18
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone

__version__ = "1.0.0"

DEFAULT_STALE_DAYS = 90

KNOWN_ROLES = {"end-user", "agent", "admin"}

YES_VALUES = {"yes", "y", "true", "1", "verified", "confirmed"}
NO_VALUES = {"no", "n", "false", "0", "unverified",
             "not verified"}

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


class Finding:
    """One audit finding for one user."""

    def __init__(self, user, rule, severity, message):
        self.user = user
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"user": self.user, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.user, self.message)


def parse_timestamp(text):
    """Parse a timestamp string into an aware datetime, or None.

    Accepts ISO 8601 with or without a timezone (a trailing Z is
    handled), plus a few common export formats. A naive timestamp
    is read as UTC. Returns None for an empty string or a value
    that matches no known format, so callers can report it
    instead of crashing.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_count(text):
    """Parse a ticket count string into an int, or None.

    Accepts plain integers with optional thousands
    separators. Returns None for an empty string, a value
    that is not an integer, or a negative number.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    cleaned = text.replace(",", "").strip()
    try:
        value = int(cleaned)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def parse_yes_no(text):
    """Parse a yes/no cell into True, False, or None.

    Returns None for an empty cell or a value that is neither
    a recognized yes nor a recognized no, so callers can fall
    back to a derived value instead of guessing.
    """
    if text is None:
        return None
    value = text.strip().lower()
    if not value:
        return None
    if value in YES_VALUES:
        return True
    if value in NO_VALUES:
        return False
    return None


def normalize_email(text):
    """Normalize an email address for comparison, or "".

    Comparison is case-insensitive and ignores surrounding
    whitespace, so "Alice@Example.com" and
    "alice@example.com" count as the same user.
    """
    if text is None:
        return ""
    return text.strip().lower()


def normalize_role(text):
    """Normalize a role to a canonical role string.

    Returns "end-user", "agent", or "admin", or an empty
    string for an unknown value. "end user" with a space
    and "end_user" with an underscore both count as
    "end-user".
    """
    if text is None:
        return ""
    role = text.strip().lower()
    role = role.replace("_", " ").replace("-", " ")
    role = " ".join(role.split())
    if role in ("end user", "enduser", "user", "customer",
                "requester"):
        return "end-user"
    if role in ("agent", "support agent"):
        return "agent"
    if role in ("admin", "administrator"):
        return "admin"
    return ""


def find_column(header, names):
    """Return the first of names present in header, or None."""
    for name in names:
        if name in header:
            return name
    return None


def parse_csv(path, as_of):
    """Parse a Zendesk end-user CSV export.

    Returns (users, findings). Each user is a dict with the
    id, name, email, role, verified and suspended flags,
    created and last login dates, open and total ticket
    counts, and last ticket date. Rows with the wrong number
    of fields are reported as malformed-row errors and
    skipped, never a crash. A UTF-8 BOM header is handled.
    Extra columns are ignored.
    """
    findings = []
    users = []
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read %s: %s" % (path, exc))
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s is empty, no header row found" % path)
        except csv.Error as exc:
            raise ValueError("%s is not a readable CSV file: %s"
                             % (path, exc))
        header = [name.strip() for name in header]
        id_column = find_column(header, ("user_id", "id", "user"))
        if id_column is None:
            raise ValueError(
                "%s has no user_id or id column (header is: %s)"
                % (path, ", ".join(header)))
        email_column = find_column(header, ("email", "email_address",
                                            "user_email"))
        if email_column is None:
            raise ValueError(
                "%s has no email column (header is: %s)"
                % (path, ", ".join(header)))
        name_column = find_column(header, ("name", "full_name",
                                           "user_name"))
        role_column = find_column(header, ("role", "user_role",
                                           "type"))
        verified_column = find_column(
            header, ("email_verified", "verified", "is_verified",
                     "verification_status"))
        suspended_column = find_column(
            header, ("suspended", "is_suspended", "suspension_status"))
        created_column = find_column(
            header, ("created_at", "created", "date_created",
                     "signup_date"))
        login_column = find_column(
            header, ("last_login", "last_sign_in", "last_login_at",
                     "last_active"))
        open_column = find_column(
            header, ("open_tickets", "open_ticket_count",
                     "open_requests"))
        total_column = find_column(
            header, ("total_tickets", "ticket_count",
                     "total_requests"))
        last_ticket_column = find_column(
            header, ("last_ticket_date", "last_ticket",
                     "last_request_date"))
        seen_ids = set()
        seen_emails = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, "
                    "so the row was skipped" % (len(row), len(header))))
                continue
            cells = dict(zip(header, (cell.strip() for cell in row)))
            user_id = cells[id_column]
            if not user_id:
                findings.append(Finding(
                    "row %d" % line_number, "missing-user-id",
                    "error",
                    "row has no user id, so the user cannot be "
                    "matched to a Zendesk record"))
                user_id = "row %d" % line_number
            if user_id in seen_ids:
                findings.append(Finding(
                    user_id, "duplicate-user-id", "error",
                    "user id appears more than once in the export"))
            else:
                seen_ids.add(user_id)
            email_raw = cells[email_column]
            email = normalize_email(email_raw)
            if not email_raw:
                findings.append(Finding(
                    user_id, "missing-email", "error",
                    "user has no email address, so Zendesk "
                    "cannot reach them at all"))
            elif not EMAIL_PATTERN.match(email):
                findings.append(Finding(
                    user_id, "invalid-email", "error",
                    "email address %r is not a valid email "
                    "address" % email_raw))
            elif email in seen_emails:
                findings.append(Finding(
                    user_id, "duplicate-email", "error",
                    "email address %s already appears in the "
                    "export, so two records claim the same user"
                    % email_raw))
            else:
                seen_emails.add(email)
            role_raw = cells[role_column] if role_column else ""
            role = normalize_role(role_raw)
            if role_column is not None and role_raw and not role:
                findings.append(Finding(
                    user_id, "invalid-role", "error",
                    "role %r is not a known Zendesk role "
                    "(end-user, agent, or admin)" % role_raw))
            created_raw = (cells[created_column]
                           if created_column else "")
            created_at = None
            if created_raw:
                created_at = parse_timestamp(created_raw)
                if created_at is None:
                    findings.append(Finding(
                        user_id, "invalid-date", "error",
                        "created date %r is not a readable date"
                        % created_raw))
                elif created_at > as_of:
                    findings.append(Finding(
                        user_id, "future-timestamp", "error",
                        "created date %s is after the as-of date "
                        "%s" % (created_at.strftime("%Y-%m-%d %H:%M"),
                                as_of.strftime("%Y-%m-%d %H:%M"))))
            login_raw = (cells[login_column]
                         if login_column else "")
            last_login = None
            if login_raw:
                last_login = parse_timestamp(login_raw)
                if last_login is None:
                    findings.append(Finding(
                        user_id, "invalid-date", "error",
                        "last login date %r is not a readable "
                        "date" % login_raw))
                elif last_login > as_of:
                    findings.append(Finding(
                        user_id, "future-timestamp", "error",
                        "last login date %s is after the as-of "
                        "date %s"
                        % (last_login.strftime("%Y-%m-%d %H:%M"),
                           as_of.strftime("%Y-%m-%d %H:%M"))))
            open_raw = (cells[open_column]
                        if open_column else "")
            open_tickets = None
            if open_column is not None:
                if not open_raw:
                    findings.append(Finding(
                        user_id, "missing-ticket-count", "error",
                        "user has no open ticket count recorded, "
                        "so the queue cannot be checked"))
                else:
                    open_tickets = parse_count(open_raw)
                    if open_tickets is None:
                        findings.append(Finding(
                            user_id, "invalid-ticket-count", "error",
                            "open ticket count %r is not a "
                            "non-negative number" % open_raw))
            total_raw = (cells[total_column]
                         if total_column else "")
            total_tickets = None
            if total_column is not None:
                if not total_raw:
                    findings.append(Finding(
                        user_id, "missing-ticket-count", "error",
                        "user has no total ticket count recorded, "
                        "so the history cannot be checked"))
                else:
                    total_tickets = parse_count(total_raw)
                    if total_tickets is None:
                        findings.append(Finding(
                            user_id, "invalid-ticket-count", "error",
                            "total ticket count %r is not a "
                            "non-negative number" % total_raw))
            if (open_tickets is not None
                    and total_tickets is not None
                    and open_tickets > total_tickets):
                findings.append(Finding(
                    user_id, "open-exceeds-total", "error",
                    "user has %d open tickets but only %d total "
                    "tickets, which cannot both be true"
                    % (open_tickets, total_tickets)))
            last_ticket_raw = (cells[last_ticket_column]
                               if last_ticket_column else "")
            last_ticket = None
            if last_ticket_raw:
                last_ticket = parse_timestamp(last_ticket_raw)
                if last_ticket is None:
                    findings.append(Finding(
                        user_id, "invalid-date", "error",
                        "last ticket date %r is not a readable "
                        "date" % last_ticket_raw))
            users.append({
                "id": user_id,
                "name": (cells[name_column]
                         if name_column else ""),
                "email": email,
                "email_raw": email_raw,
                "role": role,
                "role_raw": role_raw,
                "verified": (parse_yes_no(cells[verified_column])
                             if verified_column else None),
                "has_verified_column": verified_column is not None,
                "suspended": (parse_yes_no(cells[suspended_column])
                              if suspended_column else None),
                "has_suspended_column": suspended_column is not None,
                "created_at": created_at,
                "last_login": last_login,
                "open_tickets": open_tickets,
                "total_tickets": total_tickets,
                "last_ticket": last_ticket,
                "line": line_number})
    return users, findings


def audit(users, as_of,
          stale_days=DEFAULT_STALE_DAYS,
          unverified_error=False):
    """Audit a parsed user list and return a list of findings."""
    findings = []
    for user in users:
        user_id = user["id"]
        open_tickets = user["open_tickets"]
        total_tickets = user["total_tickets"]
        has_open = open_tickets is not None and open_tickets > 0
        verified = user["verified"]
        if user["has_verified_column"] and verified is not True:
            if has_open:
                findings.append(Finding(
                    user_id, "unverified-email-open-tickets",
                    "error",
                    "user %s has an unverified email address "
                    "and %d open tickets, so replies will never "
                    "reach them"
                    % (user["name"] or user_id, open_tickets)))
            elif unverified_error:
                findings.append(Finding(
                    user_id, "unverified-email", "error",
                    "user %s has an unverified email address"
                    % (user["name"] or user_id)))
            else:
                findings.append(Finding(
                    user_id, "unverified-email", "warning",
                    "user %s has an unverified email address"
                    % (user["name"] or user_id)))
        suspended = user["suspended"]
        if user["has_suspended_column"] and suspended is True:
            if has_open:
                findings.append(Finding(
                    user_id, "suspended-with-open-tickets", "error",
                    "suspended user %s still has %d open tickets, "
                    "so the queue is stuck on a user who cannot "
                    "reply" % (user["name"] or user_id,
                               open_tickets)))
            else:
                findings.append(Finding(
                    user_id, "suspended-user", "warning",
                    "suspended user %s has no open tickets, so "
                    "the account is safe to delete"
                    % (user["name"] or user_id)))
        if total_tickets == 0:
            created_at = user["created_at"]
            if created_at is not None:
                age_days = (as_of - created_at
                            ).total_seconds() / 86400.0
                if age_days > stale_days:
                    findings.append(Finding(
                        user_id, "no-tickets-user", "warning",
                        "user %s opened no tickets in %.1f days "
                        "since signing up, so the account looks "
                        "abandoned"
                        % (user["name"] or user_id, age_days)))
            else:
                findings.append(Finding(
                    user_id, "no-tickets-user", "warning",
                    "user %s opened no tickets and has no "
                    "signup date, so the account cannot be aged"
                    % (user["name"] or user_id)))
    return findings


def summarize(users, findings, as_of,
              stale_days=DEFAULT_STALE_DAYS):
    """Return the summary counts for a user list and findings."""
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings
                   if item.severity == "warning")
    user_ids = set(item["id"] for item in users)
    users_with_errors = set()
    for item in findings:
        if item.severity == "error" and item.user in user_ids:
            users_with_errors.add(item.user)
    clean = sum(1 for item in users
                if item["id"] not in users_with_errors)

    def count_rule(rule):
        return sum(1 for item in findings if item.rule == rule)

    verified = sum(1 for item in users if item["verified"] is True)
    suspended = sum(1 for item in users if item["suspended"] is True)
    open_tickets = sum(item["open_tickets"] or 0 for item in users)
    per_role = []
    roles = {}
    for user in users:
        role = user["role"] or "unknown"
        roles.setdefault(role, []).append(user)
    for role in sorted(roles):
        role_users = roles[role]
        role_errors = sum(
            1 for item in findings
            if item.severity == "error"
            and item.user in
            set(other["id"] for other in role_users))
        per_role.append({
            "role": role,
            "users": len(role_users),
            "errors": role_errors})
    return {"users": len(users),
            "findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "clean_users": clean,
            "users_with_errors": len(users) - clean,
            "duplicate_users": (count_rule("duplicate-email")
                                + count_rule("duplicate-user-id")),
            "duplicate_emails": count_rule("duplicate-email"),
            "unverified_emails": (
                count_rule("unverified-email")
                + count_rule("unverified-email-open-tickets")),
            "suspended_with_open_tickets": count_rule(
                "suspended-with-open-tickets"),
            "suspended_users": suspended,
            "no_tickets_users": count_rule("no-tickets-user"),
            "open_tickets": open_tickets,
            "verified_rate": (round(100.0 * verified / len(users), 1)
                              if users else 0.0),
            "per_role": per_role}


def render_text(users, findings, summary):
    """Render the text report."""
    lines = [str(item) for item in findings]
    lines.append("")
    lines.append("Users: %(users)d, findings: %(findings)d, "
                 "errors: %(errors)d, warnings: %(warnings)d"
                 % summary)
    lines.append("Clean users: %(clean_users)d of %(users)d users"
                 % summary)
    lines.append("Duplicate users: %(duplicate_users)d "
                 "(%(duplicate_emails)d duplicate emails), "
                 "unverified emails: %(unverified_emails)d, "
                 "suspended with open tickets: "
                 "%(suspended_with_open_tickets)d, suspended "
                 "users: %(suspended_users)d, users with no "
                 "tickets: %(no_tickets_users)d, open tickets: "
                 "%(open_tickets)d, verified rate: "
                 "%(verified_rate)s%%" % summary)
    lines.append("")
    lines.append("Per-role summary:")
    for row in summary["per_role"]:
        lines.append(
            "%s: %d users, %d errors"
            % (row["role"], row["users"], row["errors"]))
    if summary["findings"] == 0:
        lines.append("")
        lines.append("All users clean.")
    return "\n".join(lines) + "\n"


def render_json(users, findings, summary):
    """Render the JSON report."""
    report = dict(summary)
    report["findings"] = [item.as_dict() for item in findings]
    return json.dumps(report, indent=2) + "\n"


def build_parser():
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="zendesk-user-doctor",
        description="Audit a Zendesk end-user CSV export for "
                    "duplicate users, unverified emails, "
                    "suspended users with open tickets, and "
                    "users with no tickets.")
    parser.add_argument("csv_file", help="Zendesk end-user CSV "
                        "export to audit")
    parser.add_argument("--stale-days", type=int,
                        default=DEFAULT_STALE_DAYS,
                        help="a user with no tickets older than "
                        "this many days counts as abandoned "
                        "(default: %d)" % DEFAULT_STALE_DAYS)
    parser.add_argument("--unverified-error", action="store_true",
                        help="treat every unverified email as an "
                        "error, not just ones with open tickets")
    parser.add_argument("--as-of", default=None,
                        help="date to compare timestamps against, "
                        "for example 2026-11-18 (default: now)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser


def main(argv=None):
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    if args.stale_days < 0:
        print("error: --stale-days must be at least 0",
              file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = datetime.now(timezone.utc)
    else:
        as_of = parse_timestamp(args.as_of)
        if as_of is None:
            print("error: --as-of %r is not a readable date"
                  % args.as_of, file=sys.stderr)
            return 2
    try:
        users, findings = parse_csv(args.csv_file, as_of)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    findings.extend(audit(users, as_of,
                          stale_days=args.stale_days,
                          unverified_error=args.unverified_error))
    summary = summarize(users, findings, as_of,
                        stale_days=args.stale_days)
    if args.json:
        report = render_json(users, findings, summary)
    else:
        report = render_text(users, findings, summary)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)
    if args.check:
        if summary["errors"] > 0:
            return 1
        if args.strict and summary["warnings"] > 0:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
