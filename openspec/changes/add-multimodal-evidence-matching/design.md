## Context

现有服务通过结构化草稿、补丁、实体解析和编译调用 Java 搜索，每页 10 人。列表已有教育、工作经历，但卡片未保留这些资料。新增需求是统一文字和截图、证据匹配、有界检索及历史恢复。

已核对 persistence/models.py、仓储、SessionService.history、AgentService.get_result：现有 JSON 字段可以承载本期数据，但读取代码直接按旧 SearchPlan/SearchResult/MessageOutcome 解码，需要增加快照版本适配。本期优先复用表，不以新增表为前提。

## Goals / Non-Goals

**Goals:**
- 普通条件直接搜索；经历要求与偏好进入匹配，目标最多返回 10 人。
- 有证据、有预算，支持需求编辑、历史回显及继续检索。
- 复用现有表、SQLAlchemy、事务和 TaskRegistry，兼容旧记录。

**Non-Goals:**
- 不新增表、不改字段或索引、不执行数据库迁移，不另建存储框架。
- 不引入向量库、多 Agent、分布式调度、后台自动恢复模型调用或自由工具执行。
- 不自动放宽硬条件，不声称全库最优，不输出无依据总分。
- 不保存原图、Cookie、密钥及完整招聘宽响应，不增加跨会话长期偏好记忆。

## Decisions

### 1. 统一需求与模式交接

SearchRequirements 保留输入原文、可执行筛选、偏好和歧义，各项有稳定 ID 和原文依据。现阶段只有 SearchConditions 支持的固定字段用于强制筛选；技术栈、语言、工具、项目经验及软能力统一作为偏好，不淘汰候选人。旧快照中的必须项和面试项在新确认版本中合并为偏好。截图直接提取结构，摘要仅展示，不改写成自然语言再次解析。岗位地点不自动转候选人所在地，招聘方不转候选人公司，领域经验不转总工龄。

确认卡以紧凑分组支持增删改；对话使用同一变更模型。字段缺失表示保留，删除必须显式表达。页面明确说明偏好只排序，教育或工作经历未提及某项能力时为 UNKNOWN。仅打开编辑卡片不取消任务，确认新版本才替代旧运行；旧版本和结果保留，旧游标不能用于新版本，不做跨版本评估缓存复用。

分流看合并后的完整需求而非本次消息或输入介质：纯筛选走 V1，包含偏好时走匹配。纯筛选截图确认后也走 V1。首次 V1 转匹配继承当前计划但不继承页码；“只看本科”保留既有偏好；移除最后偏好后将已校验结构直接交回 V1。当前语义基准从最新已提交计划读取，重启不丢偏好。

### 2. 图片与模型

独立视觉配置初始 model 为 deepseek-flash，端点及凭据来自环境。先验证实际网关图片内容块与 JSON 输出，不支持时明确失败，不把图片发给纯文本模型。文本沿用现有配置。

初始限制单张 PNG/JPEG/WebP、10 MiB、2000 万像素；校验文件头、实际解码、尺寸。识别不清或非职位图片提示纠正。图片仅在请求中存在，提取文字限长保存；不记录图片和简历全文。单次提取有超时和一次修复上限。图片、简历中的指令均作为不可信内容，不改变权限或执行流程。

### 3. 资料与匹配证据

匹配专用 search_candidate_profiles 与普通检索共用 Java 请求、分页和错误适配，返回卡片、CandidateProfile、分页；不扩展旧 V1 CandidateCard。Profile 白名单保留教育、工作职位/公司/日期/描述、地点、更新时间及来源。模型不接收姓名、联系方式、年龄、性别和内部操作人；描述清洗，相同 duty/detail 去重。

每项偏好返回 SUPPORTED/PARTIAL/UNKNOWN/CONTRADICTED、criterion ID、来源路径、短引用及理由。校验来源真实和归属，有限修复失败记评估失败。引用存在不能证明结论正确，另用语义评测检查。所有固定搜索命中的候选人均可展示；偏好按支持项数、部分支持项数降序，同分保持召回顺序，不输出综合百分分数。资料没有提及语言或工具时只能标为 UNKNOWN，不能据此淘汰。

workYears 样本是日期格式，契约未确认不当数值；任职时间不等于技能时间。缺失、截断显式标记。必要资料与证据进入匹配快照，不进入旧 V1 卡片快照；拒绝者只留 ID 和必要判定，不重复保存全文。

