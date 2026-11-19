# 飞书 Base Schema

Base 名称：`薄肌教练排行榜`。Base 自身时区设为 `Asia/Shanghai`，每个排行榜仍在 `Leaderboards.timezone` 保存自己的唯一 IANA 时区，所有归档和周周期以该字段为准。

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

`score_snapshot_id`、`leaderboard_id`、`member_subject`、`local_date`、`dimension_id`、`score`、`criteria_version_id`、`idempotency_key`、`submission_hash`、`submitted_at`、`updated_at`。

逻辑唯一键是 `(leaderboard_id, member_subject, local_date, dimension_id)`。同日重复提交更新同一行，使日榜和周榜始终使用当天最终分数。

## OAuthRecords

`oauth_record_id`、`record_type`、`client_id`、`client_name`、`redirect_uris_json`、`grant_types_json`、`response_types_json`、`token_endpoint_auth_method`、`secret_hash`、`subject`、`scopes`、`redirect_uri`、`expires_at`、`used_at`、`status`、`metadata_json`、`created_at`、`updated_at`。

`record_type` 可取 `dcr_client`、`authorization_code`、`access_token`、`refresh_token`。只保存不可逆哈希、密文或外部秘密引用，不保存明文 client secret、authorization code 或 token。
