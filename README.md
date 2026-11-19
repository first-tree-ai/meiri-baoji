# 每日薄肌

一个 [openTag](https://github.com/first-tree-ai/opentag) local Agent skill，让每个人自己的 personal agent 在饮食、运动、睡眠和补水上给你日常指导：目标访谈、饮食点评和营养估算、训练记录、运动和饮食计划、提醒与周复盘。整体怎么工作见 [运营方式](skills/meiri-baoji/references/operations.md)。

每人用自己的 Agent 和自己的电脑，健康数据只存在你的 Agent 工作目录的 `baoji/` 下。这个仓库里没有任何人的数据，也不要提交。

## 安装

在飞书或 Slack 里对你的 openTag Agent 说：

> 把 first-tree-ai/meiri-baoji 克隆到工作目录外的一个文件夹，运行 `opentag skill push <克隆路径>/skills/meiri-baoji`，然后开始用它。

Agent 需要有这个仓库的读取权限。

## 更新

对你的 Agent 说：

> 在 meiri-baoji 的克隆目录运行 `git pull`，再运行 `opentag skill push skills/meiri-baoji --replace`。

更新只替换 skill。你的 `baoji/` 数据和个性化设置不受影响，但也不会自动用上新模板。如果想要新版的某部分，让 Agent 对比后合并。

## 薄肌教练排行榜 MCP

仓库同时包含一个 Vercel HTTP MCP：分发评分规则、保存每天最终分数快照，并返回日榜和周榜。它不接收原始健康指标，也不自行判断热量、步数或体重变化；每个用户的 Agent 按规则上传 0–100 分。

已确认的默认维度是饮食分、运动分和薄肌分。薄肌分默认饮食 50% + 运动 50%；计划休息日运动默认 60；明显不健康行为时，相关单项以及薄肌分封顶 50。资料不足时先追问，不猜测、不按零分。

排行榜不是本地评分的前提：没有加入排行榜时，Agent 仍按上述默认规则在本地评分，但不调用 MCP、不上传分数。加入后按周缓存 definition，一日三餐和训练打卡不重复拉规则；只在跨周期或服务端返回 stale criteria 时刷新。

连接、工具、环境变量和部署步骤见 [MCP 使用说明](docs/mcp.md)，Base 表结构见 [Base Schema](docs/base-schema.md)。

## 修改

改 `skills/meiri-baoji/` 下的文件，然后提 PR。个人偏好不用提 PR，直接告诉你的 Agent。

`SKILL.md` 是入口，`references/` 是复制给每个人的初始模板。

## 注意

使用是自愿的。健康数据属于敏感个人信息，消息内容会由你的 Agent 所用的模型服务处理。助手不是医生，身体有问题请就医。
