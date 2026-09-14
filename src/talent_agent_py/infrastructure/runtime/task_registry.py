"""V1 单进程会话任务注册表。"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import TypeVar

T = TypeVar("T")


class TaskRegistry:
    """保存每个会话当前任务，并提供尽力取消能力。"""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def replace(self, session_id: str, task: asyncio.Task) -> asyncio.Task | None:
        """注册新任务并返回旧任务，由调用方决定是否取消。"""

        async with self._lock:
            old = self._tasks.get(session_id)
            self._tasks[session_id] = task
            return old

    async def start_replacement(
        self,
        session_id: str,
        operation_factory: Callable[[], Awaitable[T]],
    ) -> asyncio.Task[T]:
        """取消并等待旧任务收尾，再启动同一会话的新任务。"""

        async with self._lock:
            previous = self._tasks.get(session_id)

            async def run_in_order() -> T:
                if previous is not None and not previous.done():
                    previous.cancel()
                    # 旧任务可能正在提交计划；必须等它完成受保护的数据库写入。
                    with suppress(asyncio.CancelledError):
                        await previous
                return await operation_factory()

            task = asyncio.create_task(run_in_order())
            self._tasks[session_id] = task
            return task

    async def cancel(self, session_id: str) -> bool:
        """尝试取消当前任务；上游服务可能仍会继续完成请求。"""

        async with self._lock:
            task = self._tasks.get(session_id)
            if task is None or task.done():
                return False
            task.cancel()
            return True

    async def remove(self, session_id: str, task: asyncio.Task) -> None:
        """仅移除仍指向该任务的注册项，避免旧任务删除新任务。"""

        async with self._lock:
            if self._tasks.get(session_id) is task:
                self._tasks.pop(session_id, None)

    async def is_active(self, session_id: str, task: asyncio.Task) -> bool:
        """判断结果是否仍属于该会话的最新任务。"""

        async with self._lock:
            return self._tasks.get(session_id) is task
