"""把已解析的 SearchPlan 确定性编译为窄版 Java 请求。"""

from talent_agent_py.application.ports.talent_search import FieldValue, TalentSearchRequest
from talent_agent_py.domain.enums import ExperienceScope
from talent_agent_py.domain.plan import ResolvedEntity, SearchPlan
from talent_agent_py.settings import Settings


def _label_values(entities: list[ResolvedEntity]) -> list[FieldValue]:
    """业务实体只能使用 Java 返回的 code，不能回退到模型猜测值。"""

    return [FieldValue(type="LABEL", code=entity.code) for entity in entities]


def compile_search_request(
    plan: SearchPlan,
    settings: Settings,
    *,
    page: int = 1,
) -> TalentSearchRequest:
    """只编译 V1 白名单字段，并注入服务端控制的搜索策略。"""

    conditions = plan.conditions
    # 分页和检索策略由服务端注入，模型只能决定受支持的业务条件。
    request = TalentSearchRequest(
        currentPage=page,
        pageSize=settings.default_page_size,
        sortType=settings.default_sort_type,
        keyWordsMatchType=settings.default_keywords_match_type,
        inFlow=settings.default_in_flow,
        hideClue=settings.default_hide_clue,
    )

    if conditions.applicant_name:
        request.applicantName = conditions.applicant_name.value
        request.strictApplicantName = conditions.applicant_name.match_mode.value == "EXACT"
    if conditions.candidate_position:
        request.nowPosition = conditions.candidate_position.value
        request.onlyNowPosition = conditions.candidate_position.scope is ExperienceScope.CURRENT
    if conditions.minimum_degree:
        if not conditions.minimum_degree.resolved:
            raise ValueError("minimum_degree has not been resolved by Java")
        request.topDegree = conditions.minimum_degree.resolved.code
    if conditions.work_years:
        request.workYearsMin = conditions.work_years.minimum
        request.workYearsMax = conditions.work_years.maximum
    if conditions.company:
        request.nowCompany = _label_values(conditions.company.resolved)
        request.onlyNowCompany = conditions.company.scope is ExperienceScope.CURRENT
    if conditions.school:
        request.school = _label_values(conditions.school.resolved)
    if conditions.current_city:
        if not conditions.current_city.resolved:
            raise ValueError("current_city has not been resolved by Java")
        # 招聘接口对现居地要求整数编码，期望地则保留字符串编码。
        request.livePlace = [int(conditions.current_city.resolved.code)]
    if conditions.expected_city:
        if not conditions.expected_city.resolved:
            raise ValueError("expected_city has not been resolved by Java")
        request.expectWorkPlace = [conditions.expected_city.resolved.code]
    if conditions.school_level:
        request.schoolLevelList = _label_values(conditions.school_level.resolved)
        request.firstDegree = conditions.school_level.first_degree_only

    return request
