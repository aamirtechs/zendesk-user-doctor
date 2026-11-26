# zendesk-user-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/zendesk-user-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/zendesk-user-doctor/issues)

A zero-dependency Python CLI that audits a Zendesk
end-user CSV export for the problems that quietly
break support: duplicate users (the same email twice,
or the same user id twice), unverified email
addresses, suspended users who still have open
tickets, and users who never opened a ticket at all.
It also prints a verified rate, a suspended count,
and a per-role table, so a support manager can see at
a glance which users need chasing and which accounts
are safe to clean up.

A support inbox lives or dies on reaching the right
person. A reply sent to an unverified address never
arrives, a suspended user with open tickets keeps a
queue stuck, and a user list full of duplicates means
the same person gets two different answers. Zendesk
itself will not flag any of this in the export. This
tool is that audit: it ranks the users in the export
alone, and never touches a live Zendesk API.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install zendesk-user-doctor
```

Or run it straight from the source checkout:

```bash
python3 zendesk_user_doctor.py examples/users.csv
```

## Input format

A CSV export with a header row, from the Zendesk admin
center user export or a support team's user
spreadsheet. Columns used: `user_id` (or `id`),
`name` (or `full_name`), `email` (or `email_address`),
`role` (or `user_role`), `email_verified` (or
`verified`), `suspended` (or `is_suspended`),
`created_at` (or `created`), `last_login` (or
`last_sign_in`), `open_tickets` (or
`open_ticket_count`), `total_tickets` (or
`ticket_count`), and `last_ticket_date` (or
`last_ticket`). Extra columns are ignored, so a full
user export works as-is. A UTF-8 BOM header is
handled. Only `user_id` and `email` are required; the
other columns are optional, and the checks that need a
missing column are skipped.

`user_id` also accepts `user`, `email` also accepts
`user_email`, `name` also accepts `user_name`, `role`
also accepts `type`, `email_verified` also accepts
`is_verified` or `verification_status`, `suspended`
also accepts `suspension_status`, `created_at` also
accepts `date_created` or `signup_date`, `last_login`
also accepts `last_login_at` or `last_active`,
`open_tickets` also accepts `open_requests`,
`total_tickets` also accepts `total_requests`, and
`last_ticket_date` also accepts `last_request_date`.

Dates accept ISO 8601 with or without a timezone
(`2026-11-17 10:00`, `2026-11-17T10:00:00Z`,
`2026-11-17`), plus day/month/year and month/day/year
forms. A date with no timezone is read as UTC. Ticket
counts accept plain integers with optional thousands
separators (`12`, `1,200`). An email verified value
of `yes`, `verified`, or `confirmed` counts as
verified. A role of `end user`, `customer`, or
`requester` counts as `end-user`.

```csv
user_id,name,email,role,email_verified,suspended,created_at,last_login,open_tickets,total_tickets,last_ticket_date
U-101,Alice Morgan,alice.morgan@example.com,end-user,yes,no,2024-01-10,2026-11-15,0,5,2026-11-10
U-102,Ben Carter,ben.carter@example.com,end-user,no,no,2024-02-01,2026-11-12,2,4,2026-11-12
U-103,Cara Diaz,cara.diaz@example.com,end-user,yes,yes,2023-06-15,2026-10-20,3,8,2026-11-05
U-104,Dan Evans,dan.evans@example.com,end-user,yes,no,2023-03-01,2023-04-01,0,0,
U-105,Emma Foster,emma.foster@example.com,end-user,no,no,2026-10-20,2026-11-17,0,1,2026-11-01
```

## What it checks

Errors, the ones that mean a user must be fixed or data
that cannot be trusted:

* `unverified-email-open-tickets`: a user with an
  unverified email address and open tickets, so replies
  will never reach them. The message names the user and
  the open ticket count.
* `suspended-with-open-tickets`: a suspended user who
  still has open tickets, so the queue is stuck on a
  user who cannot reply.
* `duplicate-email`: an email address that already
  appears in the export, so two records claim the same
  user. Emails are compared case-insensitively, so
  "ALICE.MORGAN@EXAMPLE.COM" and
  "alice.morgan@example.com" count as the same user.
* `duplicate-user-id`: the same user id twice in the
  export.
* `missing-user-id`: a row with no user id, so the user
  cannot be matched to a Zendesk record.
* `missing-email`: a user with no email address, so
  Zendesk cannot reach them at all.
* `invalid-email`: an email address that is not a valid
  email address.
* `invalid-role`: a role that is not a known Zendesk
  role (end-user, agent, or admin).
* `invalid-date`: a created, last login, or last ticket
  date that matches no known format. The row is still
  audited on the fields that did parse.
* `future-timestamp`: a `created_at` or `last_login`
  after `--as-of` (default now).
* `invalid-ticket-count`: an open or total ticket count
  that is not a non-negative number. The row is still
  audited on the fields that did parse.
* `missing-ticket-count`: a user with no open or total
  ticket count recorded, so the queue or history cannot
  be checked.
* `open-exceeds-total`: a user with more open tickets
  than total tickets, which cannot both be true.
* `malformed-row`: a row with the wrong number of
  fields. The row is skipped and reported, never a
  crash.

Warnings, users worth a closer look:

* `unverified-email`: a user with an unverified email
  address and no open tickets. With
  `--unverified-error` this becomes an error instead.
* `suspended-user`: a suspended user with no open
  tickets, so the account is safe to delete.
* `no-tickets-user`: a user who opened no tickets and
  signed up more than `--stale-days` ago (default 90),
  so the account looks abandoned.

The summary reports the user, finding, error, and
warning counts, how many users are clean (no error
findings), the counts per problem (duplicate users,
unverified emails, suspended with open tickets,
suspended users, users with no tickets), the total open
tickets, the verified rate, and a per-role table
(users and errors per role).

## Usage

```bash
python3 zendesk_user_doctor.py examples/users.csv --as-of 2026-11-18
```

Captured output:

```
ERROR [duplicate-email] U-109: email address ALICE.MORGAN@EXAMPLE.COM already appears in the export, so two records claim the same user
ERROR [open-exceeds-total] U-114: user has 4 open tickets but only 2 total tickets, which cannot both be true
ERROR [invalid-email] U-115: email address 'not-an-email' is not a valid email address
ERROR [invalid-date] U-116: created date 'not-a-date' is not a readable date
ERROR [future-timestamp] U-117: created date 2026-12-05 00:00 is after the as-of date 2026-11-18 00:00
ERROR [duplicate-user-id] U-101: user id appears more than once in the export
ERROR [malformed-row] row 20: row has 12 fields but the header has 11, so the row was skipped
ERROR [missing-user-id] row 21: row has no user id, so the user cannot be matched to a Zendesk record
ERROR [invalid-ticket-count] U-119: open ticket count 'abc' is not a non-negative number
ERROR [invalid-role] U-120: role 'superuser' is not a known Zendesk role (end-user, agent, or admin)
ERROR [unverified-email-open-tickets] U-102: user Ben Carter has an unverified email address and 2 open tickets, so replies will never reach them
ERROR [suspended-with-open-tickets] U-103: suspended user Cara Diaz still has 3 open tickets, so the queue is stuck on a user who cannot reply
WARNING [no-tickets-user] U-104: user Dan Evans opened no tickets in 1358.0 days since signing up, so the account looks abandoned
WARNING [unverified-email] U-105: user Emma Foster has an unverified email address
WARNING [suspended-user] U-111: suspended user Karen Lee has no open tickets, so the account is safe to delete
WARNING [no-tickets-user] U-112: user Leo Martin opened no tickets in 958.0 days since signing up, so the account looks abandoned

