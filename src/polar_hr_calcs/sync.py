"""The sync job: find new source sessions, transform them, insert target events."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from . import config
from .smartabase import EventRecord, SmartabaseClient
from .transform import add_percent_of_max_hr

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """What a run did, for logging and tests."""

    members: int = 0
    source_sessions: int = 0
    new_sessions: int = 0
    skipped_ids: list[str] = field(default_factory=list)
    inserted_ids: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        action = "would insert" if self.dry_run else "inserted"
        return (
            f"{self.members} members, {self.source_sessions} source sessions, "
            f"{self.new_sessions} new, {len(self.skipped_ids)} skipped, "
            f"{action} {len(self.inserted_ids)}"
        )


def select_new_sessions(sessions: Iterable[EventRecord], processed_ids: Iterable[str]) -> list[EventRecord]:
    """Keep sessions with a usable ID not already processed, first occurrence only."""
    seen = set(processed_ids)
    new = []
    for session in sessions:
        session_id = str(session.get(config.ID_FIELD) or "").strip()
        if session_id and session_id not in seen:
            seen.add(session_id)
            new.append(session)
    return new


def build_target_event(session: EventRecord, hr_data: str, api_user_id: int | None) -> dict[str, Any]:
    """Build an eventsimport event for the target form from a source session."""
    start_date = session["start_date"]
    # validates the event date is dd/mm/yyyy before it is written to Formatted Date
    formatted_date = datetime.strptime(start_date, "%d/%m/%Y").strftime("%d/%m/%Y")

    pairs = [{"key": config.ID_FIELD, "value": session[config.ID_FIELD]}]
    for name in config.PASSTHROUGH_FIELDS:
        value = session.get(name)
        if value not in (None, ""):
            pairs.append({"key": name, "value": value})
    pairs.append({"key": config.FORMATTED_DATE_FIELD, "value": formatted_date})
    pairs.append({"key": config.HR_DATA_FIELD, "value": hr_data})

    event: dict[str, Any] = {
        "formName": config.TARGET_FORM,
        "startDate": start_date,
        "finishDate": session.get("finish_date") or start_date,
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


async def run_sync(
    client: SmartabaseClient,
    athlete_group: str,
    *,
    dry_run: bool = False,
    today: date | None = None,
    lookback_days: int = config.LOOKBACK_DAYS,
) -> SyncResult:
    result = SyncResult(dry_run=dry_run)
    finish = today or date.today()  # UTC in the Workers runtime
    start = finish - timedelta(days=lookback_days)

    # eventsearch has no group filter, so resolve the group to user IDs
    members = await client.get_group_members(athlete_group)
    result.members = len(members.user_ids)
    if not members.user_ids:
        log.info("No members found in group %r.", athlete_group)
        return result

    sessions = await client.search_events(config.SOURCE_FORM, start, finish, members.user_ids)
    result.source_sessions = len(sessions)
    if not sessions:
        log.info("No source sessions between %s and %s.", start, finish)
        return result

    # IDs already on the target form over the same window have been processed
    targets = await client.search_events(config.TARGET_FORM, start, finish, members.user_ids)
    processed_ids = [t[config.ID_FIELD] for t in targets if t.get(config.ID_FIELD)]
    new_sessions = select_new_sessions(sessions, processed_ids)
    result.new_sessions = len(new_sessions)
    if not new_sessions:
        log.info("No new sessions to process.")
        return result

    events = []
    for session in new_sessions:
        hr_data = add_percent_of_max_hr(
            session.get(config.HR_SAMPLES_FIELD), session.get(config.MAX_HR_FIELD)
        )
        if hr_data is None:
            result.skipped_ids.append(session[config.ID_FIELD])
        else:
            events.append(build_target_event(session, hr_data, members.api_user_id))
            result.inserted_ids.append(session[config.ID_FIELD])

    # a few bad records should not block the rest of the upload
    if result.skipped_ids:
        log.info(
            "Skipped %d session(s) with blank or invalid heart rate samples (ID: %s).",
            len(result.skipped_ids),
            ", ".join(result.skipped_ids),
        )

    if not events:
        return result

    if dry_run:
        log.info("DRY_RUN: would insert %d event(s) (ID: %s).", len(events), ", ".join(result.inserted_ids))
        return result

    for batch in await client.import_events(events):
        log.info(
            "Inserted %d event(s): %s %s", batch["count"], batch.get("state", ""), batch.get("message", "")
        )
    return result
