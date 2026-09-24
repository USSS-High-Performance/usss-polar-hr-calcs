# Cloudflare Python Worker. On each cron run, new "Polar Summary - Training"
# sessions have their raw heart rate samples converted to % of the athlete's
# all time max HR and are inserted as events on the target form.
import csv
import io
import json
import re
import sys
import logging
from base64 import b64encode
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint, fetch

# In a Worker stdout becomes console.log and stderr becomes console.error, so
# send INFO to stdout and keep only warnings and errors on stderr.
_info = logging.StreamHandler(sys.stdout)
_info.addFilter(lambda record: record.levelno < logging.WARNING)
_errors = logging.StreamHandler(sys.stderr)
_errors.setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=[_info, _errors])
log = logging.getLogger("polar_hr_calcs")

source_form_name = "Polar Summary - Training"
target_form_name = "Polar Summary - Training - HR R"
source_field = "Heart Rate Samples"
max_field = "Max HR - All Time"  # histortical calc from Polar HR data
target_field = "Polar HR Data"
id_field = "ID"  # unique key present on both forms, used to prevent duplicate processing
formatted_date_field = "Formatted Date"  # new field, target form only

# fields carried over unchanged from the source form to the target form
passthrough_fields = [
    "Detailed Sport Info",
    "Duration (txt)",
    "Heart Rate Maximum",
    "Edwards' TRiMP",
    "Z1 Mins",
    "Z2 Mins",
    "Z3 Mins",
    "Z4 Mins",
    "Z5 Mins",
]

LOOKBACK_DAYS = 1  # both forms are pulled over this window and deduped on ID
USER_CHUNK_SIZE = 200  # userIds sent per eventsearch request
INSERT_CHUNK_SIZE = 50  # events sent per insert request


class Smartabase:
    """Minimal Teamworks AMS (Smartabase) API client."""

    def __init__(self, env):
        # accept the site URL with or without a scheme or trailing slash
        base_url = env.SB_URL.rstrip("/")
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        self.api_url = f"{base_url}/api/v1"

        credentials = b64encode(f"{env.SB_USERNAME}:{env.SB_PASSWORD}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-APP-ID": "usss-polar-hr-calcs",
        }

    async def post(self, endpoint, payload):
        """POST to the Teamworks AMS API and return the parsed JSON body."""
        response = await fetch(
            f"{self.api_url}/{endpoint}?informat=json&format=json",
            method="POST",
            headers=self.headers,
            body=json.dumps(payload),
        )
        text = await response.text()
        if not response.ok:
            raise RuntimeError(f"{endpoint} failed: {response.status} {text[:500]}")
        if not text.strip():
            return {}
        body = json.loads(text)
        # Smartabase can report errors with a 200 status and an RPC exception body
        if isinstance(body, dict) and body.get("__is_rpc_exception__"):
            raise RuntimeError(f"{endpoint} failed: {body.get('value')}")
        return body


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def get_group_members(sb, group_name):
    """Return (member user IDs, user ID of the API account) for a group."""
    body = await sb.post("groupmembers", {"name": group_name})
    user_ids = set()
    api_user_id = None
    for result in body.get("results", []):
        api_user_id = api_user_id or result.get("search", {}).get("userId")
        for member in result.get("results", []):
            if member.get("userId") is not None:
                user_ids.add(member["userId"])
    return sorted(user_ids), api_user_id


async def get_events(sb, form_name, start_date, finish_date, user_ids):
    """Pull events for a form and flatten them to one dict per event row."""
    records = []
    for ids in chunked(user_ids, USER_CHUNK_SIZE):
        body = await sb.post(
            "eventsearch",
            {
                "formNames": [form_name],
                "startDate": start_date,
                "finishDate": finish_date,
                # the date range is ignored (all history is returned) unless
                # start and finish times are sent alongside the dates
                "startTime": "12:00 AM",
                "finishTime": "11:59 PM",
                "userIds": ids,
            },
        )
        for event in body.get("events") or []:
            meta = {
                "start_date": event.get("startDate"),
                "start_time": event.get("startTime"),
                "finish_date": event.get("finishDate"),
                "finish_time": event.get("finishTime"),
                "user_id": event.get("userId"),
            }
            for row in event.get("rows") or []:
                pairs = {p["key"]: p.get("value") for p in row.get("pairs", [])}
                records.append({**meta, **pairs})
    return records


def transform_hr(hr_csv, max_hr):
    """Add a % of Max HR column to the raw samples CSV, or return None to skip."""

    # Skip sessions with nothing to transform: blank or missing samples, or a
    # missing max HR. Returning None lets the run continue instead of erroring.
    if not hr_csv or not hr_csv.strip():
        return None
    try:
        max_hr = float(max_hr)
    except (TypeError, ValueError):
        return None
    if max_hr <= 0:
        return None

    # Wrap parsing so one malformed session (e.g. no Heart Rate column) is
    # skipped rather than halting the whole job.
    try:
        # samples arrive with <br> line breaks, convert back to newlines
        text = re.sub(r"<\s*br\s*/?>", "\n", hr_csv)
        reader = csv.DictReader(io.StringIO(text))
        if "Heart Rate" not in (reader.fieldnames or []):
            log.warning("Heart Rate column not found in samples; skipping session.")
            return None

        fieldnames = [f for f in reader.fieldnames if f != "% of Max HR"] + ["% of Max HR"]
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in reader:
            try:
                pct = round(float(row["Heart Rate"]) / max_hr * 100, 2)  # take % of max HR
                row["% of Max HR"] = f"{pct:g}"
            except (TypeError, ValueError):
                row["% of Max HR"] = ""
            writer.writerow(row)
        return out.getvalue().rstrip("\n")
    except Exception as e:
        log.warning("Failed to transform heart rate samples: %s", e)
        return None


