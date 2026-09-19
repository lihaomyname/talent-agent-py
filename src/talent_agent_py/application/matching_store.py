"""会话归属查询。"""

from talent_agent_py.application.exceptions import SessionNotFoundError


async def owned_session(uow, session_id, user):
    """读取当前用户拥有的会话；不存在时统一返回业务错误。"""

    session = await uow.sessions.get_owned(session_id, user.user_id)
    if session is None:
        raise SessionNotFoundError("会话不存在")
    return session
