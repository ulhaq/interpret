"""Realtime events: tell a signed-in user's open app tabs that something changed.

Publishers - the API or the worker - call `publish_to_user` inside their
transaction; the event goes out only after it commits, so a rolled-back write
never announces itself. The app's event stream (`GET /v1/events`) subscribes
to the user's channel and forwards their events as Server-Sent Events.

Delivery is best effort: an event published while nobody listens, or while the
broker is unreachable, is gone. So events are hints ("your notifications
changed"), not data - the database stays the source of truth, and a client
re-fetches what it shows whenever its stream (re)connects or it receives
`RESYNC` (it may have missed events).

The broker is chosen by `REDIS_URL`:

- `RedisBroker`: publishes through Redis pub/sub, so an event from the worker
  or another API replica reaches every API process. Each process keeps one
  Redis subscription and fans events out to its local streams.
- `LocalBroker` (no `REDIS_URL` - local dev and tests): in-process only, so
  events the worker publishes don't reach the API.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession
lazy from redis.asyncio import Redis
lazy from redis.exceptions import ConnectionError as RedisConnectionError

from src.foundation.core.config import settings
from src.foundation.core.database import after_commit

log = logging.getLogger(__name__)

# Events a subscriber may have queued before it falls behind; past that its
# queue is replaced by a single `RESYNC`.
_SUBSCRIBER_BUFFER = 100
_REDIS_CHANNEL_PREFIX = "realtime:"
_RELAY_MAX_BACKOFF_SECONDS = 30
# How long a new subscription waits for the Redis relay to be listening.
_RELAY_READY_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class RealtimeEvent:
    """``type`` names what changed; ``organization_id`` limits the event to
    streams opened in that organization (None: every stream of the user);
    ``data`` is a small JSON-serializable hint, never personal data."""

    type: str
    organization_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.type,
                "organization_id": self.organization_id,
                "data": self.data,
            },
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> RealtimeEvent:
        value = json.loads(raw)
        return cls(
            type=value["type"],
            organization_id=value.get("organization_id"),
            data=value.get("data") or {},
        )


# Sent to a subscriber that may have missed events (it fell behind, or the
# broker reconnected): the client re-fetches instead of trusting its state.
RESYNC = RealtimeEvent(type="resync")


def user_channel(user_id: int) -> str:
    return f"user:{user_id}"


class Subscription:
    """The events published on one channel since subscribing."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(_SUBSCRIBER_BUFFER)

    async def next(self, wait: float) -> RealtimeEvent | None:
        """The next event, or None if none arrives within ``wait`` seconds."""
        try:
            return await asyncio.wait_for(self._queue.get(), wait)
        except TimeoutError:
            return None

    def _put(self, event: RealtimeEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # A stalled reader: drop what it hasn't read and have it re-sync.
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait(RESYNC)


class _Fanout:
    """This process's subscriptions, by channel."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, set[Subscription]] = {}

    @contextlib.contextmanager
    def subscribe(self, channel: str) -> Generator[Subscription]:
        subscription = Subscription()
        self._subscriptions.setdefault(channel, set()).add(subscription)
        try:
            yield subscription
        finally:
            subscribers = self._subscriptions[channel]
            subscribers.discard(subscription)
            if not subscribers:
                del self._subscriptions[channel]

    def dispatch(self, channel: str, event: RealtimeEvent) -> None:
        for subscription in self._subscriptions.get(channel, ()):
            subscription._put(event)  # noqa: SLF001 - the fanout owns delivery

    def broadcast(self, event: RealtimeEvent) -> None:
        for subscribers in self._subscriptions.values():
            for subscription in subscribers:
                subscription._put(event)  # noqa: SLF001


class Broker(Protocol):
    async def publish(self, channel: str, event: RealtimeEvent) -> None: ...

    def subscribe(
        self,
        channel: str,
    ) -> contextlib.AbstractAsyncContextManager[Subscription]: ...

    async def close(self) -> None: ...


class LocalBroker:
    """Delivers events within this process only."""

    def __init__(self) -> None:
        self._fanout = _Fanout()

    async def publish(self, channel: str, event: RealtimeEvent) -> None:
        self._fanout.dispatch(channel, event)

    @contextlib.asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncGenerator[Subscription]:
        with self._fanout.subscribe(channel) as subscription:
            yield subscription

    async def close(self) -> None:
        pass


class RedisBroker:
    """Publishes through Redis; one relay task per process (started by the
    first subscription, so a process that only publishes - the worker - never
    subscribes) receives every event and hands it to the local subscribers of
    its channel. Pattern-subscribing once keeps the relay free of per-stream
    subscribe/unsubscribe commands; events are rare and small, so receiving
    other processes' users' events too costs little."""

    def __init__(self, url: str) -> None:
        self._redis = Redis.from_url(url, health_check_interval=30)
        self._fanout = _Fanout()
        self._relay: asyncio.Task[None] | None = None
        self._listening = asyncio.Event()

    async def publish(self, channel: str, event: RealtimeEvent) -> None:
        await self._redis.publish(_REDIS_CHANNEL_PREFIX + channel, event.to_json())

    @contextlib.asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncGenerator[Subscription]:
        if self._relay is None or self._relay.done():
            self._relay = asyncio.create_task(self._run_relay(), name="realtime-relay")
        with self._fanout.subscribe(channel) as subscription:
            # Don't let the caller assume it's listening before the relay is;
            # if Redis is down, go on - the relay re-syncs it on reconnect.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._listening.wait(),
                    _RELAY_READY_TIMEOUT_SECONDS,
                )
            yield subscription

    async def close(self) -> None:
        if self._relay is not None:
            self._relay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._relay
        await self._redis.aclose()

    async def _run_relay(self) -> None:
        backoff = 1
        reconnecting = False
        while True:
            try:
                async with self._redis.pubsub() as pubsub:
                    await pubsub.psubscribe(f"{_REDIS_CHANNEL_PREFIX}*")
                    self._listening.set()
                    if reconnecting:
                        # Events published while disconnected are lost.
                        self._fanout.broadcast(RESYNC)
                    backoff = 1
                    async for message in pubsub.listen():
                        self._relay_message(message)
            except asyncio.CancelledError:
                raise
            except RedisConnectionError as exc:
                log.warning(
                    "Realtime relay lost Redis (%s); retry in %ss", exc, backoff
                )
            except Exception:
                log.exception("Realtime relay failed; retry in %ss", backoff)
            self._listening.clear()
            reconnecting = True
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RELAY_MAX_BACKOFF_SECONDS)

    def _relay_message(self, message: dict[str, Any]) -> None:
        if message["type"] != "pmessage":
            return
        channel = message["channel"].decode().removeprefix(_REDIS_CHANNEL_PREFIX)
        try:
            event = RealtimeEvent.from_json(message["data"])
        except ValueError, KeyError, TypeError:
            log.warning("Dropped a malformed realtime event on %s", channel)
            return
        self._fanout.dispatch(channel, event)


_broker: Broker | None = None


def broker() -> Broker:
    """This process's broker, created on first use from `REDIS_URL`."""
    global _broker  # noqa: PLW0603 - the process-wide broker
    if _broker is None:
        _broker = (
            RedisBroker(settings.redis_url) if settings.redis_url else LocalBroker()
        )
    return _broker


def install_broker(new: Broker) -> None:
    """Use ``new`` as this process's broker (tests)."""
    global _broker  # noqa: PLW0603
    _broker = new


async def close_broker() -> None:
    """Close the broker at process shutdown."""
    global _broker  # noqa: PLW0603
    if _broker is not None:
        await _broker.close()
        _broker = None


async def _publish(channel: str, event: RealtimeEvent) -> None:
    try:
        await broker().publish(channel, event)
    except Exception:  # never fails the publisher
        # Best effort: the client re-syncs from the database.
        log.warning("Could not publish realtime event %s", event.type, exc_info=True)


def publish_to_user(session: AsyncSession, user_id: int, event: RealtimeEvent) -> None:
    """Send ``event`` to ``user_id``'s open event streams once ``session``'s
    transaction commits (dropped if it rolls back)."""
    channel = user_channel(user_id)
    after_commit(session, lambda: _publish(channel, event))
