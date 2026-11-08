"""Server-sent events: the event format, a hub of connected clients, and the
response that streams to one of them. server/stream/stream.go is the same
thing for the Go template.

No library: the format is a few lines of text, and writing it here is also
where data is kept from forging a field (event()).

A hub fans one event out to its clients. Each client has a small queue, and an
event that does not fit is dropped rather than waited for, so one stalled
browser costs itself an update and costs the sender nothing. That suits what
goes through here, which says "something changed" and not what: the next one
says the same thing. A hub takes a limited number of clients, because an open
stream holds a connection for as long as it lives.

An open stream is also a request that was authorised once, possibly hours ago.
So every tick it is asked again, and ends when the answer is no.

Everything but publish_from_thread runs on the event loop.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable, Sequence

from starlette.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send

CLIENT_QUEUE_SIZE = 16
MAX_CLIENTS = 8
# One tick for the heartbeat and the auth re-check. A proxy that gives up on a
# quiet connection usually does so after 30 to 60 seconds.
TICK_SECONDS = 15.0
# uvicorn has no write timeout, so a client that stops reading would otherwise
# hold a slot, and hold up shutdown, for as long as the socket stays open.
SEND_TIMEOUT_SECONDS = 30.0
RETRY_MS = 5000

# Set as a raw header: StreamingResponse's media_type would add a charset.
HEADERS = {
    "content-type": "text/event-stream",
    "cache-control": "no-store",
    # nginx buffers responses unless told not to, and a buffered stream is a
    # stream that arrives all at once when it ends.
    "x-accel-buffering": "no",
}


def event(name: str, data: str) -> bytes:
    """One event. A line break in data becomes the next data: line, which is
    what the format says a line break is, so data can never start a line of
    its own; one in the name is removed for the same reason."""
    name = name.replace("\r", "").replace("\n", "")
    lines = data.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return f"event: {name}\n".encode("utf-8") + "".join(f"data: {line}\n" for line in lines).encode("utf-8") + b"\n"


def retry(milliseconds: int) -> bytes:
    return f"retry: {milliseconds}\n\n".encode("ascii")


CHANGED = event("changed", "1")
PING = b": ping\n\n"


class Client:
    def __init__(self) -> None:
        # None means the hub has closed: stop.
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE)

    def offer(self, message: bytes) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            pass

    def close(self) -> None:
        """Make room if it has to: this one message is never dropped."""
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(None)


class Hub:
    def __init__(self, max_clients: int = MAX_CLIENTS) -> None:
        self.max_clients = max_clients
        self.clients: set[Client] = set()
        self.closed = False
        # Replaced in tests.
        self.tick_seconds = TICK_SECONDS
        self.send_timeout_seconds = SEND_TIMEOUT_SECONDS

    def join(self) -> Client | None:
        """A slot, or None when there is none to give."""
        if self.closed or len(self.clients) >= self.max_clients:
            return None
        client = Client()
        self.clients.add(client)
        return client

    def leave(self, client: Client) -> None:
        self.clients.discard(client)

    def publish(self, message: bytes) -> None:
        for client in self.clients:
            client.offer(message)

    def close(self) -> None:
        """End every stream. Part of stopping the server, so that an open one
        does not use up the graceful timeout."""
        self.closed = True
        for client in self.clients:
            client.close()


def publish_from_thread(loop: asyncio.AbstractEventLoop, hub: Hub, message: bytes) -> None:
    """Hub.publish for a thread that is not the event loop's. A loop already
    closed means the server is on its way out, and nobody is listening."""
    try:
        loop.call_soon_threadsafe(hub.publish, message)
    except RuntimeError:
        pass


class EventStream(StreamingResponse):
    """The response for one client of a hub. allowed is asked every tick, and
    the stream ends on False, or on an exception: unable to tell, the safe
    answer is no. The browser reconnects, and meets the guards again.

    The slot is freed in a finally around __call__, not inside the generator:
    when a client goes away Starlette cancels the send, and a generator
    suspended there can be left unfinished, so its own finally is not a
    promise. __call__ always returns."""

    def __init__(
        self,
        hub: Hub,
        client: Client,
        allowed: Callable[[], Awaitable[bool]],
        opening: Sequence[bytes] = (),
    ) -> None:
        self.hub = hub
        self.client = client
        self.allowed = allowed
        self.opening = opening
        super().__init__(self._events(), headers=HEADERS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_or_give_up(message: Message) -> None:
            async with asyncio.timeout(self.hub.send_timeout_seconds):
                await send(message)

        try:
            await super().__call__(scope, receive, send_or_give_up)
        except TimeoutError:
            # Returning with the response unfinished makes uvicorn drop the
            # connection, which is what a client that stopped reading gets.
            pass
        finally:
            self.hub.leave(self.client)

    async def _events(self) -> AsyncIterator[bytes]:
        for message in self.opening:
            yield message
        loop = asyncio.get_running_loop()
        next_tick = loop.time() + self.hub.tick_seconds
        while True:
            # Checked before reading the queue, not by a timeout alone: get()
            # on a queue with something in it returns without ever letting a
            # timeout fire, so a busy stream would never be re-checked.
            remaining = next_tick - loop.time()
            if remaining <= 0:
                try:
                    if not await self.allowed():
                        return
                except Exception as error:  # noqa: BLE001 -- see the class docstring
                    print(f"[stream] re-check failed: {error!r}", flush=True)
                    return
                yield PING
                next_tick = loop.time() + self.hub.tick_seconds
                continue
            try:
                async with asyncio.timeout(remaining):
                    message = await self.client.queue.get()
            except TimeoutError:
                continue
            if message is None:
                return
            yield message
