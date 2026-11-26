# Changelog

## 1.0.0 - 2026-11-23

Initial release.

* Zendesk end-user audit over a CSV export: duplicate
  users (duplicate emails compared case-insensitively,
  and duplicate user ids), unverified emails, suspended
  users with open tickets, and users who never opened a
  ticket.
* Clean count: users with no error findings are clean,
  with a per-role table (users and errors per role),
  plus the verified rate, suspended count, and total
  open tickets.
* Unverified email is an error when the user has open
  tickets and a warning otherwise, unless
  --unverified-error promotes every unverified email to
  an error. Suspended users with no open tickets are a
  warning, safe to delete. A user with no tickets is
  only flagged when the signup is more than
  --stale-days (default 90) old.
* Data quality checks: duplicate and missing user ids,
  missing and invalid emails, invalid roles, invalid
  and future dates, invalid and missing ticket counts,
  open tickets exceeding total tickets, and malformed
  rows.
* Defensive timestamp parsing (ISO 8601 with or without
  a timezone, plus common day/month/year forms) and
  ticket count parsing (plain integers, thousands
  separators); a bad row is reported as a finding and
  never crashes the run. UTF-8 BOM headers and extra
  columns handled.
* Findings carry a user id, a rule name, a severity
  (error or warning), and a message; errors and warnings
  are counted in the summary.
* Text and --json output, --out file output,
  --stale-days, --unverified-error, and --as-of
  thresholds, and a --check CI gate that exits 1 on
  errors (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
