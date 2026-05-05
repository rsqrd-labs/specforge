from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await _send_too_large(send)
            return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                await self.app(scope, _replay([message]), send)
                return

            chunk = message.get("body", b"")
            body.extend(chunk)
            if len(body) > self.max_body_bytes:
                await _send_too_large(send)
                return
            more_body = bool(message.get("more_body", False))

        await self.app(
            scope,
            _replay(
                [
                    {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                ]
            ),
            send,
        )


def _content_length(scope: Scope) -> int | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() != b"content-length":
            continue
        try:
            return int(raw_value)
        except ValueError:
            return None
    return None


def _replay(messages: list[Message]) -> Callable[[], Awaitable[Message]]:
    async def receive() -> Message:
        if messages:
            return messages.pop(0)
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    return receive


async def _send_too_large(send: Send) -> None:
    body = json.dumps({"detail": "Request body too large"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
