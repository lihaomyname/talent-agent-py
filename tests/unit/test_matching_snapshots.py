import pytest

from talent_agent_py.application.matching_snapshots import (
    SnapshotVersionError,
    read_search_plan,
    read_snapshot,
    snapshot_kind,
)
from talent_agent_py.domain.matching import MatchingPlanSnapshot, OwnerScope, SearchRequirements
from talent_agent_py.domain.plan import SearchConditions, SearchPlan
from talent_agent_py.settings import Settings


def test_old_and_new_plans_share_compiler_projection():
    plan = SearchPlan(version=1, applied_through_message_seq=1, conditions=SearchConditions())
    snapshot = MatchingPlanSnapshot(
        owner_scope=OwnerScope(session_id="s", user_id="u"),
        requirements=SearchRequirements(), search_plan=plan,
    )
    assert read_search_plan(plan.model_dump(mode="json")) == plan
    assert read_search_plan(snapshot.model_dump(mode="json")) == plan
    assert read_snapshot(snapshot.model_dump(mode="json")) == snapshot


def test_unknown_version_is_not_treated_as_legacy():
    with pytest.raises(SnapshotVersionError):
        read_search_plan({"schema_version": 99})


@pytest.mark.parametrize("kind", ["RESULT", "CHAT", "ENTITY_AMBIGUITY", "LOCATION_SCOPE"])
def test_legacy_business_kind_is_not_a_snapshot_discriminator(kind):
    assert snapshot_kind({"kind": kind}) is None


def test_matching_kind_requires_explicit_version():
    with pytest.raises(SnapshotVersionError):
        snapshot_kind({"kind": "matching_run"})


def test_matching_defaults_and_limits():
    settings = Settings(_env_file=None)
    assert settings.enable_matching is False
    assert settings.matching_target == 10
    assert settings.matching_max_pages == 5
    with pytest.raises(ValueError):
        Settings(_env_file=None, matching_batch_size=6)
