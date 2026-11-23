# 飞书 Base Schema

Base 名称：`薄肌教练排行榜`。Base 自身时区设为 `Asia/Shanghai`，每个排行榜仍在 `Leaderboards.timezone` 保存自己的唯一 IANA 时区，所有归档和周周期以该字段为准。

当前 Base：`https://unispark.feishu.cn/base/OzoibyVbga3xXQsthFrcLBuwnkd`，由 engtag 的 bot 身份创建。MCP 通过一个专用的读写飞书应用访问它，该应用以可编辑文档应用的身份加入 Base。默认排行榜 ID 是 `thin-muscle-default`（已预置 3 个默认维度和 v1 标准）。

## Leaderboards

`leaderboard_id`、`name`、`timezone`、`cycle_anchor_date`、`status`、`creator_subject`、`created_at`、`updated_at`。

## Dimensions

`dimension_id`、`leaderboard_id`、`name`、`description`、`aggregation`、`active_from_cycle`、`is_composite`、`composite_definition`、`created_at`。

维度只新增不删除。新增维度从下一周期生效。

## CriteriaVersions

`criteria_version_id`、`leaderboard_id`、`dimension_id`、`version`、`criteria_text`、`policy_status`、`effective_from_cycle`、`created_by`、`created_at`。

规则按维度独立版本化。`criteria_text` 是创建者给出的自然语言标准；新版从下一周期生效。

## Members

`membership_id`、`leaderboard_id`、`member_subject`、`display_name`、`status`、`joined_at`、`left_at`、`updated_at`。

## DailyScores

`submission_id`、`leaderboard_id`、`member_subject`、`local_date`、`scores_json`、`idempotency_key`、`submission_hash`、`submitted_at`。

只追加：每次提交写**一行**，`scores_json` 里是当次全部维度（`[{dimension_id, score, criteria_version_id}]`），所以一次提交要么整份写入、要么没写，不会出现部分维度。`submission_id` = `leaderboard_id:member_subject:local_date:idempotency_key`，只用于人工查看。

Base 没有唯一约束，多个实例并发提交可能让同一人同一天有多行。读取时每个 `(member_subject, local_date)` 只取一行作为最终快照：`submitted_at` 最大者，相同再比 `idempotency_key`、记录 ID，所有实例结果一致，不会重复累计。当天已处理过的幂等键都保留：同 key 同内容的重放视为成功且不改变最终快照，同 key 不同内容被拒绝。

`member_subject` 是服务端从 openTag 访问令牌得到的身份（`agent:<openTag 给本 MCP 的 Agent ID>`），不来自工具参数，也不会出现在排行榜返回结果里。鉴权不需要表。
