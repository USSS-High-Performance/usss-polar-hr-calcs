from datetime import date

import pytest

from polar_hr_calcs import config
from polar_hr_calcs.smartabase import GroupMembers
from polar_hr_calcs.sync import build_target_event, run_sync, select_new_sessions

SAMPLES = "Timestamp,Heart Rate<br>1,99"


def session(session_id, **fields):
    return {
        "start_date": "23/09/2026",
        "start_time": "9:59 AM",
        "finish_date": "23/09/2026",
        "finish_time": "10:59 AM",
        "user_id": 1,
        "ID": session_id,
        config.HR_SAMPLES_FIELD: SAMPLES,
        config.MAX_HR_FIELD: "198",
        **fields,
    }


class FakeClient:
    def __init__(self, sources, targets=(), user_ids=(1,)):
        self.forms = {config.SOURCE_FORM: list(sources), config.TARGET_FORM: list(targets)}
        self.user_ids = list(user_ids)
        self.imported = []
        self.searches = []

    async def get_group_members(self, group):
        return GroupMembers(self.user_ids, api_user_id=99)

    async def search_events(self, form, start, finish, user_ids):
        self.searches.append((form, start, finish))
        return self.forms[form]

    async def import_events(self, events):
        self.imported.extend(events)
        return [{"count": len(events), "state": "SUCCESSFULLY_IMPORTED"}]


def test_select_new_sessions_skips_processed_blank_and_repeated_ids():
    sessions = [session("a"), session("b"), session(""), session(None), session("b"), session("c")]
    assert [s["ID"] for s in select_new_sessions(sessions, ["a"])] == ["b", "c"]


def test_build_target_event():
    event = build_target_event(session("abc", **{"Z1 Mins": "8.1", "Z2 Mins": ""}), "hr-data", 99)
    assert event == {
        "formName": config.TARGET_FORM,
        "startDate": "23/09/2026",
        "finishDate": "23/09/2026",
        "startTime": "9:59 AM",
        "finishTime": "10:59 AM",
        "userId": {"userId": 1},
        "enteredByUserId": 99,
        "rows": [
            {
                "row": 0,
                "pairs": [
                    {"key": "ID", "value": "abc"},
                    {"key": "Z1 Mins", "value": "8.1"},  # blank passthrough fields are left out
                    {"key": "Formatted Date", "value": "23/09/2026"},
                    {"key": "Polar HR Data", "value": "hr-data"},
                ],
            }
        ],
    }


def test_build_target_event_rejects_unexpected_date_format():
    with pytest.raises(ValueError):
        build_target_event(session("abc", start_date="2026-09-23"), "hr-data", 99)


async def test_run_sync_inserts_only_new_transformable_sessions():
    client = FakeClient(
        sources=[session("done"), session("new"), session("bad", **{config.HR_SAMPLES_FIELD: ""})],
        targets=[{"ID": "done"}],
    )
    result = await run_sync(client, "Team", today=date(2026, 9, 24), lookback_days=1)

    assert [e["rows"][0]["pairs"][0]["value"] for e in client.imported] == ["new"]
    assert result.inserted_ids == ["new"]
    assert result.skipped_ids == ["bad"]
    assert (result.members, result.source_sessions, result.new_sessions) == (1, 3, 2)
    assert client.searches[0] == (config.SOURCE_FORM, date(2026, 9, 23), date(2026, 9, 24))


async def test_run_sync_dry_run_does_not_import():
    client = FakeClient(sources=[session("new")])
    result = await run_sync(client, "Team", dry_run=True)
    assert client.imported == []
    assert result.inserted_ids == ["new"] and result.dry_run


async def test_run_sync_stops_early_without_members():
    client = FakeClient(sources=[session("new")], user_ids=[])
    result = await run_sync(client, "Team")
    assert client.searches == [] and client.imported == []
    assert result.members == 0
