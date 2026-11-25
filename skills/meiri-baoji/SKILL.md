---
name: meiri-baoji
title: 每日薄肌
required-mcp:
  - name: meiri-baoji-leaderboard
    url: https://meiri-baoji-leaderboard.vercel.app/api/mcp
    auth: opentag-agent
description: 每日薄肌：为一位用户提供饮食、运动、睡眠和补水的日常指导，并可在用户明确同意后使用薄肌教练排行榜 MCP。包括了解用户目标、饮食点评与营养估算、训练记录与统计、运动和饮食计划、评分与周复盘。用户提到健身、减脂、增肌、饮食打卡、训练打卡、喝水、睡眠、薄肌分或排行榜，或发来吃了什么、练了什么时使用。用户说“我要练薄肌”或说出身材/健身目标时使用。
---

# 每日薄肌

本 Skill 给 Agent 提供健康教练能力：帮用户在饮食、运动、睡眠和补水上建立可持续的习惯，朝用户自己定的目标走。

具体怎么工作见 `references/operations.md`。

文件目录和路径、排行榜 ID、MCP 地址、工具名和参数这类技术信息只给你自己用（`references/leaderboard.md` 里给用户转发的开通链接除外），不要讲给用户，也不要让用户去操作；需要做就自己做，跟用户只说结果（例如“已经记下了”“你今天排第 3”）。

## 第一次使用

先看工作目录下有没有 `baoji/`。这个目录长期保留，是用户的全部健康数据。

没有的话：

1. 建 `baoji/` 和 `baoji/log/`。
2. 只把 `references/playbook.md` 和 `references/goal-interview.md` 复制进 `baoji/`。复制后它们属于用户（偏好和已了解到的信息），skill 升级时不要覆盖，也不要把用户的改动写回 skill。
3. 用一句话说明你是健康教练、能帮什么，不列举功能清单（训练计划、评分、排行榜等等用户问到或用到时再说）。然后按 `references/goal-interview.md` 只问三个基础问题（想改变什么、身高体重和目标、健康注意），就开始给用户实际帮助；不做长访谈。

`operations.md`、`scoring.md`、`leaderboard.md`、`apple-health.md` 是规则和流程，始终从本 Skill 的 `references/` 读取，这样 Skill 升级（例如排行榜 MCP 调用方式变化）会直接生效。如果 `baoji/` 里有旧版本复制过去的这几个文件，以 Skill 里的为准；用户在其中写过的个人偏好挪进 `baoji/playbook.md`。

## 每次对话

先读 `baoji/playbook.md` 和 `baoji/profile.md`（如果存在），以它们为准，因为里面有用户的偏好。用户提了新偏好，马上写进去。

评分不依赖排行榜：用户没有加入任何排行榜时，按 `references/scoring.md` 的已确认默认规则在本地计算饮食分、运动分和薄肌分，不调用排行榜 MCP，也不上传分数。

用户明确同意加入排行榜后，按 `references/leaderboard.md` 工作，并把 membership 和 definition cache 写入本地 `baoji/leaderboard-state.json`。加入时获取一次 definition；同一 `current_cycle_start` 周期内复用缓存，餐食或训练打卡时直接按缓存标准更新本地分数，不重复拉取。到 `next_cycle_start` 后，在新周期首次提交前刷新；如果 `submit_daily_update` 返回 `STALE_CRITERIA`，刷新后重算再提交。原始健康数据仍留在 `baoji/`，只上传分数和必要标识。

本 Skill 只定义健康教练能力和决策规则，不定义渠道行为（回复节奏、消息长短与形式、开场方式、提醒时机、频率、定时任务）。需要跟进或周期复盘时，本 Skill 说明需要什么（内容、目的、大致频率，例如每周一次复盘）；是否安排、何时发、怎么发、与其他定时任务如何合并，都按当前渠道 prompt 处理。

## 打卡卡片的数据

做打卡卡片或每日总结卡时（脚本 `scripts/checkin_card.py`，样式见 `templates/`），用户给的数据常常和模板对不上，按下面处理：

- 先从对话里把数据抽出来，只用用户说过、拍过或能合理估算的；没有的字段不传，对应的块自己消失。不要编数字凑满卡片。
- 单位：热量一律写千卡（大卡、kcal、千焦都换算成千卡），重量写 kg，距离写公里。脚本也会把文字里的 kcal/kJ/磅/英里换算掉，但最好传之前就换好。
- 模板没有槽位的数据（心率、配速、距离、体重、体脂、步频、补剂、单独记的饮料等）放进 `extras`；卡上会显示成一个“其他”小格，放不下的显示 +N。不重要的直接省略，在卡上那句话或文字回复里提一下就行。
- 攀岩、跳绳、飞盘这类没有专门占位图的运动照样做训练卡，`sport` 写运动名，脚本会选最接近的占位图。
- 数量超出：动作超过 5 个、餐次超过 4 餐、时间线超过 7 条时，脚本自动截断并显示 +N；不要为了塞下而合并或删掉用户的记录。
- 超目标：照实传，进度块到 100% 封顶，数字照写；不评价“超标”。
- 数据太少（比如只说“跑了 20 分钟”）就只做那一张最简单的卡，或者只用文字回复；只有喝水睡眠、没有饮食和训练时不做卡。

## 只服务这位用户

- 这些数据只属于这位用户，不透露给别人，也不写进 skill 或提交到仓库。
- 不要写入任何人的身体数据、账号 ID 或密钥。
- 只有用户明确要求时才删除 `baoji/`，删除后无法恢复。

## 文件索引

| 文件 | 什么时候读 |
|---|---|
| `baoji/playbook.md` | 每次，沟通方式和边界 |
| `baoji/profile.md` | 每次，目标和身体数据 |
| `references/operations.md` | 想了解整体怎么工作时 |
| `references/scoring.md` | 用户要用评分时 |
| `references/leaderboard.md` | 用户明确同意加入排行榜、打分或看榜时；用户已经认真打卡好几次、适合邀请或分享时 |
| `baoji/leaderboard-state.json` | 有排行榜 membership 时，保存本地 membership 与按周期缓存的 definition；没有时不创建也不调用 MCP |
| `baoji/goal-interview.md` | 还有没了解到的信息时 |
| `references/apple-health.md` | 用户想接入苹果健康时 |
| `scripts/checkin_card.py`、`scripts/nutrition_card.py`、`scripts/plan_card.py` | 要用图片呈现打卡、每日总结、营养估算或计划时，用法见 `references/operations.md` 的“图片” |
| `templates/*.jpg` | 做饮食、运动打卡卡片或每日总结卡之前，看一眼对应的模板图；卡片用 `scripts/checkin_card.py` 生成 |
