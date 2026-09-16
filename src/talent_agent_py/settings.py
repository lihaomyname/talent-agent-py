"""从环境变量加载的强类型运行配置。"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API、持久化、LLM、Java 和搜索策略配置。"""

    model_config = SettingsConfigDict(
        env_prefix="TALENT_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用名称，用于标识服务。
    app_name: str = "talent-agent-py"
    # 运行环境名称，例如 local。
    environment: str = "local"
    # 调试配置标志；具体生效范围以调用方为准。
    debug: bool = False
    # 业务 HTTP 路由统一前缀。
    api_prefix: str = "/api/v1"
    # SQLAlchemy 数据库连接地址，包含驱动和连接参数。
    database_url: str = "sqlite+aiosqlite:///./talent_agent.db"
    # 是否输出 SQLAlchemy SQL 日志。
    database_echo: bool = False
    # 是否启动时建表，仅用于本地开发和测试。
    auto_create_schema: bool = False

    # 大模型服务中的模型名称。
    llm_model: str = "deepseek-v3"
    # OpenAI 兼容协议的模型服务地址。
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # 模型访问密钥；为空时使用不可用客户端并在业务调用时报错。
    llm_api_key: SecretStr | None = None
    # 单次模型请求超时，单位秒。
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=180)
    # 模型采样温度，数值越低通常越稳定。
    llm_temperature: float = Field(default=0.1, ge=0, le=2)
    # 结构化输出校验失败后的最大修复次数。
    llm_repair_attempts: int = Field(default=1, ge=0, le=1)

    # 招聘系统服务地址。
    java_base_url: str = "http://localhost:8080"
    # 内部招聘接口的服务凭据；不使用时为空。
    java_service_token: SecretStr | None = None
    # 内部实体解析接口路径。
    java_resolve_path: str = "/internal/agent/search/resolve-entities"
    # 人才搜索接口路径。
    java_search_path: str = "/internal/agent/search/candidates"
    # 浏览器直连接口模式下的城市选项路径。
    java_city_options_path: str = "/api/eTalent/option/city"
    # 招聘系统单次请求超时，单位秒。
    java_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    # 转发给招聘系统的登录 Cookie 名。
    java_user_cookie_name: str = "authOpenIdToken"
    # 允许接收用户登录 Cookie 的域名。
    java_cookie_allowed_host: str = "zhaopin.netease.com"
    # 是否要求请求包含用户招聘登录 Cookie。
    java_requires_user_cookie: bool = False
    # 是否适配招聘网站接口，而不是内部 Agent 契约。
    java_direct_browser_api: bool = False

    # 每页请求和展示 10 位候选人，控制响应数据量。
    default_page_size: int = Field(default=10, ge=1, le=10)
    # 人才搜索默认排序编码。
    default_sort_type: int = 1
    # 默认关键词匹配方式。
    default_keywords_match_type: str = "ALL"
    # 默认透传给招聘接口的 inFlow 标志。
    default_in_flow: bool = True
    # 默认透传给招聘接口的 hideClue 标志。
    default_hide_clue: bool = True
    # 预留 SSE 配置标志；当前业务流程未启用 SSE。
    enable_sse: bool = False
    # 自然语言找人总开关，关闭时业务请求返回功能不可用。
    enable_agent: bool = True


@lru_cache
def get_settings() -> Settings:
    """每个进程只创建一个配置实例。"""

    return Settings()