### 4. 表复用与快照版本

| 现有表/字段 | 复用内容 |
| --- | --- |
| agent_sessions.active_run_id/current_plan_version | 共用当前运行、计划版本指针 |
| agent_messages.content/outcome_json | 用户文字、截图提取文字、确认/修改/继续动作；回复引用及安全摘要 |
| agent_search_plans.plan_json | 已确认完整需求版本和可执行条件投影 |
| agent_pending_clarifications.card_json/draft_json | 唯一待确认或澄清草稿，提交后清除；原输入仍在消息表 |
| agent_runs.result_json | 预算、检查点、必要资料/证据、结果组及停止原因 |

V2 匹配快照以 schema_version=2 和 kind（matching_plan、matching_run、matching_reply、matching_draft）明确区分。没有 kind 或为 V1 的记录按旧模型解析，不批量改写。未知未来版本明确返回兼容性错误，不猜测。所有新增 JSON 键由类型化模型及中文注释定义。

计划 V2 包含 owner_scope、requirements、search_plan，版本和已吸收序号与表列一致。普通编译读取 search_plan 投影，路由读取完整需求；两种模式共用版本序列。运行 V2 包含 owner_scope、plan_version、parent_run_id、continuation_root_run_id、request_key、budget、usage、checkpoint、summary、output_group。

checkpoint 保存固定查询、下一页、批内缓冲、候选 ID 及评估状态/来源、未展示池、已展示 ID、源耗尽标志。每次继续建新 Run，继承最近已提交 checkpoint，budget/usage 重新开始；旧 Run 的结果组与消耗不改写。主结果最多 10 人，不能被旧 _bounded_result 当整个 SearchResult 解码或截断。

状态沿用既有枚举：重启中断写 FAILED、stage=interrupted、error_code=PROCESS_RESTARTED，JSON stop_reason=INTERRUPTED。result_status 使用既有 OK/EMPTY 或错误分类，新的停止原因只在匹配快照表达。

确认/继续使用消息幂等键，在单进程会话锁内检查、写消息、创建关联 Run，提交后才开始调用；重复请求返回已有 Run，不依赖内存幂等记录。trigger_message_sequence 保持消息关联。

必须同步适配 PlanRepository、ClarificationRepository、SessionService.get/history、AgentService.get_result/_bounded_result、重复消息读取及 API 序列化。旧记录保持原响应；新匹配记录返回明确类型的展示引用/摘要，资料由授权端点读取，不直接暴露 checkpoint。不能把新快照无条件交给旧模型验证。

### 5. 有界检索、提交与继续

确认 → 编译 → 每批 10 人检索 → 去重清洗 → 每批最多 5 人核验 → 提交状态及游标 → 决策。复用工具与编译，不逐页执行完整 V1 Graph、写新计划或追加聊天结果。无有效检索方向先澄清，不自动全库扫描，不自动扩词或放宽要求。

初始单轮预算：最多 5 次搜索、50 个新检查人选、20 次匹配模型尝试（含修复）、120 秒。每次调用前检查，超时不超过剩余 deadline。得到 10 名去重候选人并完成偏好证据判断即停止；用户继续时再读取下一组。偏好用于组内排序，不为寻找“全偏好命中”扫描额外页面。不足十人如实返回。

停止原因：TARGET_REACHED、SOURCE_EXHAUSTED、PAGE_LIMIT、CANDIDATE_LIMIT、MODEL_LIMIT、TIME_LIMIT、NO_NEW_CANDIDATES、CANCELLED、SUPERSEDED、DEPENDENCY_ERROR、INTERRUPTED、CONTEXT_LIMIT。零新增一批停止；权限拒绝按 DENIED 处理。

每个评估小批完成后，同一短事务保存候选状态、批内位置和消耗；整页未完须保存缓冲，游标不越过未落库人选。用完整快照重新赋值，不能依赖 SQLAlchemy 追踪嵌套 JSON 原地修改。事务不跨模型/HTTP 等待；调用前预记尝试消耗，结果返回后保存结果。停止、超时和失败保留已提交进度；崩溃未提交小批可重做并去重。

继续同版本最新可继续 Run，先处理未展示池及未消费缓冲，再读后续页；不重复展示或评估。旧祖先 Run 不得分叉继续，返回 STALE_CONTINUATION 指向最新 Run。新版本从头检索。初始累计最多 10 轮、500 人及 10 MiB 单快照，到限只禁继续并提示新任务，不删除历史；跨新任务不保证去重。

