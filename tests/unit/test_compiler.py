"""Java 窄版请求编译测试。"""

from talent_agent_py.application.search_compiler import compile_search_request
from talent_agent_py.domain.enums import ExperienceScope, LocationScope
from talent_agent_py.domain.plan import (
    CompanyCondition,
    DegreeCondition,
    LocationCondition,
    PositionCondition,
    ResolvedEntity,
    SchoolCondition,
    SchoolLevelCondition,
    SearchConditions,
    SearchPlan,
    WorkYearsCondition,
)
from talent_agent_py.settings import Settings


def test_compiler_maps_degree_years_position_and_city():
    plan = SearchPlan(
        version=1,
        applied_through_message_seq=1,
        conditions=SearchConditions(
            candidate_position=PositionCondition(
                value="Java 后端", scope=ExperienceScope.CURRENT
            ),
            minimum_degree=DegreeCondition(
                value="本科", resolved=ResolvedEntity(code="06", label="本科")
            ),
            work_years=WorkYearsCondition(minimum=3, maximum=5),
            current_city=LocationCondition(
                name="杭州",
                scope=LocationScope.CURRENT_CITY,
                resolved=ResolvedEntity(code="330100", label="杭州"),
            ),
        ),
    )
    request = compile_search_request(plan, Settings())
    assert request.topDegree == "06"
    assert request.workYearsMin == 3
    assert request.workYearsMax == 5
    assert request.onlyNowPosition is True
    assert request.livePlace == [330100]
    assert "workYears" not in request.model_dump()


def test_compiler_keeps_company_school_multi_values_as_labels():
    plan = SearchPlan(
        version=1,
        applied_through_message_seq=1,
        conditions=SearchConditions(
            company=CompanyCondition(
                names=["网易", "有道"],
                resolved=[
                    ResolvedEntity(code="company-1", label="网易"),
                    ResolvedEntity(code="company-2", label="有道"),
                ],
            ),
            school=SchoolCondition(
                names=["浙江大学"],
                resolved=[ResolvedEntity(code="school-1", label="浙江大学")],
            ),
            school_level=SchoolLevelCondition(
                labels=["985"],
                resolved=[ResolvedEntity(code="level-985", label="985")],
                first_degree_only=True,
            ),
        ),
    )
    request = compile_search_request(plan, Settings())
    assert [item.code for item in request.nowCompany] == ["company-1", "company-2"]
    assert request.school[0].code == "school-1"
    assert request.schoolLevelList[0].code == "level-985"
    assert request.firstDegree is True
