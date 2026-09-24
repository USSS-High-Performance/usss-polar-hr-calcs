"""Minimal async client for the Teamworks AMS (Smartabase) v1 REST API.

The HTTP function is injected (the Workers `fetch` in production, a fake in
tests), so this module has no dependency on the Workers runtime.
"""

import json
from base64 import b64encode
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from . import config

# Called as fetch(url, method=..., headers=..., body=...). The response must
# expose `.ok`, `.status` and an awaitable `.text()`.
Fetch = Callable[..., Awaitable[Any]]

# One flattened event row: event metadata (start_date, start_time, finish_date,
# finish_time, user_id) plus the row's form fields keyed by field name.
EventRecord = dict[str, Any]


class SmartabaseError(RuntimeError):
    """The API returned an error, including errors reported with HTTP 200."""


@dataclass(frozen=True)
class GroupMembers:
    user_ids: list[int]
    api_user_id: int | None  # the account making the calls, used as enteredByUserId


def chunked(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def format_date(d: date) -> str:
    """Smartabase dates are dd/mm/yyyy."""
    return d.strftime("%d/%m/%Y")


class SmartabaseClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        fetch: Fetch,
        *,
        user_chunk_size: int = config.USER_CHUNK_SIZE,
        import_chunk_size: int = config.IMPORT_CHUNK_SIZE,
    ) -> None:
        # accept the site URL with or without a scheme or trailing slash
        base_url = base_url.rstrip("/")
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        self.api_url = f"{base_url}/api/v1"

        credentials = b64encode(f"{username}:{password}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-APP-ID": config.APP_ID,
        }
        self._fetch = fetch
        self._user_chunk_size = user_chunk_size
        self._import_chunk_size = import_chunk_size

    async def _post(self, endpoint: str, payload: Any) -> dict[str, Any]:
        """POST to an API endpoint and return the parsed JSON body."""
        response = await self._fetch(
            f"{self.api_url}/{endpoint}?informat=json&format=json",
            method="POST",
            headers=self._headers,
            body=json.dumps(payload),
        )
        text = await response.text()
        if not response.ok:
            raise SmartabaseError(f"{endpoint} failed: HTTP {response.status} {text[:500]}")
        if not text.strip():
            return {}
        body = json.loads(text)
        # Smartabase can report errors with a 200 status and an RPC exception body
        if isinstance(body, dict) and body.get("__is_rpc_exception__"):
            raise SmartabaseError(f"{endpoint} failed: {body.get('value')}")
        return body

    async def get_group_members(self, group_name: str) -> GroupMembers:
        """Resolve a group name to its members' user IDs."""
        body = await self._post("groupmembers", {"name": group_name})
        user_ids: set[int] = set()
        api_user_id = None
        for result in body.get("results", []):
            api_user_id = api_user_id or result.get("search", {}).get("userId")
            for member in result.get("results", []):
                if member.get("userId") is not None:
                    user_ids.add(member["userId"])
        return GroupMembers(sorted(user_ids), api_user_id)

    async def search_events(
        self, form_name: str, start: date, finish: date, user_ids: Sequence[int]
    ) -> list[EventRecord]:
        """Pull a form's events for the given users and dates, one record per event row."""
        records: list[EventRecord] = []
        for ids in chunked(user_ids, self._user_chunk_size):
            body = await self._post(
                "eventsearch",
                {
                    "formNames": [form_name],
                    "startDate": format_date(start),
                    "finishDate": format_date(finish),
                    # the date range is ignored (all history is returned) unless
                    # start and finish times are sent alongside the dates
                    "startTime": "12:00 AM",
                    "finishTime": "11:59 PM",
                    "userIds": list(ids),
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

    async def import_events(self, events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert events, returning the API's result for each batch."""
        results = []
        for batch in chunked(events, self._import_chunk_size):
            body = await self._post("eventsimport", {"events": list(batch)})
            # a failed import can still return 200, with the outcome in result.state
            result = body.get("result") or {}
            state = result.get("state", "")
            if "ERROR" in state or state == "FAILURE":
                raise SmartabaseError(
                    f"eventsimport {state}: {result.get('message')} {json.dumps(body)[:1000]}"
                )
            results.append({"count": len(batch), **result})
        return results
