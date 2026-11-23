# 薄肌教练排行榜 MCP

这个 MCP 分发排行榜规则、保存每天最终分数快照，并返回日榜和周榜。它不读取或计算用户的原始健康指标；用户自己的 Agent 按规则完成判断，只上传 0–100 分。

## 连接

部署后的 Streamable HTTP 地址是：

```text
https://<your-project>.vercel.app/api/mcp
```

当前生产地址是 `https://meiri-baoji-leaderboard.vercel.app/api/mcp`。默认排行榜 ID 是 `thin-muscle-default`。

## 鉴权

openTag「Agent 身份」模式（team-context `personal-agent/mcp-auth-modes.md`，opentag#1941）：openTag 是授权服务器和客户端，本 MCP 是资源服务器，**什么都不用注册**。

- `/.well-known/oauth-protected-resource/api/mcp`（及根路径）返回 PRM：`resource` = 本 MCP 地址，`authorization_servers` = openTag issuer，`opentag_auth_mode: "agent"`；
- 未带令牌或令牌无效返回 401，`WWW-Authenticate: Bearer resource_metadata="<PRM 地址>"`；
- 令牌是 openTag 签发的 JWT，用 issuer discovery 里的 `jwks_uri` 校验签名，并校验 `iss`、`aud` = 本 MCP 地址、`exp`、有效期不超过 15 分钟、`opentag_subject_type` = `agent`；
- 身份 = `agent:<sub>`（openTag 给本 MCP 的 Agent ID，不同 MCP 之间无法关联）。工具不接受任何身份参数。

服务端环境变量：

```text
LARK_APP_ID / LARK_APP_SECRET / LARK_BASE_TOKEN   # 专用读写飞书应用 + Base
MCP_PUBLIC_URL                                    # 本部署的公开地址
OPENTAG_OAUTH_ISSUER                              # staging https://dev.opentag.build/api/v1/auth，prod https://app.opentag.build/api/v1/auth
MCP_ALLOWED_ORIGINS                               # 可选，逗号分隔
```

前提：目标环境的 openTag 已上线 MCP Agent 身份模式（opentag#1941）。

## 工具

| 工具 | 用途 |
|---|---|
| `create_leaderboard` | 创建排行榜并装入已确认的三个默认维度 |
| `join_leaderboard` | 加入或重新加入 |
| `leave_leaderboard` | 离开；历史分数仍保留 |
| `get_leaderboard_definition` | 加入时或跨周期/stale 后获取当前周期维度和必须使用的规则版本 |
| `add_dimension` | 创建者新增维度；MVP 不支持删除，下一周期生效 |
| `update_scoring_criteria` | 创建者用一段自然语言发布新版规则；下一周期生效 |
| `submit_daily_update` | 提交当前所有维度的分数和规则版本 |
| `get_leaderboard` | 读当前日榜或周榜 |

`submit_daily_update` 不接受客户端日期或时区。服务端按排行榜唯一的 IANA 时区决定当天；同一天再次提交会覆盖当天最终快照。`idempotency_key` 相同且内容相同视为安全重试，相同 key 配不同内容会被拒绝。

参与者 Agent 应在加入排行榜时获取一次 definition，并在本地按排行榜缓存 `current_cycle_start`、`next_cycle_start`、维度、标准和版本。同一周期内复用缓存；每次餐食或训练打卡可以即时更新本地分数，但不要重复取规则。到 `next_cycle_start` 后，在新周期首次提交前刷新。如果提交返回 `STALE_CRITERIA`，刷新 definition、重算全部分数，并用新幂等键重提一次。没有任何 active membership 时，只按已确认默认规则本地评分，不调用 MCP、不上传分数。

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

不要把 Vercel token 或飞书 App Secret 放在命令历史、仓库文件或聊天消息里。部署后先访问 `/api/health`；只有返回 `ready` 才表示上述必要配置都已装入。随后让 openTag Agent 挂载此 MCP，完成 initialize、tools/list 和一次只读调用。若项目启用了 Vercel Deployment Protection，还需要在 Vercel 侧为正式 MCP 客户端放行，不能把保护绕过令牌写进仓库或群聊。
