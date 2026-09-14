"""持久化和未处理消息边界测试。"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from talent_agent_py.domain.enums import LocationScope
from talent_agent_py.domain.plan import LocationCondition, SearchConditions, SearchPlan
from talent_agent_py.infrastructure.persistence.models import Base
from talent_agent_py.infrastructure.persistence.unit_of_work import UnitOfWork


async def test_plan_tracks_applied_message_sequence_and_loads_later_messages():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with UnitOfWork(factory) as uow:
        session = await uow.sessions.create("user-1")
        first, _ = await uow.messages.append_user(session.id, "m1", "找杭州的人")
        first.route_type = "SEARCH_NEW"
        await uow.plans.save(session, SearchPlan(
            version=1,
            applied_through_message_seq=first.sequence,
            conditions=SearchConditions(current_city=LocationCondition(
                name="杭州", scope=LocationScope.CURRENT_CITY
            )),
        ))
        second, _ = await uow.messages.append_user(session.id, "m2", "改成上海")
        second.route_type = "SEARCH_PATCH"

    async with UnitOfWork(factory) as uow:
        plan = await uow.plans.get_current(session.id)
        messages = await uow.messages.list_after(session.id, plan.applied_through_message_seq)
        assert [message.content for message in messages] == ["改成上海"]

    await engine.dispose()
