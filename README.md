# talent-agent-py

自然语言找人 Agent 的 Python 编排服务。

## 核心能力

项目使用分层结构实现自然语言人才搜索：

1. `MessageRouter` 判断闲聊、搜索、修改、翻页、停止和澄清回答。
2. LLM 只把自然语言转换为 `SearchPlanDraft` 或 `PlanPatch`，不直接调用任意工具。
3. LangGraph 用固定节点和固定边控制执行顺序。
4. Python 确定性校验条件；含义不清时返回结构化澄清卡。
5. `TalentSearchPort` 是 Tool 边界，由 `JavaTalentClient` 调用招聘系统。
6. 新的有效搜索消息会替代旧 Run；闲聊和进度查询不会打断搜索。

当前采用单实例运行方式。使用进程内消息写锁，确保搜索被新消息打断时两个短暂重叠的
HTTP 请求不会生成相同消息序号；暂不实现分布式锁、多实例一致性和复杂并发恢复。

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

- `GET /`：自然语言找人会话页面。
- `GET /health`：进程存活检查。
- `GET /ready`：数据库就绪检查。
- `GET /docs`：OpenAPI 文档。
- `GET /metrics`：Prometheus 指标。

打开首页后，点击右上角“连接招聘系统”，填写用户 ID，并粘贴当前登录招聘系统的
`authOpenIdToken`。页面只创建会话 Cookie，不写入数据库；关闭浏览器会话后自动失效。
随后可以直接输入自然语言搜索条件，在页面右侧观察 LangGraph 节点执行过程和最终生成的
招聘接口请求参数。

## 主要 API

所有业务接口要求受信网关注入 `X-User-Id`，可选传入 `X-Tenant-Id` 和 `X-Trace-Id`。请求体不接受 `operatorId`。

调用人才搜索时，客户端还需要把当前登录态 Cookie 一并发送给 Agent：

```http
Cookie: authOpenIdToken=<当前用户令牌>
```

Agent 只提取并透传 `authOpenIdToken`，不会转发其他 Cookie，也不会把令牌写入数据库、日志或 LangGraph 持久化状态。浏览器跨域调用时必须启用凭据发送，并由网关配置允许的来源；更推荐把 Agent 接口反向代理到招聘系统同站域名下。

候选人结果固定按每页 10 条请求和展示；总命中数只用于说明搜索范围，可通过“下一页”继续查看。

```text
POST /api/v1/sessions
GET  /api/v1/sessions
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

`TALENT_AGENT_AUTO_CREATE_SCHEMA=true` 只用于测试和本地开发。

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

## 日志

控制台会输出四类 JSON 日志，中文和业务字段保持可读：

- `HTTP 请求响应`：入站 API 的请求体、响应体、状态码和耗时。
- `LLM 请求`、`LLM 响应`、`LLM 结构化结果`：提示词、模型原始输出和校验后的对象。
- `LangGraph 节点开始`、`LangGraph 节点完成`：当前节点、Run 标识和节点输出。
- `招聘接口请求`、`招聘接口响应`：实际搜索参数和招聘接口业务响应。

Cookie、Authorization、API Key、手机号、邮箱和证件号始终显示为 `***已脱敏***`，
其他搜索条件、SearchPlan 和候选人安全卡片按明文打印。

## Java 契约

Java 适配假设和上线前必须确认的字段语义见 [docs/java-contract.md](./docs/java-contract.md)。

## 后续设计

当前设计决策、会话记忆边界，以及后续“职位截图解析 → 复用找人 Agent → 人岗匹配”的方案见
[Talent Agent 当前设计记忆与职位截图方案](./docs/design-memory-and-position-image-plan.md)。
