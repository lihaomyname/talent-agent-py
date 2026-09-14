# talent-agent-py

自然语言找人 Agent 的 Python 编排服务。

V1 将招聘人员的中文自然语言转换为受控、可审计的 `SearchPlan`，并调用 `recruit-social` 的 eTalent/Elasticsearch 搜索能力返回权限内人才。当前支持姓名、候选人职位、最低学历、工作年限、公司、学校、期望工作地、现居住地和院校标签。

V1 不绑定招聘职位，不接收 `positionId`，不进行 JD 解析、人岗匹配、候选人 LLM 评分、向量召回或外部寻源。

## OpenSpec

当前变更：[`build-natural-language-talent-search-v1`](./openspec/changes/build-natural-language-talent-search-v1/)

- [Proposal](./openspec/changes/build-natural-language-talent-search-v1/proposal.md)
- [Technical design](./openspec/changes/build-natural-language-talent-search-v1/design.md)
- [Conversation orchestration spec](./openspec/changes/build-natural-language-talent-search-v1/specs/conversation-orchestration/spec.md)
- [Search plan management spec](./openspec/changes/build-natural-language-talent-search-v1/specs/search-plan-management/spec.md)
- [Talent search execution spec](./openspec/changes/build-natural-language-talent-search-v1/specs/talent-search-execution/spec.md)
- [Implementation tasks](./openspec/changes/build-natural-language-talent-search-v1/tasks.md)

规格状态：4/4 artifacts complete，已通过 `openspec validate build-natural-language-talent-search-v1 --strict`。

## 技术结构

```text
FastAPI API
  → MessageRouter（闲聊、进度、停止、搜索、修改、澄清、分页）
  → LangGraph 固定状态图
  → LLMClient（只生成结构化 Draft/Patch）
  → TalentSearchPort（Java 实体解析和人才搜索）
  → SearchPlan 版本、Run 和待澄清状态
```

Python 不直连人才库数据库或 Elasticsearch。Java 继续负责业务 code、用户权限、查询语义和人才卡脱敏。

## 本地启动

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```bash
cp .env.example .env
uv sync --all-groups
uv run alembic upgrade head
uv run talent-agent-py
```

服务默认监听 `http://localhost:8000`：

- `GET /health`：进程存活检查。
- `GET /ready`：数据库就绪检查。
- `GET /docs`：OpenAPI 文档。
- `GET /metrics`：Prometheus 指标。

## 主要 API

所有业务接口要求受信网关注入 `X-User-Id`，可选传入 `X-Tenant-Id` 和 `X-Trace-Id`。请求体不接受 `operatorId`。

```text
POST /api/v1/sessions
GET  /api/v1/sessions/{sessionId}
POST /api/v1/sessions/{sessionId}/messages
GET  /api/v1/runs/{runId}
POST /api/v1/sessions/{sessionId}/cancel
GET  /api/v1/sessions/{sessionId}/result
POST /api/v1/sessions/{sessionId}/pages
```

V1 采用 Run 状态轮询，没有同时维护 SSE。用户修改搜索条件时会尝试取消旧的 LLM/Java 节点；已经开始的 SearchPlan 保存允许正常完成，新 Run 从最新计划继续。

## 数据库迁移

正式环境禁止运行时自动建表：

```bash
uv run alembic upgrade head
```

`TALENT_AGENT_AUTO_CREATE_SCHEMA=true` 只用于测试和本地演示。

MySQL 使用异步 `asyncmy` 驱动，例如：

```env
TALENT_AGENT_DATABASE_URL=mysql+asyncmy://user:password@127.0.0.1:3306/talent_agent?charset=utf8mb4
```

## 测试

```bash
uv run pytest -q
openspec validate build-natural-language-talent-search-v1 --strict
```

测试使用 Fake LLM 和 Fake Java，不需要外部服务或真实候选人数据。

## Java 契约

Java 适配假设和上线前必须确认的字段语义见 [docs/java-contract.md](./docs/java-contract.md)。
