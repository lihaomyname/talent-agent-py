"""耗时节点统一取消包装器。"""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def interruptible(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """在外部调用前后响应取消，不干预已经开始的数据库保存。"""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        """包装异步调用以落实取消边界，返回原方法的结果。"""

        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        result = await func(*args, **kwargs)
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        return result

    return wrapper


def complete_before_cancel(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """收到取消信号后先完成关键写入，再把取消状态交还给上层。"""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # 独立任务配合 shield，避免父 Run 取消时中断已经开始的数据库事务。
        """包装异步调用以落实取消边界，返回原方法的结果。"""

        operation = asyncio.create_task(func(*args, **kwargs))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            # 等待事务提交或回滚完成，替代 Run 才能读取确定的最新计划。
            await asyncio.shield(operation)
            raise

    return wrapper
