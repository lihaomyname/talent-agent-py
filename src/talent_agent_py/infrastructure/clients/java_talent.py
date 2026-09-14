"""Java eTalent 内部接口适配器。"""

import httpx

from talent_agent_py.application.exceptions import (
    TalentSearchDeniedError,
    TalentSearchDependencyError,
)
from talent_agent_py.application.ports.talent_search import (
    EntityResolution,
    EntityResolutionRequest,
    TalentSearchPort,
    TalentSearchRequest,
    TalentSearchResponse,
)
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.settings import Settings


class JavaTalentClient(TalentSearchPort):
    """携带可信用户上下文调用 Java，Java 仍执行最终鉴权。"""

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
        return headers

    async def _post(self, path: str, payload: object, user: UserContext) -> object:
        try:
            response = await self._http.post(path, json=payload, headers=self._headers(user))
        except httpx.HTTPError as exc:
            raise TalentSearchDependencyError("Java 人才服务网络异常") from exc

        if response.status_code in {401, 403}:
            raise TalentSearchDeniedError("Java 拒绝当前用户访问")
        if response.status_code >= 500:
            raise TalentSearchDependencyError("Java 人才服务暂时不可用")
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TalentSearchDependencyError("Java 人才服务响应无效") from exc

    async def resolve_entities(
        self, requests: list[EntityResolutionRequest], user: UserContext
    ) -> list[EntityResolution]:
        payload = {"entities": [item.model_dump(mode="json") for item in requests]}
        data = await self._post(self._settings.java_resolve_path, payload, user)
        if not isinstance(data, dict):
            raise TalentSearchDependencyError("Java 实体解析响应格式错误")
        return [
            EntityResolution.model_validate(item, strict=False)
            for item in data.get("entities", [])
        ]

    async def search_candidates(
        self, request: TalentSearchRequest, user: UserContext
    ) -> TalentSearchResponse:
        data = await self._post(
            self._settings.java_search_path,
            request.model_dump(mode="json", exclude_none=True),
            user,
        )
        return TalentSearchResponse.model_validate(data, strict=False)
