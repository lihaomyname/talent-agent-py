"""基于 OpenAI 兼容协议的内部大模型适配器。"""

from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from talent_agent_py.application.exceptions import ModelOutputError
from talent_agent_py.application.ports.llm import LLMClient
from talent_agent_py.domain.conversation import MessageRoute
from talent_agent_py.domain.plan import PlanPatch, SearchPlan, SearchPlanDraft
from talent_agent_py.infrastructure.clients.prompts import (
    PATCH_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
)
from talent_agent_py.settings import Settings

T = TypeVar("T", bound=BaseModel)


class UnavailableLLMClient(LLMClient):
    """未配置模型密钥时保留服务健康检查，并在业务调用处明确失败。"""

    async def classify_message(self, **kwargs) -> MessageRoute:
        raise ModelOutputError("尚未配置 TALENT_AGENT_LLM_API_KEY")

    async def parse_search_draft(self, **kwargs) -> SearchPlanDraft:
        raise ModelOutputError("尚未配置 TALENT_AGENT_LLM_API_KEY")

    async def parse_plan_patch(self, **kwargs) -> PlanPatch:
        raise ModelOutputError("尚未配置 TALENT_AGENT_LLM_API_KEY")


class InternalLLMClient(LLMClient):
    """通过严格结构化输出实现路由、首次解析和增量修改。"""

    def __init__(self, settings: Settings) -> None:
        if settings.llm_api_key is None:
            raise ValueError("启用真实模型时必须配置 TALENT_AGENT_LLM_API_KEY")
        self._repair_attempts = settings.llm_repair_attempts
        self._model = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )

    async def _invoke_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[T],
    ) -> T:
        """调用模型，并最多修复一次不符合 Schema 的输出。"""

        runnable = self._model.with_structured_output(output_type)
        messages = [SystemMessage(system_prompt), HumanMessage(user_prompt)]
        last_error: Exception | None = None

        for attempt in range(self._repair_attempts + 1):
            try:
                result = await runnable.ainvoke(messages)
                return output_type.model_validate(result, strict=False)
            except (ValidationError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt >= self._repair_attempts:
                    break
                # 修复提示只允许调整 JSON 结构，不能改变用户原始意图。
                messages.append(HumanMessage(
                    "上一份输出不符合 JSON Schema。请保持原意，仅修正结构后重新输出。"
                ))

        raise ModelOutputError("大模型结构化输出校验失败") from last_error

    async def classify_message(
        self,
        *,
        message: str,
        current_plan: SearchPlan | None,
        has_pending_clarification: bool,
    ) -> MessageRoute:
        payload = {
            "message": message,
            "currentPlan": current_plan.model_dump(mode="json") if current_plan else None,
            "hasPendingClarification": has_pending_clarification,
        }
        return await self._invoke_structured(
            system_prompt=ROUTER_SYSTEM_PROMPT,
            user_prompt=str(payload),
            output_type=MessageRoute,
        )

    async def parse_search_draft(self, *, messages: list[str]) -> SearchPlanDraft:
        return await self._invoke_structured(
            system_prompt=PLAN_SYSTEM_PROMPT,
            user_prompt=str({"messages": messages}),
            output_type=SearchPlanDraft,
        )

    async def parse_plan_patch(
        self,
        *,
        messages: list[str],
        current_plan: SearchPlan,
    ) -> PlanPatch:
        return await self._invoke_structured(
            system_prompt=PATCH_SYSTEM_PROMPT,
            user_prompt=str({
                "currentPlan": current_plan.model_dump(mode="json"),
                "messages": messages,
            }),
            output_type=PlanPatch,
        )
