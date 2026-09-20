"""修正模型对常见可举证条件的保守误判。"""

import re

from talent_agent_py.domain.plan import Preference, SearchPlanDraft

# 这里只列出能够从工作经历中客观举证、且业务中高频的领域。
# 未命中的内容仍由提示词分类，避免把“北美工作过”等条件误转成偏好。
_EVIDENCE_KEYWORDS = (
    "支付",
    "收单",
    "清结算",
    "电商",
    "游戏",
    "金融",
    "供应链",
    "订单",
    "营销",
    "高并发",
    "分布式",
    "微服务",
    "java",
    "python",
    "golang",
    "go语言",
    "vue",
    "react",
    "ci/cd",
    "nginx",
)


def normalize_preferences(draft: SearchPlanDraft) -> SearchPlanDraft:
    """把明确可由履历举证的常见条件从“不支持”移入偏好。"""

    preferences = list(draft.preferences)
    unsupported = []
    existing_quotes = {item.source_quote for item in preferences}
    existing_ids = {item.id for item in preferences}

    for condition in draft.unsupported_conditions:
        original = condition.original_text.strip()
        lowered = original.lower()
        if not any(keyword in lowered for keyword in _EVIDENCE_KEYWORDS):
            unsupported.append(condition)
            continue
        if original in existing_quotes:
            continue
        preference_id = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        if not preference_id:
            preference_id = f"preference-{len(preferences) + 1}"
        base_id = preference_id[:64]
        suffix = 2
        while preference_id in existing_ids:
            preference_id = f"{base_id[:60]}-{suffix}"
            suffix += 1
        preferences.append(
            Preference(
                id=preference_id[:64],
                description=original,
                source_quote=original,
            )
        )
        existing_quotes.add(original)
        existing_ids.add(preference_id[:64])

    if len(preferences) == len(draft.preferences):
        return draft
    return draft.model_copy(
        update={
            "preferences": preferences,
            "unsupported_conditions": unsupported,
        }
    )
