# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a per-user ticket summary table

Title: Show the users with open tickets as a table

Description: After the per-role summary, print a short
table of the users with open tickets sorted by open
ticket count, most first (user id, name, email, open
tickets, total tickets, verified or not), so a support
manager can work the chase list top-down without
reading every finding. Users with no open tickets are
left out.

Difficulty: Easy

Acceptance criteria: the table appears in text output with
the correct order for the sample file (U-110 first with
5 open tickets, then U-114 with 4, then U-103 with 3);
JSON output is unchanged; a test checks the table rows.

## 2. Flag users who never logged in

Title: Warn on users who never logged in after signing up

Description: Add a `never-logged-in` warning for a user
whose last_login cell is empty and whose signup is more
than --stale-days old, so an account that was created
and never used can be cleaned up. The check only runs
when the last_login column is present in the export.

Difficulty: Easy

Acceptance criteria: a user with an empty last login and
an old signup gets the warning and still passes
--check; the sample file is unchanged (every row has a
last login); a test covers both cases.

## 3. Report the role with the most errors in the summary

Title: Print the role with the most errors

Description: Add one line to the text summary naming the
role with the most errors (role, error count, user
count), so a support manager can see the biggest user
problem at a glance. When every role has zero errors,
the line is omitted.

Difficulty: Easy

Acceptance criteria: the line appears for the sample file
naming end-user at 10 errors; it is absent for the
clean file, where no role has errors; JSON output is
unchanged; a test checks both cases.

## 4. Add a configurable duplicate email window

Title: Only flag duplicate emails within a signup window

Description: Add a --duplicate-days flag that only flags
a duplicate email when the two records were created
within that many days of each other (measured on
created_at). The default stays at no window, meaning
every duplicate is flagged. When a record has no
created date, the duplicate is still flagged.

Difficulty: Easy

Acceptance criteria: with --duplicate-days 365 the sample
file still flags U-109 (records about 357 days apart)
and a test with records 500 days apart is not flagged;
README documents the flag.
