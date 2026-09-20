"""让底层模型调用可以取得当前业务会话。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_session_id: ContextVar[str | None] = ContextVar("model_session_id", default=None)


def current_model_session_id() -> str | None:
    return _session_id.get()


@contextmanager
def model_session(session_id: str) -> Iterator[None]:
    """绑定当前会话，作用类似 Java 的 ThreadLocal。"""

    token = _session_id.set(session_id)
    try:
        yield
    finally:
        _session_id.reset(token)
