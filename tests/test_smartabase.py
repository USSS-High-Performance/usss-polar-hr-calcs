from datetime import date

import pytest

from conftest import FakeResponse
from polar_hr_calcs.smartabase import SmartabaseClient, SmartabaseError


def client(fetch, **kwargs):
    return SmartabaseClient("example.smartabase.com/site/", "user", "pass", fetch=fetch, **kwargs)


def test_normalises_base_url(make_fetch):
    assert (
        client(make_fetch(lambda *_: FakeResponse())).api_url == "https://example.smartabase.com/site/api/v1"
    )


async def test_group_members_collects_ids_and_api_user(make_fetch):
    body = {
        "results": [{"search": {"userId": 99}, "results": [{"userId": 3}, {"userId": 1}, {"userId": 3}, {}]}]
    }
    members = await client(make_fetch(lambda *_: FakeResponse(body))).get_group_members("Team")
    assert members.user_ids == [1, 3]
    assert members.api_user_id == 99


async def test_search_events_sends_times_chunks_users_and_flattens_rows(make_fetch):
    event = {
        "startDate": "23/09/2026",
        "startTime": "9:59 AM",
        "finishDate": "23/09/2026",
        "finishTime": "10:59 AM",
        "userId": 1,
        "rows": [{"row": 0, "pairs": [{"key": "ID", "value": "abc"}, {"key": "Z1 Mins", "value": "8.1"}]}],
    }
    fetch = make_fetch(lambda *_: FakeResponse({"events": [event]}))
    records = await client(fetch, user_chunk_size=2).search_events(
        "Form", date(2026, 9, 23), date(2026, 9, 24), [1, 2, 3]
    )

    assert [payload["userIds"] for _, payload in fetch.calls] == [[1, 2], [3]]
    payload = fetch.calls[0][1]
    assert payload["startDate"] == "23/09/2026" and payload["finishDate"] == "24/09/2026"
    # without these the API ignores the date range
    assert payload["startTime"] == "12:00 AM" and payload["finishTime"] == "11:59 PM"
    assert records[0] == {
        "start_date": "23/09/2026",
        "start_time": "9:59 AM",
        "finish_date": "23/09/2026",
        "finish_time": "10:59 AM",
        "user_id": 1,
        "ID": "abc",
        "Z1 Mins": "8.1",
    }


async def test_empty_body_is_no_events(make_fetch):
    fetch = make_fetch(lambda *_: FakeResponse(""))
    assert await client(fetch).search_events("Form", date.today(), date.today(), [1]) == []


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse("Not Found", status=404),
        FakeResponse({"__is_rpc_exception__": True, "value": "bad request"}),
    ],
)
async def test_api_errors_raise(make_fetch, response):
    with pytest.raises(SmartabaseError):
        await client(make_fetch(lambda *_: response)).get_group_members("Team")


async def test_import_events_chunks_and_returns_results(make_fetch):
    fetch = make_fetch(
        lambda *_: FakeResponse({"result": {"state": "SUCCESSFULLY_IMPORTED", "message": "ok"}})
    )
    results = await client(fetch, import_chunk_size=2).import_events([{"a": 1}, {"a": 2}, {"a": 3}])
    assert [len(payload["events"]) for _, payload in fetch.calls] == [2, 1]
    assert [r["count"] for r in results] == [2, 1]


@pytest.mark.parametrize("state", ["UNEXPECTED_ERROR", "FAILURE", "IMPORTED_WITH_ERRORS"])
async def test_import_error_states_raise_even_with_http_200(make_fetch, state):
    fetch = make_fetch(lambda *_: FakeResponse({"result": {"state": state, "message": "nope"}}))
    with pytest.raises(SmartabaseError):
        await client(fetch).import_events([{"a": 1}])
