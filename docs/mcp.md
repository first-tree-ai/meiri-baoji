# 薄肌教练排行榜 MCP

这个 MCP 分发排行榜规则、保存每天最终分数快照，并返回日榜和周榜。它不读取或计算用户的原始健康指标；用户自己的 Agent 按规则完成判断，只上传 0–100 分。

## 连接

部署后的 Streamable HTTP 地址是：

```text
https://<your-project>.vercel.app/api/mcp
```

请求必须带 `Authorization: Bearer <MCP_BEARER_TOKEN>`。令牌只放在客户端安全配置或秘密管理器，不写进仓库、群聊或日志。

服务端还需要：

```text
LARK_APP_ID
LARK_APP_SECRET
LARK_BASE_TOKEN
MCP_BEARER_TOKEN
MCP_ALLOWED_ORIGINS   # 可选，逗号分隔
```

## 工具

| 工具 | 用途 |
|---|---|
| `create_leaderboard` | 创建排行榜并装入已确认的三个默认维度 |
| `join_leaderboard` | 加入或重新加入 |
| `leave_leaderboard` | 离开；历史分数仍保留 |
| `get_leaderboard_definition` | 获取当前周期维度和必须使用的规则版本 |
| `add_dimension` | 创建者新增维度；MVP 不支持删除，下一周期生效 |
| `update_scoring_criteria` | 创建者用一段自然语言发布新版规则；下一周期生效 |
| `submit_daily_update` | 提交当前所有维度的分数和规则版本 |
| `get_leaderboard` | 读当前日榜或周榜 |

`submit_daily_update` 不接受客户端日期或时区。服务端按排行榜唯一的 IANA 时区决定当天；同一天再次提交会覆盖当天最终快照。`idempotency_key` 相同且内容相同视为安全重试，相同 key 配不同内容会被拒绝。

周榜是本周每天最终分数的累计，不是平均分。评分规则由 Agent 执行，MCP 不根据热量、体重、步数等原始指标自行算分。

## 已确认默认规则

- 饮食分：按用户已经确认的个性化饮食计划执行情况评分。
- 运动分：按训练与恢复计划评分；计划休息日默认 60 分。
- 薄肌分：饮食分 50% + 运动分 50%，四舍五入。
- 资料不足：先追问，不猜测、不把未知记为 0，也不要提交当天分数。
- 明显不健康行为：相关单项以及薄肌分最高 50 分。

创建者可以发布自然语言新版规则；服务端保留版本，并只从下一周周期开始使用。

## 本地验证

```bash
npm install
npm run check
npm test
npm run build
```

## 部署

安装 Vercel CLI，先以安全方式配置上述环境变量，再执行生产部署：

```bash
vercel --prod
```

不要把 Vercel token 或飞书 App Secret 放在命令历史、仓库文件或聊天消息里。部署后先访问 `/api/health`；只有返回 `ready` 才表示四项必要配置都已装入。随后用 MCP 客户端完成 initialize、tools/list 和一次只读调用。

当前 MVP 使用静态 Bearer token。Base 已预留 `OAuthRecords`，可存 DCR client、authorization code、access/refresh token 的哈希或加密引用；正式多租户开放前应切换为标准 OAuth，并且绝不在 Base 保存明文令牌。
