import asyncio
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class QueueStats:
    dropped: int = 0


class DropOldestQueue(Generic[T]):
    def __init__(self, maxsize: int) -> None:
        self.queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)
        self.stats = QueueStats()

    def put_latest(self, item: T) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            self.queue.task_done()
            self.stats.dropped += 1
        self.queue.put_nowait(item)

    async def get(self) -> T:
        return await self.queue.get()

    def task_done(self) -> None:
        self.queue.task_done()

    def qsize(self) -> int:
        return self.queue.qsize()