Users: 21, findings: 16, errors: 12, warnings: 4
Clean users: 9 of 21 users
Duplicate users: 2 (1 duplicate emails), unverified emails: 2, suspended with open tickets: 1, suspended users: 2, users with no tickets: 2, open tickets: 15, verified rate: 90.5%

Per-role summary:
agent: 1 users, 0 errors
end-user: 19 users, 10 errors
unknown: 1 users, 1 errors
```

The sample has 22 rows; the malformed row 20 is skipped,
so 21 users are audited. The headline numbers are 9 of
21 users clean, 2 duplicate users (one duplicate email,
one duplicate id), 2 unverified emails (one with open
tickets, one without), 1 suspended user with open
tickets, 2 users with no tickets, 15 open tickets in
total, and a 90.5% verified rate. Ben Carter (U-102)
has an unverified email and 2 open tickets, so his
replies will never arrive. Cara Diaz (U-103) is
suspended with 3 open tickets, so her queue is stuck.
Dan Evans (U-104) signed up 1358.0 days ago and never
opened a ticket. Mia Nelson (U-113) also has no
tickets, but she signed up only 3 days before the
as-of date, so she is not flagged. The user id U-101
appears twice, so both records sharing that id count
as not clean even though the first one is otherwise
clean.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 zendesk_user_doctor.py examples/users.csv --as-of 2026-11-18 --check
```

On `examples/clean.csv`, five clean users, it exits 0:

