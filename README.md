# Polar HR Calcs

## Purpose

This project enriches Polar heart rate data in Smartabase. For each new
"Polar Summary - Training" session it converts the raw heart rate samples into
percentage of an athlete's all time maximum heart rate, then writes the result
to a new event on the "Polar Summary - Training - HR R" form. This runs
automatically on a schedule so coaches and staff see the percentage of max HR
values without any manual processing.

## What it does

A Cloudflare Python Worker (`src/polar_hr_calcs.py`) runs end to end on a cron trigger against
the Teamworks AMS (Smartabase) REST API:

1. Resolves the configured athlete group to a list of user IDs
   (`groupmembers`), since `eventsearch` needs explicit user IDs.
2. Reads "Polar Summary - Training" and "Polar Summary - Training - HR R"
   events for those users over the last day (`eventsearch`).
3. Keeps only source sessions whose `ID` is not already on the target form.
   There is no stored sync time; the overlapping lookback plus the `ID` dedup
   makes reruns and delayed runs safe.
4. For each session, parses the raw heart rate CSV and adds a `% of Max HR`
   column, calculated against that athlete's `Max HR - All Time` value.
      - `Max HR - All Time` = max(`Maximum Heart Rate` from last 2 years, 220 - Age)
5. Inserts one target event per session (`eventsimport`) with the transformed
   `Polar HR Data`, the `ID`, a `Formatted Date`, and the passthrough summary
   fields.

If there are no new sessions, or nothing is left to upload after processing,
the Worker logs a message and exits cleanly without inserting anything.

## Schedule

The cron trigger in `wrangler.jsonc` runs the Worker every 30 minutes
(`*/30 * * * *`, evaluated in UTC). Each run's logs, and whether it succeeded,
are in the Cloudflare dashboard under Workers & Pages, `usss-polar-hr-calcs`,
Logs. A run that throws is marked as failed there.

## Secrets

The Worker reads its Smartabase credentials and configuration from environment
variables. When deployed these are Worker secrets; locally they come from
`.env`. All four are required:

| Secret             | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `SB_USERNAME`      | Smartabase account username                          |
| `SB_PASSWORD`      | Smartabase account password                          |
| `SB_URL`           | Smartabase site URL                                  |
| `SB_ATHLETE_GROUP` | Smartabase group whose sessions are processed        |

Set or rotate a deployed secret with:

```
uv run pywrangler secret put SB_PASSWORD
```

Optional: set `DRY_RUN=true` to log what would be inserted without writing to
Smartabase.

## Running locally

Create a `.env` file in the project root with the same four values:

```
SB_USERNAME=your_username
SB_PASSWORD=your_password
SB_URL=https://your-site.smartabase.com/site
SB_ATHLETE_GROUP=Your Group Name
```

`.env` is gitignored and must never be committed. Wrangler loads it
automatically for local development (as long as there is no `.dev.vars` file).
Requires [uv](https://docs.astral.sh/uv/) 0.12.3 or newer and Node.js. Then
run:

```
npm install
uv sync
npm run dev
```

`npm run dev` is a shortcut for
`uv run pywrangler dev --var ALLOW_MANUAL_TRIGGER:true`.
`pywrangler` is Cloudflare's Python wrapper around `wrangler`; it bundles the
Python packages listed in `pyproject.toml` and then runs wrangler.

The cron does not fire on its own locally. With the dev server running, trigger
a run from another terminal (wrangler's built in `--test-scheduled` route does
not work for Python Workers, so the Worker handles `/__scheduled` itself, only
when `npm run dev` sets `ALLOW_MANUAL_TRIGGER`):

```
curl "http://localhost:8787/__scheduled?cron=*/30+*+*+*+*"
```

Output appears in the `npm run dev` terminal. Note this is a real run: it
inserts into Smartabase unless `DRY_RUN=true` is in `.env`.

## Deploying

```
npm run deploy
```

This runs `uv run pywrangler deploy`.

## Python in a Worker

The Worker runs on Pyodide (Python compiled to WebAssembly), so a few things
differ from a normal Python script:

- HTTP calls use the async `fetch` from the `workers` package, not `requests`.
- Settings come from the Worker's `env` (`env.SB_URL`), not `os.environ`.
- Runtime packages go in `pyproject.toml` `dependencies` (`uv add <package>`)
  and must be pure Python or available in Pyodide. `workers-py` and
  `workers-runtime-sdk` are dev only tooling.
