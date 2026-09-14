"""共用的严格 Pydantic 模型配置。"""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """在模型、API 和工具边界拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)
