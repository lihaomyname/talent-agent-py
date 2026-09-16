"""Java eTalent 内部接口适配器。"""

from typing import Any

import httpx
import structlog

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
from talent_agent_py.domain.conversation import CandidateCard, UserContext
from talent_agent_py.domain.enums import EntityKind, EntityResolutionStatus
from talent_agent_py.settings import Settings
from talent_agent_py.telemetry import sanitize_log_value

logger = structlog.get_logger(__name__)


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
        """保存 HTTP 客户端和配置；启用用户 Cookie 时检查目标地址白名单。"""

        # 由应用生命周期创建并关闭的共享异步 HTTP 客户端。
        self._http = http_client
        # 招聘接口路径、超时和认证策略。
        self._settings = settings
        if settings.java_requires_user_cookie:
            base_url = self._http.base_url
            if (
                base_url.scheme != "https"
                or base_url.host != settings.java_cookie_allowed_host
                or base_url.port not in {None, 443}
            ):
                raise ValueError("招聘 Cookie 只能发送到白名单 HTTPS 标准端口")

    def _headers(self, user: UserContext) -> dict[str, str]:
        """构建可信用户头、服务凭据和允许转发的招聘 Cookie。"""

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
        """发送 JSON 请求并记录日志，返回业务 data；请求失败转换为依赖异常。"""

        headers = self._headers(user)
        logger.info(
            "招聘接口请求",
            method="POST",
            url=str(self._http.base_url.join(path)),
            headers=sanitize_log_value(headers),
            payload=sanitize_log_value(payload),
        )
        try:
            response = await self._http.post(path, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.exception("招聘接口网络异常", method="POST", path=path)
            raise TalentSearchDependencyError("Java 人才服务网络异常") from exc

        data = self._decode_response(response)
        logger.info(
            "招聘接口响应",
            method="POST",
            path=path,
            status_code=response.status_code,
            response=sanitize_log_value(data),
        )
        return data

    async def _get(self, path: str, user: UserContext) -> object:
        """使用同一白名单 Cookie 调用招聘系统的字典读取接口。"""

        headers = self._headers(user)
        logger.info(
            "招聘接口请求",
            method="GET",
            url=str(self._http.base_url.join(path)),
            headers=sanitize_log_value(headers),
        )
        try:
            response = await self._http.get(path, headers=headers)
        except httpx.HTTPError as exc:
            logger.exception("招聘接口网络异常", method="GET", path=path)
            raise TalentSearchDependencyError("Java 人才服务网络异常") from exc
        data = self._decode_response(response)
        logger.info(
            "招聘接口响应",
            method="GET",
            path=path,
            status_code=response.status_code,
            response=sanitize_log_value(data),
        )
        return data

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
            raw_code = body.get("code")
            code = int(raw_code) if str(raw_code).isdigit() else raw_code
            if code in {401, 403}:
                raise TalentSearchDeniedError("招聘系统登录已失效或无人才库权限")
            if code != 200:
                raise TalentSearchDependencyError(
                    f"招聘系统返回业务错误：{body.get('msg') or code}"
                )
            return body.get("data")
        return body

    @staticmethod
    def _candidate_card(item: dict[str, Any]) -> CandidateCard:
        """把宽版 TalentResumeVO 收敛为不含联系方式的安全候选人卡片。"""

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
        """按配置选择内部契约或招聘网站适配，返回逐项实体解析结果。"""

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

        city_items: list[dict[str, Any]] = []
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
                requested_city = self._normalize_city_name(item.text)
                candidates.extend(
                    EntityCandidate(code=str(option["id"]), label=str(option["name"]))
                    for option in city_items
                    if self._normalize_city_name(str(option.get("name", "")))
                    == requested_city
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

    @staticmethod
    def _normalize_city_name(value: str) -> str:
        """允许“杭州”和字典中的“杭州市”稳定匹配。"""

        normalized = value.strip()
        return normalized[:-1] if normalized.endswith("市") else normalized

    async def search_candidates(
        self, request: TalentSearchRequest, user: UserContext
    ) -> TalentSearchResponse:
        """请求人才列表并适配分页格式，返回最多一页的安全候选人卡片。"""

        data = await self._post(
            self._settings.java_search_path,
            request.model_dump(mode="json", exclude_none=True),
            user,
        )
        if data is None:
            raise TalentSearchDependencyError("招聘接口成功响应缺少分页数据")
        if isinstance(data, dict) and "list" in data:
            # 浏览器人才库接口返回 PageResult<TalentResumeVO>。
            items = data.get("list") or []
            if not isinstance(items, list):
                raise TalentSearchDependencyError("招聘接口分页列表格式错误")
            # 即使上游忽略 pageSize，也只接收本页允许的前 10 条安全卡片。
            candidates = [
                self._candidate_card(item)
                for item in items[: request.pageSize]
                if isinstance(item, dict)
            ]
            last_page = data.get("lastPage", data.get("isLastPage"))
            if not isinstance(last_page, bool):
                last_page = request.currentPage >= int(data.get("pages") or 0)
            return TalentSearchResponse(
                candidates=candidates,
                total=int(data.get("total") or 0),
                has_next=not bool(last_page),
            )
        if isinstance(data, dict) and isinstance(data.get("candidates"), list):
            data = {
                **data,
                "candidates": data["candidates"][: request.pageSize],
            }
        return TalentSearchResponse.model_validate(data, strict=False)
