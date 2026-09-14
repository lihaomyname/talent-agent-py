"""测试使用的可预测 LLM 和 Java 适配器。"""

import asyncio

from talent_agent_py.application.ports.talent_search import (
    EntityCandidate,
    EntityResolution,
    EntityResolutionRequest,
    TalentSearchRequest,
    TalentSearchResponse,
)
from talent_agent_py.domain.conversation import CandidateCard, MessageRoute
from talent_agent_py.domain.enums import (
    EntityResolutionStatus,
    ExperienceScope,
    LocationScope,
    MessageType,
    PatchOperation,
    SupportedField,
)
from talent_agent_py.domain.plan import (
    ApplicantNameCondition,
    CompanyCondition,
    DegreeCondition,
    LocationCondition,
    PlanPatch,
    PlanPatchItem,
    PositionCondition,
    SchoolCondition,
    SchoolLevelCondition,
    SearchConditions,
    SearchPlanDraft,
    UnsupportedCondition,
    WorkYearsCondition,
)


class FakeLLMClient:
    """根据测试文本返回固定结构，不执行任何网络请求。"""

    def __init__(self, *, delay: float = 0) -> None:
        self.delay = delay
        self.classify_calls = 0
        self.parse_calls = 0
        self.patch_calls = 0

    async def classify_message(self, *, message, current_plan, has_pending_clarification):
        self.classify_calls += 1
        message_type = MessageType.SEARCH_PATCH if current_plan else MessageType.SEARCH_NEW
        return MessageRoute(
            message_type=message_type,
            affects_active_run=True,
            confidence=0.99,
            reason_code="FAKE_SEARCH",
        )

    async def parse_search_draft(self, *, messages):
        self.parse_calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        text = " ".join(messages)
        unsupported = []
        if "支付系统" in text:
            unsupported.append(UnsupportedCondition(
                original_text="支付系统经验",
                reason="V1不支持项目经验筛选",
            ))
        unresolved_location = None
        current_city = None
        expected_city = None
        if "杭州" in text:
            if "现居" in text:
                current_city = LocationCondition(name="杭州", scope=LocationScope.CURRENT_CITY)
            elif "期望" in text:
                expected_city = LocationCondition(name="杭州", scope=LocationScope.EXPECTED_CITY)
            else:
                unresolved_location = "杭州"
        return SearchPlanDraft(
            conditions=SearchConditions(
                applicant_name=ApplicantNameCondition(value="张三") if "张三" in text else None,
                candidate_position=PositionCondition(value="Java 后端") if "Java" in text else None,
                minimum_degree=DegreeCondition(value="本科") if "本科" in text else None,
                work_years=WorkYearsCondition(minimum=3, maximum=5) if "3到5年" in text else None,
                company=CompanyCondition(names=["网易"]) if "网易" in text else None,
                school=SchoolCondition(names=["浙江大学"]) if "浙江大学" in text else None,
                current_city=current_city,
                expected_city=expected_city,
                school_level=SchoolLevelCondition(labels=["985"]) if "985" in text else None,
            ),
            unresolved_location=unresolved_location,
            unsupported_conditions=unsupported,
        )

    async def parse_plan_patch(self, *, messages, current_plan):
        self.patch_calls += 1
        text = " ".join(messages)
        operations = []
        if "上海" in text:
            operations.append(PlanPatchItem(
                operation=PatchOperation.REPLACE,
                field=SupportedField.CURRENT_CITY,
                value={"name": "上海", "scope": "CURRENT_CITY", "resolved": None},
            ))
        if "5年以上" in text:
            operations.append(PlanPatchItem(
                operation=PatchOperation.REPLACE,
                field=SupportedField.WORK_YEARS,
                value={"minimum": 5, "maximum": None},
            ))
        if "当前职位" in text:
            existing = current_plan.conditions.candidate_position
            operations.append(PlanPatchItem(
                operation=PatchOperation.REPLACE,
                field=SupportedField.CANDIDATE_POSITION,
                value={
                    "value": existing.value if existing else "Java 后端",
                    "scope": ExperienceScope.CURRENT,
                },
            ))
        return PlanPatch(base_plan_version=current_plan.version, operations=operations)


class FakeTalentSearch:
    """为每个实体返回唯一 code，并返回一张脱敏人才卡。"""

    def __init__(self, *, delay: float = 0, empty: bool = False) -> None:
        self.delay = delay
        self.empty = empty
        self.resolve_calls = 0
        self.search_calls = 0
        self.last_request: TalentSearchRequest | None = None

    async def resolve_entities(self, requests: list[EntityResolutionRequest], user):
        self.resolve_calls += 1
        result = []
        for item in requests:
            code = {
                "DEGREE": "06",
                "COMPANY": "company-netease",
                "SCHOOL": "school-zju",
                "CITY": "310100" if item.text == "上海" else "330100",
                "SCHOOL_LEVEL": "school-level-985",
            }[item.kind.value]
            result.append(EntityResolution(
                key=item.key,
                kind=item.kind,
                status=EntityResolutionStatus.RESOLVED,
                candidates=[EntityCandidate(code=code, label=item.text)],
            ))
        return result

    async def search_candidates(self, request: TalentSearchRequest, user):
        self.search_calls += 1
        self.last_request = request
        if self.delay:
            await asyncio.sleep(self.delay)
        candidates = [] if self.empty else [CandidateCard(
            candidate_id="candidate-1",
            display_name="候选人A",
            headline="Java后端工程师",
            current_company="示例公司",
            current_city="杭州",
            highlights=["Java"],
        )]
        return TalentSearchResponse(candidates=candidates, total=len(candidates), has_next=False)
