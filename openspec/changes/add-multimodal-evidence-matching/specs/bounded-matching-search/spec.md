## ADDED Requirements

### Requirement: Bounded batch execution
系统 SHALL 每批读取 10 人，目标最多返回 10 人，每轮默认最多 5 次搜索、50 名新检查人选、20 次模型尝试（含修复）及 120 秒。调用前校验剩余额度，继续重置本轮预算，历史消耗保持可查。

#### Scenario: Budget exhausted with fewer results
- **WHEN** 达到任一上限而固定条件只召回七人
- **THEN** 停止新调用、保存已完成进度、返回七人及停止原因，不伪造人选凑数

#### Scenario: Preference comparison
- **WHEN** 已完成十名候选人的偏好证据判断
- **THEN** 在这十人内按支持项和部分支持项排序并结束本轮，不为满足全部偏好继续扫描

#### Scenario: Source exhausted or repeated page
- **WHEN** 上游无后续页或一整批没有新增 ID
- **THEN** 按 SOURCE_EXHAUSTED 或 NO_NEW_CANDIDATES 结束并保存状态

### Requirement: Existing table persistence and compatibility
系统 SHALL 复用现有消息、计划、澄清及运行表，以版本化 JSON 保存匹配数据，不新建表、不改字段、不执行迁移。所有读取路径 SHALL 区分 V1 与 V2，旧历史保持可读，未知版本明确报错。

#### Scenario: Mixed legacy and matching history
- **WHEN** 同一会话同时包含旧搜索结果和新匹配结果
- **THEN** 各自按快照版本解析并显示；完整 checkpoint 不被传入旧 SearchResult 或直接暴露给前端

#### Scenario: Shared plan version sequence
- **WHEN** 同一会话普通搜索转匹配再转回普通搜索
- **THEN** 使用同一计划版本序列和活动运行指针，未修改条件保留，旧结果作为历史保留

### Requirement: Atomic progress checkpoints
系统 SHALL 在每个评估小批完成后以短事务保存候选状态、批内位置和消耗，游标不得越过未保存人选。事务不跨模型/网络等待，调用前预记消耗，停止或失败保留已提交进度。

#### Scenario: Partial page interrupted
- **WHEN** 十人一页仅完成前五人的评估后发生中断
- **THEN** 已完成五人和剩余缓冲可恢复，下一次继续不跳过后五人，不重复展示前五人

#### Scenario: Crash before commit
- **WHEN** 模型调用已结束但小批尚未成功提交即崩溃
- **THEN** 用户继续时允许重做未提交小批并去重，不声称未提交结果已保存

### Requirement: Continuation and idempotency
系统 SHALL 每次继续创建新 Run，继承同版本最新已提交进度，优先未展示池，再读后续资料，排除已展示人选。消息幂等键及关联 Run SHALL 持久化，不能从旧祖先运行分叉继续。

#### Scenario: Duplicate continue after reconnect
- **WHEN** 用户重复提交同一继续幂等键
- **THEN** 返回同一 Run，不重复消耗预算或追加结果组

#### Scenario: Stale ancestor continuation
- **WHEN** 已有后续运行却尝试从旧结果组继续
- **THEN** 返回 STALE_CONTINUATION 并指向最新运行，不重放已消费进度

#### Scenario: Cumulative limit
- **WHEN** 即将超过累计默认 10 轮、500 人或单快照 10 MiB
- **THEN** 按 CONTEXT_LIMIT 停止继续并提示新任务，不删除历史；上限可配置

### Requirement: Shared control and restart recovery
系统 SHALL 共用现有 TaskRegistry 取消和替代，业务状态从数据库恢复。启动时把遗留 V2 QUEUED/RUNNING 标为中断（FAILED/PROCESS_RESTARTED），保留进度，由用户主动继续，不自动重发模型调用。

#### Scenario: Restart and reopen
- **WHEN** 服务重启后用户重新进入会话
- **THEN** 无需原 sessionStorage 即可读取需求、历史分组及中断原因，继续时重新取得身份和凭据

#### Scenario: Controls during matching
- **WHEN** 匹配中收到闲聊、停止、进度或确认新需求
- **THEN** 闲聊不打断，其余作用于当前统一运行；旧结果不能覆盖新版本，必要短提交可完成

#### Scenario: Runtime state released
- **WHEN** 一轮任务完成、取消或进程重启
- **THEN** 内存 Task 和请求凭据被释放，后续从现有表重新加载，不删除业务历史或返回重启丢失错误

### Requirement: Authorized historical result access
系统 SHALL 对 V2 核对 tenant_id/user_id/session_id。默认轮询仅元数据；业务确认候选人均可查看且不删除，历史资料直接读取保存快照，继续直接恢复进度，不额外调用 Java 复核。凭据不落库。

#### Scenario: Historical results without repeated search
- **WHEN** 会话所有者读取历史结果
- **THEN** 返回保存的结果和证据，不额外调用 Java，不消耗检索预算

#### Scenario: Cross-tenant history access
- **WHEN** 同用户切换租户或其他用户读取 V2 历史
- **THEN** 拒绝访问，消息历史接口也不能绕过资料授权

### Requirement: Stable result groups
系统 SHALL 内部分页只更新进度，首次与每次继续各保存一组最终结果，展示需求版本、偏好证据、信息不足项、检查范围和停止原因。普通搜索保留原位分页。

#### Scenario: Five batches and refresh
- **WHEN** 一轮读取五批后刷新页面
- **THEN** 恢复一组最终汇总而非五条聊天结果，旧组不被后续需求修改覆盖
