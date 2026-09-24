# Polar HR Calcs

## Purpose

This project enriches Polar heart rate data in Smartabase. For each new
"Polar Summary - Training" session it converts the raw heart rate samples into
percentage of an athlete's all time maximum heart rate, then writes the result
to a new event on the "Polar Summary - Training - HR R" form. This runs
automatically on a schedule so coaches and staff see the percentage of max HR
values without any manual processing.

## What it does

The single script `polar_hr_calcs.py` runs end to end against the Teamworks
AMS (Smartabase) REST API:

1. Resolves the configured athlete group to a list of user IDs
   (`groupmembers`), since `eventsearch` needs explicit user IDs.
2. Reads "Polar Summary - Training" and "Polar Summary - Training - HR R"
   events for those users over the last 2 days (`eventsearch`).
3. Keeps only source sessions whose `ID` is not already on the target form.
   There is no stored sync time; the overlapping lookback plus the `ID` dedup
   makes reruns and delayed runs safe.
4. For each session, parses the raw heart rate CSV and adds a `% of Max HR`
   column, calculated against that athlete's `Max HR - All Time` value.
      - `Max HR - All Time` = max(`Maximum Heart Rate` from last 2 years, 220 - Age)
5. Inserts one target event per session (`insert`) with the transformed
   `Polar HR Data`, the `ID`, a `Formatted Date`, and the passthrough summary
   fields.

If there are no new sessions, or nothing is left to upload after processing,
the script logs a message and exits cleanly without inserting anything.

## Schedule

A GitHub Actions workflow (`.github/workflows/polar_hr_calcs.yml`) runs the
script at minute 8 and 38 of every hour (a 30 minute cadence). Cron in GitHub
Actions is evaluated in UTC, and scheduled runs can be delayed under GitHub
load. You can also trigger a run manually from the repository's Actions tab
(the workflow has `workflow_dispatch` enabled). The non-round timing was chosen
to try to prevent execessive queueing of the task as this action competes for 
resources. 

## Secrets

The script reads its Smartabase credentials and configuration from environment
variables. In GitHub Actions these come from repository secrets
(Settings, Secrets and variables, Actions). All four are required:

| Secret             | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `SB_USERNAME`      | Smartabase account username                          |
| `SB_PASSWORD`      | Smartabase account password                          |
| `SB_URL`           | Smartabase site URL                                  |
| `SB_ATHLETE_GROUP` | Smartabase group whose sessions are processed        |

## Running locally

Create a `.env` file in the project root with the same four values:

```
SB_USERNAME=your_username
SB_PASSWORD=your_password
SB_URL=https://your-site.smartabase.com/site
SB_ATHLETE_GROUP=Your Group Name
```

The script loads `.env` only if it exists, so the same code runs unchanged in
CI (where the values come from secrets). `.env` is gitignored and must never be
committed. Then run:

```
uv sync
uv run polar_hr_calcs.py
```

Dependencies are managed with [uv](https://docs.astral.sh/uv/) and pinned in
`uv.lock`. Add or update one with `uv add <package>` and commit both
`pyproject.toml` and `uv.lock`.
