"""节点统一取消装饰器测试。"""

import asyncio

import pytest

from talent_agent_py.orchestration.interruptible import complete_before_cancel, interruptible


async def test_interruptible_propagates_task_cancellation():
    @interruptible
    async def slow_node():
        await asyncio.sleep(10)

    task = asyncio.create_task(slow_node())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_critical_save_finishes_before_cancellation_is_propagated():
    """模拟保存中收到新消息，验证关键写入不会被半途撤销。"""

    started = asyncio.Event()
    finished = asyncio.Event()

    @complete_before_cancel
    async def save_plan() -> None:
        started.set()
        await asyncio.sleep(0.02)
        finished.set()

    task = asyncio.create_task(save_plan())
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