### 6. 共用控制与持久化恢复

普通和匹配共用现有 TaskRegistry 的取消/替代机制，不另建独立活动任务表。内存仅保留 Task、锁、在途凭据及有界缓存，业务状态以现有表为准。

控制先于解析：闲聊不打断，进度读取 active_run，停止取消当前任务，确认新需求才替代旧运行。跨模式等待旧任务必要短提交，发布前检查当前 Run/版本，旧结果只保留历史。锁不跨网络调用持有。

启动时仅将 V2 匹配遗留 QUEUED/RUNNING 标为中断，保留 checkpoint；用户主动继续创建新 Run 并重新提供当前身份和 Cookie，不自动恢复模型调用。数据库不可用时就绪失败。仍是单实例，不做分布式抢占。

刷新、关闭后重进、服务重启后按会话从数据库恢复需求和结果组，不依赖 sessionStorage。本期不建立候选资料内存缓存，任务结束即释放 Task、请求身份及闭包；业务数据后续直接读库。活动任务和上传/模型调用分别设并发上限，不能通过清理内存删除业务历史。未确认草稿落现有澄清表。

### 7. 权限和数据边界

V2 计划、草稿、回复引用及运行保存可信 tenant_id/user_id/session_id，先查会话归属再核对作用域。旧表没有租户列，旧 V1 沿用既有部署身份边界，不根据读请求猜测补租户；V2 不得跨作用域读取。

业务已确认候选人不删除且均可查看。默认轮询只返回计数和状态；历史结果在校验会话归属与 V2 作用域后直接读数据库，继续直接继承 checkpoint，不额外调用 Java 复核候选人可见性。

权限拒绝返回 DENIED、清理内存资料，不删除数据库审计历史。Cookie 仅在本轮协程最长 deadline 内使用，结束释放，不落库或日志。历史接口也不能绕过授权直接序列化 V2 资料。

### 8. API 与界面

复用会话、消息历史、运行标识，新增：
- POST /sessions/{id}/requirements：文字提取/增量，保存消息和草稿。
- POST /sessions/{id}/requirement-images：保存提取文字及草稿，不存原图。
- POST /sessions/{id}/requirements/{requirementId}/confirm：显式增删改及分类确认，校验草稿版本，原子保存新计划与启动 Run；按完整需求分流。
- GET /sessions/{id}/matches/{runId}：默认进度，include_results=true 校验会话归属后返回保存的结果。
- POST /sessions/{id}/matches/{runId}/continue、.../cancel：保存继续动作或取消。

confirm 是唯一首次启动入口，不再同时设置另一个 matches POST。明确自然语言可由服务端执行同样确认逻辑，不强制额外点击；截图必须确认。匹配进度只更新一张卡，首次及每次继续各保存一组汇总。展示需求版本、偏好证据、信息不足项、范围和停止原因；旧版本结果可查看、不能直接继续。简单搜索保留原位分页。

## Risks / Trade-offs

- [JSON 无新增索引] → 按会话/Run 主键访问、有界快照，不做跨全库证据检索；有实证瓶颈再评估结构。
- [旧代码不认识 V2] → 先部署兼容读取，再开新写入；回滚保留双版本读取，不直接回旧二进制。
- [简历或证据不足] → UNKNOWN/截断提示及语义评测，不默认需要详情接口。
- [崩溃小批重做] → 小批提交、调用消耗预记、ID 去重，用户主动继续。
- [历史增加数据量] → 必要快照、大小上限，不用内存 TTL 删除数据库历史；后续明确保留策略。
- [原列注释只描述 V1] → 本期不改 DDL，新增键在类型与本文说明，不声称数据库注释已更新。

## Migration Plan

无数据库迁移。先完成双版本读取及旧历史回归，再开 V2 写入与恢复，通过模型/Java 接入验证后启用功能。回滚关闭新增入口，保留历史可读与普通搜索；不得删除 V2 数据或让旧解码器处理新快照。

## Open Questions

- 实际 deepseek-flash 网关能力、Java 日期语义；人选无额外可见性复核已由业务确认。
- 默认预算和快照上限需要脱敏数据验证，不是性能 SLA。
- 历史保留周期沿用现有治理，本期不增加自动删除。
- 若实现发现现有字段或访问模式无法承载，单独提出证据再决定，不预先新增表。
