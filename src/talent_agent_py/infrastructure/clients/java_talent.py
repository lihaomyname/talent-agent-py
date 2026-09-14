"""Java eTalent 内部接口适配器。"""

import httpx

from talent_agent_py.application.exceptions import (
    TalentSearchDeniedError,
    TalentSearchDependencyError,
)
from talent_agent_py.application.ports.talent_search import (
    EntityCandidate,
    EntityResolution,
    EntityResolutionRequest,
    TalentSearchPort,
    TalentSearchRequest,
    TalentSearchResponse,
)
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.domain.enums import EntityKind, EntityResolutionStatus
from talent_agent_py.settings import Settings


class JavaTalentClient(TalentSearchPort):
    """携带可信用户上下文调用 Java，Java 仍执行最终鉴权。"""

    # 来源：recruit-social 的 SocialDegreeTypeEnum；这里只做确定性的名称归一化。
    _DEGREE_CODES = {
        "大专": "05",
        "专科": "05",
        "本科": "06",
        "学士": "06",
        "研究生": "07",
        "硕士": "07",
        "MBA": "09",
        "博士": "10",
    }

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http_client
        self._settings = settings

    def _headers(self, user: UserContext) -> dict[str, str]:
        headers = {"X-Effective-User-Id": user.user_id, "X-Trace-Id": user.trace_id or ""}
        if user.tenant_id:
            headers["X-Tenant-Id"] = user.tenant_id
        if self._settings.java_service_token:
            headers["Authorization"] = (
                f"Bearer {self._settings.java_service_token.get_secret_value()}"
            )
        if user.auth_open_id_token:
            # 只允许把指定登录 Cookie 发往招聘域名，防止配置错误造成令牌泄漏。
            if self._http.base_url.host != self._settings.java_cookie_allowed_host:
                raise TalentSearchDependencyError("招聘 Cookie 的目标域名不在允许列表中")
            token = user.auth_open_id_token.get_secret_value()
            headers["Cookie"] = f"{self._settings.java_user_cookie_name}={token}"
        elif self._settings.java_requires_user_cookie:
            raise TalentSearchDeniedError("请求缺少招聘系统登录 Cookie")
        return headers

    async def _post(self, path: str, payload: object, user: UserContext) -> object:
        try:
            response = await self._http.post(path, json=payload, headers=self._headers(user))
        except httpx.HTTPError as exc:
            raise TalentSearchDependencyError("Java 人才服务网络异常") from exc

        return self._decode_response(response)

    async def _get(self, path: str, user: UserContext) -> object:
        """使用同一白名单 Cookie 调用招聘系统的字典读取接口。"""

        try:
            response = await self._http.get(path, headers=self._headers(user))
        except httpx.HTTPError as exc:
            raise TalentSearchDependencyError("Java 人才服务网络异常") from exc
        return self._decode_response(response)

    @staticmethod
    def _decode_response(response: httpx.Response) -> object:
        """统一处理 HTTP 状态和 recruit-social 的 Result<T> 包装。"""

        if response.status_code in {401, 403}:
            raise TalentSearchDeniedError("Java 拒绝当前用户访问")
        if 300 <= response.status_code < 400:
            raise TalentSearchDeniedError("招聘系统登录已失效，需要重新登录")
        if response.status_code >= 500:
            raise TalentSearchDependencyError("Java 人才服务暂时不可用")
        try:
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TalentSearchDependencyError("Java 人才服务响应无效") from exc

        # 兼容 recruit-social 的 Result<T> 包装，同时保留内部窄接口直返格式。
        if isinstance(body, dict) and "code" in body and "data" in body:
            code = body.get("code")
            if code in {401, 403}:
                raise TalentSearchDeniedError("招聘系统登录已失效或无人才库权限")
            if code != 200:
                raise TalentSearchDependencyError(
                    f"招聘系统返回业务错误：{body.get('msg') or code}"
                )
            return body.get("data")
        return body

    @staticmethod
    def _candidate_card(item: dict) -> "CandidateCard":
        """把宽版 TalentResumeVO 收敛为不含联系方式的安全候选人卡片。"""

        from talent_agent_py.domain.conversation import CandidateCard

        raw_id = item.get("id") or item.get("applicantId")
        if raw_id is None:
            raise TalentSearchDependencyError("招聘接口返回的候选人缺少标识")
        highlights: list[str] = []
        for label in item.get("labelList") or []:
            if not isinstance(label, dict):
                continue
            value = label.get("name") or label.get("labelName") or label.get("value")
            if value and str(value) not in highlights:
                highlights.append(str(value))
            if len(highlights) >= 20:
                break
        return CandidateCard(
            candidate_id=str(raw_id),
            display_name=item.get("applicantName"),
            headline=item.get("nowPosition"),
            current_company=item.get("nowCompany"),
            current_city=item.get("livePlaceName"),
            highlights=highlights,
        )

    async def resolve_entities(
        self, requests: list[EntityResolutionRequest], user: UserContext
    ) -> list[EntityResolution]:
        if self._settings.java_direct_browser_api:
            return await self._resolve_browser_entities(requests, user)
        payload = {"entities": [item.model_dump(mode="json") for item in requests]}
        data = await self._post(self._settings.java_resolve_path, payload, user)
        if not isinstance(data, dict):
            raise TalentSearchDependencyError("Java 实体解析响应格式错误")
        return [
            EntityResolution.model_validate(item, strict=False)
            for item in data.get("entities", [])
        ]

    async def _resolve_browser_entities(
        self,
        requests: list[EntityResolutionRequest],
        user: UserContext,
    ) -> list[EntityResolution]:
        """复用现有字典和文本搜索语义，替代尚未建设的内部解析接口。"""

        city_items: list[dict] = []
        if any(item.kind is EntityKind.CITY for item in requests):
            city_data = await self._get(self._settings.java_city_options_path, user)
            if not isinstance(city_data, dict):
                raise TalentSearchDependencyError("招聘城市字典响应格式错误")
            city_items = [
                option
                for group in city_data.values()
                if isinstance(group, list)
                for option in group
                if isinstance(option, dict)
            ]

        results: list[EntityResolution] = []
        for item in requests:
            candidates: list[EntityCandidate] = []
            if item.kind is EntityKind.DEGREE:
                code = self._DEGREE_CODES.get(item.text.strip())
                if code:
                    candidates.append(EntityCandidate(code=code, label=item.text.strip()))
            elif item.kind is EntityKind.CITY:
                candidates.extend(
                    EntityCandidate(code=str(option["id"]), label=str(option["name"]))
                    for option in city_items
                    if str(option.get("name", "")).strip() == item.text.strip()
                    and option.get("id") is not None
                )
            else:
                # TalentController 会把 TEXT 名称转换为公司、学校或院校级别标签。
                candidates.append(EntityCandidate(code=item.text.strip(), label=item.text.strip()))

            status = (
                EntityResolutionStatus.RESOLVED
                if len(candidates) == 1
                else EntityResolutionStatus.AMBIGUOUS
                if len(candidates) > 1
                else EntityResolutionStatus.NOT_FOUND
            )
            results.append(EntityResolution(
                key=item.key,
                kind=item.kind,
                status=status,
                candidates=candidates,
            ))
        return results

    async def search_candidates(
        self, request: TalentSearchRequest, user: UserContext
    ) -> TalentSearchResponse:
        data = await self._post(
            self._settings.java_search_path,
            request.model_dump(mode="json", exclude_none=True),
            user,
        )
        if isinstance(data, dict) and "list" in data:
            # 浏览器人才库接口返回 PageResult<TalentResumeVO>。
            items = data.get("list") or []
            if not isinstance(items, list):
                raise TalentSearchDependencyError("招聘接口分页列表格式错误")
            candidates = [
                self._candidate_card(item)
                for item in items
                if isinstance(item, dict)
            ]
            last_page = data.get("lastPage", data.get("isLastPage"))
            if last_page is None:
                last_page = request.currentPage >= int(data.get("pages") or 0)
            return TalentSearchResponse(
                candidates=candidates,
                total=int(data.get("total") or 0),
                has_next=not bool(last_page),
            )
        return TalentSearchResponse.model_validate(data, strict=False)
