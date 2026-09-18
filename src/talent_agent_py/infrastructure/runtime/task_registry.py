"""V1 单进程会话任务注册表。"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import TypeVar

T = TypeVar("T")


class TaskRegistry:
    """保存每个会话当前任务，并提供尽力取消能力。"""

    def __init__(self) -> None:
        """初始化单进程的会话任务表和保护其更新的异步锁。"""

        # 会话 ID 到当前异步任务的映射，只存在当前进程。
        self._tasks: dict[str, asyncio.Task] = {}
        # 保护任务表替换与删除操作的异步锁。
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
                """先取消并等待原任务收尾，再运行替代任务并返回其结果。"""

                if previous is not None and not previous.done():
                    previous.cancel()
                    # 旧任务可能正在提交计划；必须等它完成受保护的数据库写入。
                    with suppress(asyncio.CancelledError):
                        await previous
                try:
                    return await operation_factory()
                finally:
                    # 结束即释放任务闭包中的本轮凭据，不缓存业务资料。
                    await self.remove(session_id, asyncio.current_task())

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

    async def has_capacity(self, session_id: str, maximum: int) -> bool:
        """只统计正在执行的会话；替换当前会话不占新名额。"""
        async with self._lock:
            active = {key for key, task in self._tasks.items() if not task.done()}
            return session_id in active or len(active) < maximum

    async def cancel_and_wait(self, session_id: str) -> None:
        """模式交接前等待旧任务必要提交；不持有任务表锁等待。"""
        async with self._lock:
            task = self._tasks.get(session_id)
            if task is not None and not task.done():
                task.cancel()
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def remove(self, session_id: str, task: asyncio.Task) -> None:
        """仅移除仍指向该任务的注册项，避免旧任务删除新任务。"""

        async with self._lock:
            if self._tasks.get(session_id) is task:
                self._tasks.pop(session_id, None)

    async def is_active(self, session_id: str, task: asyncio.Task) -> bool:
        """判断结果是否仍属于该会话的最新任务。"""

        async with self._lock:
            return self._tasks.get(session_id) is task
