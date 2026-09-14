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

    app_name: str = "talent-agent-py"
    environment: str = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./talent_agent.db"
    database_echo: bool = False
    auto_create_schema: bool = False

    llm_model: str = "deepseek-v3"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=180)
    llm_temperature: float = Field(default=0.1, ge=0, le=2)
    llm_repair_attempts: int = Field(default=1, ge=0, le=1)

    java_base_url: str = "http://localhost:8080"
    java_service_token: SecretStr | None = None
    java_resolve_path: str = "/internal/agent/search/resolve-entities"
    java_search_path: str = "/internal/agent/search/candidates"
    java_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    default_page_size: int = Field(default=20, ge=1, le=100)
    default_sort_type: int = 1
    default_keywords_match_type: str = "ALL"
    default_in_flow: bool = True
    default_hide_clue: bool = True
    enable_sse: bool = False
    enable_agent: bool = True


@lru_cache
def get_settings() -> Settings:
    """每个进程只创建一个配置实例。"""

    return Settings()
