"""在固定条件搜索之后，按偏好循环检查候选人资料。"""

import asyncio

from talent_agent_py.application.candidate_profiles import (
    evaluation_rank,
    failed_evaluation,
    validate_evaluation,
)
from talent_agent_py.application.exceptions import ModelOutputError
from talent_agent_py.application.ports.talent_search import (
    TalentSearchPort,
    TalentSearchRequest,
    TalentSearchResponse,
)
from talent_agent_py.domain.conversation import PreferenceEvidenceView, UserContext
from talent_agent_py.domain.plan import Preference
from talent_agent_py.infrastructure.clients.matching_llm import MatchingLLMClient
from talent_agent_py.settings import Settings


class PreferenceMatcher:
    """有偏好时才启用；无偏好时原搜索流程完全不经过这里。"""

    def __init__(
        self,
        talent_search: TalentSearchPort,
        llm: MatchingLLMClient,
        settings: Settings,
    ) -> None:
        self._talent_search = talent_search
        self._llm = llm
        self._settings = settings

    async def match(
        self,
        request: TalentSearchRequest,
        preferences: tuple[Preference, ...],
        user: UserContext,
    ) -> TalentSearchResponse:
        """逐页寻找命中偏好的人，达到人数或预算后停止。"""

        matched = []
        checked_ids: set[str] = set()
        model_attempts = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.matching_deadline_seconds

        for page in range(1, self._settings.matching_max_pages + 1):
            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                break
            page_request = request.model_copy(update={"currentPage": page})
            try:
                async with asyncio.timeout(remaining_seconds):
                    profile_page = await self._talent_search.search_candidate_profiles(
                        page_request, user
                    )
            except TimeoutError:
                break
            profiles = [
                profile
                for profile in profile_page.candidates
                if profile.candidate_id not in checked_ids
            ]
            for start in range(0, len(profiles), self._settings.matching_batch_size):
                if len(checked_ids) >= self._settings.matching_max_candidates:
                    break
                batch = profiles[start : start + self._settings.matching_batch_size]
                remaining = self._settings.matching_max_candidates - len(checked_ids)
                batch = batch[:remaining]
                evaluations = None
                for _ in range(2):
                    remaining_seconds = deadline - loop.time()
                    if (
                        remaining_seconds <= 0
                        or model_attempts >= self._settings.matching_max_model_attempts
                    ):
                        break
                    model_attempts += 1
                    try:
                        async with asyncio.timeout(remaining_seconds):
                            result = await self._llm.evaluate(preferences, batch)
                        by_id = {item.candidate_id: item for item in result.evaluations}
                        if len(by_id) != len(batch):
                            raise ValueError("批次人选数量不一致")
                        for profile in batch:
                            validate_evaluation(by_id[profile.candidate_id], profile, preferences)
                        evaluations = by_id
                        break
                    except TimeoutError:
                        break
                    except (ModelOutputError, ValueError, KeyError):
                        continue
                if evaluations is None:
                    evaluations = {
                        profile.candidate_id: failed_evaluation(profile, preferences)
                        for profile in batch
                    }

                preference_by_id = {item.id: item for item in preferences}
                for profile in batch:
                    checked_ids.add(profile.candidate_id)
                    evaluation = evaluations[profile.candidate_id]
                    rank = evaluation_rank(evaluation, preferences)
                    if not rank[0]:
                        continue
                    evidence_views = []
                    for evidence in evaluation.evidence:
                        if evidence.status not in {"SUPPORTED", "PARTIAL"}:
                            continue
                        preference = preference_by_id[evidence.criterion_id]
                        evidence_views.append(
                            PreferenceEvidenceView(
                                preference_id=preference.id,
                                preference=preference.description,
                                status=evidence.status,
                                explanation=evidence.explanation,
                                quote=evidence.quote,
                            )
                        )
                    card = profile.card.model_copy(
                        update={
                            "preference_evidence": evidence_views,
                        }
                    )
                    matched.append((card, rank[2], rank[3]))

            matched.sort(key=lambda item: (-item[1], -item[2]))
            if len(matched) >= self._settings.matching_target:
                break
            if not profile_page.has_next:
                break
            if len(checked_ids) >= self._settings.matching_max_candidates:
                break

        cards = [item[0] for item in matched[: self._settings.matching_target]]
        return TalentSearchResponse(candidates=cards, total=len(cards), has_next=False)
