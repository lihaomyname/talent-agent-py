"""IDE 单进程调试入口，兼容旧版 PyCharm 的 asyncio 补丁。"""

import asyncio

import uvicorn


def main() -> None:
    """运行本地服务，支持普通断点；退出时由 Runner 清理事件循环。"""

    config = uvicorn.Config(
        "talent_agent_py.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    # 旧版 PyCharm 替换的 asyncio.run 不接受 loop_factory。
    # 显式使用 Python 3.12 Runner 执行 serve，绕过 Server.run 的冲突入口。
    with asyncio.Runner() as runner:
        runner.run(server.serve())


if __name__ == "__main__":
    main()
