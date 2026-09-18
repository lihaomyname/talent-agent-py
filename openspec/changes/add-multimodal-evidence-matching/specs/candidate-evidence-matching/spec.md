## ADDED Requirements

### Requirement: Minimal candidate profiles
系统 SHALL 从授权列表响应提取教育和工作经历用于匹配，去重 duty/detail，不将联系方式、年龄、性别及内部操作人送入匹配模型，不记录原始宽响应。

#### Scenario: Duplicate and sensitive fields
- **WHEN** 返回包含重复描述以及 mobile、resumeBaseAppMobile、email、resumeBaseAppEmail
- **THEN** 描述只保留一份，上述联系方式不进入模型或明文日志

#### Scenario: Profile data stays outside legacy snapshots
- **WHEN** 匹配专用检索返回完整工作经历
- **THEN** 必要资料及证据通过匹配 V2 快照保存在现有运行表，不扩展或改写旧 V1 CandidateCard/SearchResult 快照，不保存整个招聘响应

#### Scenario: Missing experience still allows card rendering
- **WHEN** 返回有候选人卡片但没有经历描述
- **THEN** 卡片正常展示，相关核验项标为信息不足，不生成虚构经历

### Requirement: Traceable evidence
系统 SHALL 为每项要求返回 SUPPORTED、PARTIAL、UNKNOWN 或 CONTRADICTED，并在声称有证据时提供实际存在的来源字段及短引用。缺少描述不能判定为明确不符合。

#### Scenario: Related experience is insufficient
- **WHEN** 简历仅写“搜打撤 + MOBA”或角色技能设计，要求是枪械后坐力调优
- **THEN** 不判该要求为 SUPPORTED，并解释缺少射击调优证据

#### Scenario: Unsupported quote
- **WHEN** 模型引用不存在的工作经历片段
- **THEN** 校验拒绝该证据，有限修复失败后记录评估失败，不能将该候选人作为已确认满足者

#### Scenario: Incomplete duration
- **WHEN** 任职两年但未说明射击工作持续多久，或日期含义未知
- **THEN** 不把两年全部计入射击经验，标记该年限要求信息不足

### Requirement: Fixed filters and preference ordering
系统 SHALL 只使用 SearchConditions 固定字段强制筛选。技术栈、语言、工具、项目经验和软能力均作为偏好；缺失、未知、部分支持或矛盾不淘汰已经被固定条件召回的人选。偏好只影响确定性排序，同分沿用召回顺序，不生成无依据总分。

#### Scenario: Preference is absent
- **WHEN** 候选人被固定条件召回但没有 UGC 证据
- **THEN** 不因缺少偏好淘汰，在偏好匹配更好的合格人选之后展示

#### Scenario: Strict seniority limit
- **WHEN** 用户明确总工龄不得超过三年
- **THEN** 该范围进入固定 work_years 搜索条件；工作经历描述只补充证据，不在匹配层重复淘汰

#### Scenario: Programming language absent
- **WHEN** 教育和工作经历没有写 Python、Java 或 Go
- **THEN** 对应偏好标为 UNKNOWN，候选人仍展示，不能推断其不熟悉该语言