def build_insert_event(session, api_user_id):
    """Build an insert payload event for the target form from a source session."""
    # event date, reformatted from Smartabase's dd/mm/yyyy into DD/MM/YYYY
    formatted_date = datetime.strptime(session["start_date"], "%d/%m/%Y").strftime("%d/%m/%Y")

    pairs = [{"key": id_field, "value": session[id_field]}]
    for field in passthrough_fields:
        value = session.get(field)
        if value not in (None, ""):
            pairs.append({"key": field, "value": value})
    pairs.append({"key": formatted_date_field, "value": formatted_date})
    pairs.append({"key": target_field, "value": session[target_field]})

    event = {
        "formName": target_form_name,
        "startDate": session["start_date"],
        "finishDate": session.get("finish_date") or session["start_date"],
        "userId": {"userId": session["user_id"]},
        "rows": [{"row": 0, "pairs": pairs}],
    }
    if session.get("start_time"):
        event["startTime"] = session["start_time"]
    if session.get("finish_time"):
        event["finishTime"] = session["finish_time"]
    if api_user_id is not None:
        event["enteredByUserId"] = api_user_id
    return event


async def main(env):
    for key in ("SB_USERNAME", "SB_PASSWORD", "SB_URL", "SB_ATHLETE_GROUP"):
        if not getattr(env, key, None):
            raise RuntimeError(f"Missing {key}. Set it in .env locally or as a Worker secret.")
    sb = Smartabase(env)

    # Load recent Polar Summary - Training
    today = date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)

    # format to dd/mm/yyyy
    start_formatted = start.strftime("%d/%m/%Y")
    today_formatted = today.strftime("%d/%m/%Y")

    # the API has no group filter on eventsearch, so resolve the group to user IDs
    user_ids, api_user_id = await get_group_members(sb, env.SB_ATHLETE_GROUP)
    if not user_ids:
        log.info("No members found in group. Exiting.")
        return
    log.info("Found %d members in group.", len(user_ids))

    sessions = await get_events(sb, source_form_name, start_formatted, today_formatted, user_ids)

    # keep only rows with a usable ID
    sessions = [s for s in sessions if (s.get(id_field) or "").strip()]

    # if there are no sessions with an ID, exit script
    if not sessions:
        log.info("No source sessions with a valid ID. Exiting.")
        return

    # Pull already processed sessions from the target form over the same lookback
    # so we can skip any source ID that has already been pushed there.
    target_sessions = await get_events(sb, target_form_name, start_formatted, today_formatted, user_ids)
    processed_ids = {t[id_field] for t in target_sessions if t.get(id_field)}

    # filter down to source sessions that have not yet been processed, keeping
    # only the first occurrence of any ID repeated within the source pull
    new_sessions = []
    for s in sessions:
        if s[id_field] not in processed_ids:
            processed_ids.add(s[id_field])
            new_sessions.append(s)

    # if all sessions have been processed exit script
    if not new_sessions:
        log.info("No new sessions to process. Exiting.")
        return

    # apply transform_hr to each session
    skipped = []
    events = []
    for s in new_sessions:
        s[target_field] = transform_hr(s.get(source_field), s.get(max_field))
        if s[target_field] is None:
            skipped.append(s[id_field])
        else:
            events.append(build_insert_event(s, api_user_id))

    # Log any sessions that could not be transformed (blank or malformed
    # samples), so a few bad records do not block the rest of the upload.
    if skipped:
        log.info(
            "Skipped %d session(s) with blank or invalid heart rate samples (ID: %s).",
            len(skipped),
            ", ".join(skipped),
        )

    # Exit cleanly if nothing is left to upload.
    if not events:
        log.info("No sessions to upload after processing. Exiting.")
        return

    if str(getattr(env, "DRY_RUN", "")).lower() == "true":
        log.info(
            "DRY_RUN: would insert %d event(s) (ID: %s).",
            len(events),
            ", ".join(e["rows"][0]["pairs"][0]["value"] for e in events),
        )
        return

    # Upload data to Smartabase as new events on the target form
    for batch in chunked(events, INSERT_CHUNK_SIZE):
        body = await sb.post("eventsimport", {"events": batch})
        # a failed import can still return 200, with the outcome in result.state
        result = body.get("result") or {}
        state = result.get("state", "")
        if "ERROR" in state or state == "FAILURE":
            raise RuntimeError(f"eventsimport {state}: {result.get('message')} {body}")
        log.info("Inserted %d event(s): %s %s", len(batch), state, result.get("message", ""))


class Default(WorkerEntrypoint):
    async def scheduled(self, controller, env, ctx):
        await self.run()

    async def fetch(self, request):
        # Local testing only. wrangler's --test-scheduled route does not work for
        # Python Workers, so `npm run dev` sets ALLOW_MANUAL_TRIGGER and this
        # handler runs the job on /__scheduled. Deployed, it is always a 404.
        if (
            str(getattr(self.env, "ALLOW_MANUAL_TRIGGER", "")).lower() == "true"
            and urlparse(request.url).path == "/__scheduled"
        ):
            await self.run()
            return Response("Ran scheduled event")
        return Response("Not found", status=404)

    async def run(self):
        # an exception here marks the run as failed in the Workers dashboard
        try:
            await main(self.env)
        except Exception:
            log.exception("Polar HR calcs failed.")
            raise
