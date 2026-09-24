import json
from collections.abc import Callable
from typing import Any

import pytest


class FakeResponse:
    def __init__(self, body: Any = None, status: int = 200) -> None:
        self.status = status
        self.ok = 200 <= status < 300
        self._text = body if isinstance(body, str) else json.dumps(body if body is not None else {})

    async def text(self) -> str:
        return self._text


class FakeFetch:
    """Records requests and answers them from a handler keyed on endpoint name."""

    def __init__(self, handler: Callable[[str, dict], FakeResponse]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, url: str, *, method: str, headers: dict, body: str) -> FakeResponse:
        endpoint = url.split("/api/v1/")[1].split("?")[0]
        payload = json.loads(body)
        self.calls.append((endpoint, payload))
        return self.handler(endpoint, payload)


@pytest.fixture
def make_fetch() -> Callable[..., FakeFetch]:
    return FakeFetch
