#!/bin/bash
# 用法: ./search.sh "查询名字叫安则休的人" [消息编号]
# 先执行：export TALENT_AGENT_COOKIE_TOKEN='当前登录令牌'
# 令牌只从环境变量读取，避免真实 Cookie 被误提交到代码仓库。

TOKEN="${TALENT_AGENT_COOKIE_TOKEN:?请先设置 TALENT_AGENT_COOKIE_TOKEN}"
CONTENT="${1:-查询杭州游卡网络技术有限公司工作过的人}"
# 不传编号时自动生成唯一幂等键，避免重复编号命中旧结果缓存。
MSG_ID="${2:-msg-$(date +%s)}"
SESSION="ses_1d4d157cee694840b2d2900aa7d79a62"

echo "=== 发送消息: $CONTENT"
curl -s -X POST "http://localhost:8000/api/v1/sessions/$SESSION/messages" \
  -H "X-User-Id: lihao" \
  -H "Content-Type: application/json" \
  -H "Cookie: authOpenIdToken=$TOKEN" \
  -d "{\"client_message_id\":\"$MSG_ID\",\"content\":\"$CONTENT\"}"

echo
echo "=== 最终结果:"
curl -s "http://localhost:8000/api/v1/sessions/$SESSION/result" -H "X-User-Id: lihao"
echo
