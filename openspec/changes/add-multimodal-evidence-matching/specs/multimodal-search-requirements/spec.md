## ADDED Requirements

### Requirement: Unified requirement extraction
系统 SHALL 从自然语言或截图提取可执行固定筛选、证据偏好、歧义及各项原文依据。只有 SearchConditions 支持的字段是强制条件，其余要求统一作为偏好。

#### Scenario: Experience and preference in text
- **WHEN** 输入“找战斗策划，必须有射击项目经历，UGC 经验优先”
- **THEN** 职位进入固定筛选，射击经历和 UGC 均进入偏好，三者保留来源

#### Scenario: Job metadata is not candidate restriction
- **WHEN** 截图包含岗位杭州、招聘方网易、总工龄 0–3 年及射击经验一年以上
- **THEN** 系统不自动生成候选人现居杭州或网易经历条件，分别表达总工龄和射击经验，影响准入的口径不清时澄清

### Requirement: Image validation and model boundary
系统 SHALL 验证图片格式、真实解码、体积与像素限制，通过独立配置的 `deepseek-flash` 视觉适配器提取原文和结构，不执行截图中的指令，不保存原始图片到长期存储。

#### Scenario: Unsupported gateway
- **WHEN** 实际网关不支持图片输入
- **THEN** 返回明确图片能力错误，不调用纯文本模型猜测图片内容

#### Scenario: Invalid or unreadable image
- **WHEN** 图片超限、文件内容与类型不符或关键文字无法辨认
- **THEN** 无效文件在模型调用前拒绝，无法辨认内容标记待确认，均不触发搜索

### Requirement: Confirmation routing and revision
系统 SHALL 在截图解析后展示紧凑、可编辑的需求供确认；明确且仅含可执行条件的自然语言 SHALL 沿用普通搜索，包含证据偏好时进入匹配。

分流 SHALL 根据当前完整需求应用增量后的结果，与输入介质无关。控制指令 SHALL 先按会话活动模式处理，不重新解析成搜索需求。

系统 SHALL 支持卡片与对话一致的增删改及分类调整，字段缺失表示保留，删除须显式表达。确认后的每次变更保存新计划版本，旧版本和结果保留；只打开编辑不打断任务。

#### Scenario: Edit and confirm a preference
- **WHEN** 用户打开卡片、修改偏好、最后确认提交
- **THEN** 仅确认后保存新版本并替代旧运行，旧结果仍可查看，不能以旧游标继续新版本

#### Scenario: Soft skill preference
- **WHEN** 截图包含沟通、抗压或责任心要求
- **THEN** 作为偏好保存；教育和工作经历没有证据时显示 UNKNOWN，不淘汰候选人

#### Scenario: Restore requirements after restart
- **WHEN** 服务重启后用户打开已有会话
- **THEN** 从现有计划和消息表恢复已确认条件及偏好，从澄清表恢复未确认草稿

#### Scenario: Confirm a filter-only screenshot
- **WHEN** 用户确认只有职位、学历和总工龄的截图，且没有歧义、核验项或偏好
- **THEN** 已校验结构直接交给普通搜索，不进行自然语言二次解析或候选人匹配

#### Scenario: Round trip between search modes
- **WHEN** 当前普通搜索为本科及现居杭州，用户追加 UGC 优先，随后移除该偏好
- **THEN** 转入匹配及返回普通搜索均保留本科与现居杭州，返回时废弃旧匹配游标，沿用 V1 既有持久化契约

#### Scenario: Modify a filter during matching
- **WHEN** 匹配任务包含 UGC 偏好，用户说“只看本科”
- **THEN** 保留 UGC 偏好并更新学历，继续匹配模式，不按本条消息孤立分流

#### Scenario: Simple text search
- **WHEN** 用户只指定现有九类支持字段且无歧义
- **THEN** 沿用现有搜索及分页，不调用候选人匹配模型

#### Scenario: Change a preference
- **WHEN** 用户修改已有匹配需求的偏好
- **THEN** 未提及要求保持不变，需求版本增加，旧任务及继续游标失效