```
Users: 5, findings: 0, errors: 0, warnings: 0
Clean users: 5 of 5 users
Duplicate users: 0 (0 duplicate emails), unverified emails: 0, suspended with open tickets: 0, suspended users: 0, users with no tickets: 0, open tickets: 6, verified rate: 100.0%

Per-role summary:
agent: 1 users, 0 errors
end-user: 4 users, 0 errors

All users clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one user with no
tickets, one unverified email, and one suspended user
with no open tickets, so it passes `--check` (exit 0)
and fails `--check --strict` (exit 1). With a longer
stale window the no-ticket warnings drop out:

```bash
python3 zendesk_user_doctor.py examples/users.csv --as-of 2026-11-18 --stale-days 2000
```

Captured output (the two no-tickets warnings drop out;
the rest of the output is identical to the default
run):

```
Users: 21, findings: 14, errors: 12, warnings: 2
Clean users: 9 of 21 users
Duplicate users: 2 (1 duplicate emails), unverified emails: 2, suspended with open tickets: 1, suspended users: 2, users with no tickets: 0, open tickets: 15, verified rate: 90.5%

Per-role summary:
agent: 1 users, 0 errors
end-user: 19 users, 10 errors
unknown: 1 users, 1 errors
```

With `--unverified-error` the unverified email with no
open tickets becomes an error too, so the run reports
13 errors and 3 warnings and 8 of 21 users clean.
`--json` emits the summary and the findings as JSON,
and `--out` writes the report to a file. JSON for the
warnings-only file:

```json
{
  "users": 3,
  "findings": [
    {
      "user": "U-401",
      "rule": "no-tickets-user",
      "severity": "warning",
      "message": "user Dan Evans opened no tickets in 1358.0 days since signing up, so the account looks abandoned"
    },
    {
      "user": "U-402",
      "rule": "unverified-email",
      "severity": "warning",
      "message": "user Emma Foster has an unverified email address"
    },
    {
      "user": "U-403",
      "rule": "suspended-user",
      "severity": "warning",
      "message": "suspended user Karen Lee has no open tickets, so the account is safe to delete"
    }
  ],
  "errors": 0,
  "warnings": 3,
  "clean_users": 3,
  "users_with_errors": 0,
  "duplicate_users": 0,
  "duplicate_emails": 0,
  "unverified_emails": 1,
  "suspended_with_open_tickets": 0,
  "suspended_users": 1,
  "no_tickets_users": 1,
  "open_tickets": 0,
  "verified_rate": 66.7,
  "per_role": [
    {
      "role": "end-user",
      "users": 3,
      "errors": 0
    }
  ]
}
```

## Options

| Flag | Meaning |
| --- | --- |
| `--stale-days` | A user with no tickets older than this many days counts as abandoned (default: 90) |
| `--unverified-error` | Treat every unverified email as an error, not just ones with open tickets |
| `--as-of` | Date to compare timestamps against, for example 2026-11-18 (default: now) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still
  audited. A malformed row is not a user, so it never
  counts for or against the clean count.
* A bad date or ticket count is an error, and the row is
  still audited on the fields that did parse, so one bad
  value never hides the other problems on the user. A
  user with an unreadable ticket count is left out of
  the open-exceeds-total check, and a user with an
  unreadable created date is left out of the no-tickets
  age check.
* A user with no email gets a missing-email error and is
  left out of the duplicate check; an email that is not
  a valid address gets an invalid-email error. Emails
  are compared case-insensitively, so "ALICE@EXAMPLE.COM"
  and "alice@example.com" are the same user.
* A user id that appears twice blocks both records
  sharing it, since the id can no longer be trusted to
  identify one user.
* A user with no tickets is only flagged when the signup
  is more than `--stale-days` old, so a brand new user
  who has not opened a ticket yet is never flagged. A
  user with no tickets and no signup date at all still
  gets the warning, since the account cannot be aged.
* An unverified email is an error only when the user has
  open tickets; otherwise it is a warning, unless
  `--unverified-error` is given.
* A blank line in the file is skipped silently.
* `--as-of` makes runs reproducible: without it, the
  future-timestamp and no-tickets age checks compare
  against the current time.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

66 tests, all passing: timestamp and count parsing,
yes/no parsing, email normalization, role
normalization, header aliases and BOM handling,
malformed rows, duplicate and missing user ids,
duplicate emails including case variants, missing and
invalid emails, invalid roles, invalid and future
dates, invalid and negative ticket counts, open tickets
exceeding total tickets, bad values still audited,
unverified emails with and without open tickets,
`--unverified-error` promotion, suspended users with
and without open tickets, no-tickets users with the
stale-days boundary, summary counts and verified rate,
the per-role table, duplicate ids blocking both rows,
text and JSON output, `--out` file output,
`--stale-days` and `--unverified-error` flags, and
`--check` and `--strict` exit codes. The same 66 tests
pass under pytest.

## License

MIT. See [LICENSE](LICENSE).
