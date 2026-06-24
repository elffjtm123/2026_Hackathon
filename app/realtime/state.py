import json
import time
from typing import Any
from uuid import UUID

from redis.asyncio import Redis


class SessionStateStore:
    def __init__(self, redis_url: str | None) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        self.memory: dict[UUID, dict[str, Any]] = {}
        self.rate_counters: dict[tuple[UUID, int], int] = {}

    async def set(self, session_id: UUID, value: dict[str, Any]) -> None:
        self.memory[session_id] = value
        if self.redis:
            await self.redis.setex(f"session:{session_id}:state", 3600, json.dumps(value))

    async def get(self, session_id: UUID) -> dict[str, Any] | None:
        if self.redis:
            raw = await self.redis.get(f"session:{session_id}:state")
            if raw:
                return json.loads(raw)
        return self.memory.get(session_id)

    async def delete(self, session_id: UUID) -> None:
        self.memory.pop(session_id, None)
        if self.redis:
            await self.redis.delete(f"session:{session_id}:state")

    async def ping(self) -> bool:
        if not self.redis:
            return True
        return bool(await self.redis.ping())

    async def allow_realtime_message(self, user_id: UUID, limit: int) -> bool:
        second = int(time.time())
        if self.redis:
            key = f"rate:realtime:{user_id}:{second}"
            async with self.redis.pipeline(transaction=True) as pipe:
                count, _ = await pipe.incr(key).expire(key, 2).execute()
            return int(count) <= limit
        counter_key = (user_id, second)
        self.rate_counters[counter_key] = self.rate_counters.get(counter_key, 0) + 1
        if len(self.rate_counters) > 1_000:
            self.rate_counters = {
                key: value for key, value in self.rate_counters.items() if key[1] >= second - 1
            }
        return self.rate_counters[counter_key] <= limit

    async def close(self) -> None:
        if self.redis:
            await self.redis.aclose()
