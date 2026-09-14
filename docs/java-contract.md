# Java eTalent 接口契约假设

Python 侧保留实体解析操作，并直接复用现有招聘人才分页接口：

```text
POST /internal/agent/search/resolve-entities
POST https://zhaopin.netease.com/api/eTalent/talent/list/page
```

人才分页接口通过当前用户的 `authOpenIdToken` Cookie 鉴权。Python 只允许将该 Cookie 透传到配置的招聘域名，不在配置、数据库或日志中保存令牌，也不信任普通请求体中的操作人字段。

实际响应为 `Result<PageResult<TalentResumeVO>>`。Python 会解包 `code/data`，读取 `data.list/total/pages/lastPage`，并把宽版 `TalentResumeVO` 收敛为安全候选人卡片；手机号、邮箱、证件号、微信等字段不会进入 Agent 结果。

直连模式下，城市通过 `GET /api/eTalent/option/city` 获取权威 ID；学历编码与 `SocialDegreeTypeEnum` 保持一致；公司、学校和院校级别以 `TEXT` 名称交给 `TalentController.convertText2Label` 使用现有标签能力转换。后续若建设专用 `resolve-entities` 接口，可关闭 `TALENT_AGENT_JAVA_DIRECT_BROWSER_API` 恢复统一解析端口。

## 已按现有源码实现的映射

| SearchPlan | Java 字段 | 当前约定 |
|---|---|---|
| 姓名 | `applicantName` | 通过 `strictApplicantName` 控制精确/模糊 |
| 候选人职位 | `nowPosition` | `onlyNowPosition` 控制仅当前或当前/历史 |
| 最低学历 | `topDegree` | Java 返回真实学历 code；本科示例为 `06` |
| 工作年限 | `workYearsMin/Max` | 不发送虚构的 `workYears` 数组 |
| 公司 | `nowCompany` | 使用 Java 返回的 LABEL code |
| 学校 | `school` | 使用 Java 返回的 LABEL code |
| 现居住地 | `livePlace` | 整数城市 ID |
| 期望工作地 | `expectWorkPlace` | 字符串城市编码 |
| 院校标签 | `schoolLevelList` | `firstDegree` 控制第一学历范围 |

## 联调前必须确认

1. 工龄单边界是包含还是不包含临界值。
2. `nowPosition` 空格拆词后的 ALL 语义是否符合产品预期。
3. 公司、学校和院校标签多值是否按 OR 执行。
4. 城市字典 ID 在现居和期望字段中的正式类型。
5. Java 内部接口的统一响应包裹、错误码和超时约定。
6. 浏览器接口 `/talent/list/page` 是否由内部 facade 复用，而不是让 Python 模拟浏览器调用。

上述事项必须通过非生产环境契约测试后再开启功能开关。
