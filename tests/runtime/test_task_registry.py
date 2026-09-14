"""进程内任务取消行为测试。"""

import asyncio

import pytest

from talent_agent_py.infrastructure.runtime.task_registry import TaskRegistry


async def test_registry_cancels_active_task():
    registry = TaskRegistry()
    task = asyncio.create_task(asyncio.sleep(10))
    await registry.replace("session-1", task)

    assert await registry.cancel("session-1") is True
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_replacement_waits_for_previous_cleanup():
    """新任务必须在旧任务处理完取消收尾后再开始。"""

    registry = TaskRegistry()
    cleanup_finished = asyncio.Event()
    replacement_started = asyncio.Event()

    async def previous_operation():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            cleanup_finished.set()
            raise

    previous = asyncio.create_task(previous_operation())
    await registry.replace("session-1", previous)

    async def replacement_operation():
        assert cleanup_finished.is_set()
        replacement_started.set()
        return "完成"

    replacement = await registry.start_replacement(
        "session-1", replacement_operation
    )
    assert await replacement == "完成"
    assert replacement_started.is_set()
