"""基于 OpenAI 兼容协议的内部大模型适配器。"""

import asyncio
import json
import time
from typing import TypeVar

import structlog
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
from talent_agent_py.infrastructure.persistence.model_message_writer import ModelMessageWriter
from talent_agent_py.settings import Settings

T = TypeVar("T", bound=BaseModel)
logger = structlog.get_logger(__name__)


class UnavailableLLMClient(LLMClient):
    """未配置模型密钥时保留服务健康检查，并在业务调用处明确失败。"""

    async def classify_message(self, **kwargs: object) -> MessageRoute:
        """返回消息分类；不可用客户端会抛出 ModelOutputError。"""

        raise ModelOutputError("尚未配置 TALENT_AGENT_LLM_API_KEY")

    async def parse_search_draft(self, **kwargs: object) -> SearchPlanDraft:
        """返回首次搜索草稿；模型调用或输出校验失败时抛出 ModelOutputError。"""

        raise ModelOutputError("尚未配置 TALENT_AGENT_LLM_API_KEY")

    async def parse_plan_patch(self, **kwargs: object) -> PlanPatch:
        """返回基于当前计划的增量补丁；不可用或校验失败时抛出 ModelOutputError。"""

        raise ModelOutputError("尚未配置 TALENT_AGENT_LLM_API_KEY")


class InternalLLMClient(LLMClient):
    """通过严格结构化输出实现路由、首次解析和增量修改。"""

    def __init__(
        self, settings: Settings, message_writer: ModelMessageWriter | None = None
    ) -> None:
        """依据配置创建模型客户端；密钥缺失时拒绝初始化真实客户端。"""

        if settings.llm_api_key is None:
            raise ValueError("启用真实模型时必须配置 TALENT_AGENT_LLM_API_KEY")
        # 外层结构化输出失败时允许追加调用模型的次数。
        self._repair_attempts = settings.llm_repair_attempts
        self._model_name = settings.llm_model
        self._message_writer = message_writer
        # OpenAI 兼容协议客户端，负责实际异步模型请求。
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

        # 内部网关不支持 response_format=json_schema，思考模式也不支持强制 tool_choice；
        # 因此请求 json_object，把 JSON Schema 拼进提示词，由本方法做宽松校验和有限修复。
        model = self._model.bind(response_format={"type": "json_object"})
        schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False)
        structured_system_prompt = (
            f"{system_prompt}\n\n只能输出一个符合以下 JSON Schema 的 JSON 对象：\n{schema}"
        )
        messages = [SystemMessage(structured_system_prompt), HumanMessage(user_prompt)]
        last_error: Exception | None = None

        for attempt in range(self._repair_attempts + 1):
            attempt_number = attempt + 1
            invocation_id = None
            actual_user_input = json.dumps(
                [message.content for message in messages if isinstance(message, HumanMessage)],
                ensure_ascii=False,
            )
            if self._message_writer:
                invocation_id = await self._message_writer.write_user(
                    output_type.__name__, attempt_number,
                    self._model_name, structured_system_prompt, actual_user_input,
                )
            logger.info(
                "LLM 请求",
                operation=output_type.__name__,
                attempt=attempt_number,
                system_prompt=structured_system_prompt,
                user_prompt=user_prompt,
            )
            started = time.perf_counter()
            response_text: str | None = None
            try:
                response = await model.ainvoke(messages)
                response_text = str(response.content)
                logger.info(
                    "LLM 响应",
                    operation=output_type.__name__,
                    attempt=attempt_number,
                    response=response_text,
                )
                payload = json.loads(response_text)
                # 先校验外层契约；PlanPatch.value 的具体条件结构仍由应用补丁时校验。
                parsed = output_type.model_validate(payload, strict=False)
                logger.info(
                    "LLM 结构化结果",
                    operation=output_type.__name__,
                    result=parsed.model_dump(mode="json"),
                )
                await self._write_assistant(
                    invocation_id, output_type.__name__, attempt_number,
                    response_text, "SUCCESS", started, response=response,
                )
                return parsed
            except asyncio.CancelledError as exc:
                await self._write_assistant(
                    invocation_id, output_type.__name__, attempt_number,
                    response_text, "ERROR", started, error=exc,
                )
                raise
            except (ValidationError, ValueError, TypeError) as exc:
                await self._write_assistant(
                    invocation_id, output_type.__name__, attempt_number,
                    response_text, "INVALID_OUTPUT", started, error=exc,
                )
                last_error = exc
                logger.warning(
                    "LLM 结构化响应校验失败",
                    operation=output_type.__name__,
                    attempt=attempt_number,
                    exception_type=type(exc).__name__,
                )
                if attempt >= self._repair_attempts:
                    break
                # 修复提示只允许调整 JSON 结构，不能改变用户原始意图。
                messages.append(HumanMessage(
                    "上一份输出不符合 JSON Schema。请保持原意，仅修正结构后重新输出。"
                ))
            except Exception as exc:
                await self._write_assistant(
                    invocation_id, output_type.__name__, attempt_number,
                    response_text, "ERROR", started, error=exc,
                )
                logger.exception(
                    "LLM 请求失败",
                    operation=output_type.__name__,
                    exception_type=type(exc).__name__,
                    exception_message=str(exc),
                )
                if type(exc).__name__ in {"APITimeoutError", "TimeoutException", "TimeoutError"}:
                    raise ModelOutputError("大模型请求超时，请重试") from exc
                raise ModelOutputError("大模型服务调用失败，请检查模型日志") from exc

        raise ModelOutputError("大模型结构化输出校验失败") from last_error

    async def _write_assistant(
        self, invocation_id: int | None, operation: str, attempt: int,
        content: str | None, status: str, started: float,
        *, response: object | None = None, error: BaseException | None = None,
    ) -> None:
        if not self._message_writer:
            return
        usage = self._token_usage(response)
        await self._message_writer.write_assistant(
            invocation_id, operation, attempt, self._model_name,
            content, status, round((time.perf_counter() - started) * 1000),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            error_message=str(error) if error else None,
        )

    @staticmethod
    def _token_usage(response: object | None) -> dict[str, int | None]:
        if response is None:
            return {}
        standard = getattr(response, "usage_metadata", None) or {}
        metadata = getattr(response, "response_metadata", None) or {}
        provider = metadata.get("token_usage", {})
        return {
            "prompt_tokens": standard.get("input_tokens", provider.get("prompt_tokens")),
            "completion_tokens": standard.get(
                "output_tokens", provider.get("completion_tokens")
            ),
            "total_tokens": standard.get("total_tokens", provider.get("total_tokens")),
        }

    async def classify_message(
        self,
        *,
        message: str,
        current_plan: SearchPlan | None,
        has_pending_clarification: bool,
    ) -> MessageRoute:
        """返回消息分类；不可用客户端会抛出 ModelOutputError。"""

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
        """返回首次搜索草稿；模型调用或输出校验失败时抛出 ModelOutputError。"""

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
        """返回基于当前计划的增量补丁；不可用或校验失败时抛出 ModelOutputError。"""

        return await self._invoke_structured(
            system_prompt=PATCH_SYSTEM_PROMPT,
            user_prompt=str({
                "currentPlan": current_plan.model_dump(mode="json"),
                "messages": messages,
            }),
            output_type=PlanPatch,
        )
