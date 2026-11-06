# 每日薄肌

一个 [openTag](https://github.com/first-tree-ai/opentag) local Agent skill，让你的 Agent 成为你的私人薄肌助手：目标访谈、饮食打卡和打分、训练记录、每天变着花样的提醒。

每人用自己的 Agent 和自己的电脑，健康数据只存在你的 Agent 工作目录的 `baoji/` 下。这个仓库里没有任何人的数据，也不要提交。

## 安装

在飞书或 Slack 里对你的 openTag Agent 说：

> 把 first-tree-ai/meiri-baoji 克隆到工作目录外的一个文件夹，运行 `opentag skill push <克隆路径>/skills/meiri-baoji`，然后开始用它。

Agent 需要有这个仓库的读取权限。

## 更新

对你的 Agent 说：

> 在 meiri-baoji 的克隆目录运行 `git pull`，再运行 `opentag skill push skills/meiri-baoji --replace`。

更新只替换 skill。你的 `baoji/` 数据和个性化设置不受影响，但也不会自动用上新模板。如果想要新版的某部分，让 Agent 对比后合并。

## 修改

改 `skills/meiri-baoji/` 下的文件，然后提 PR。个人偏好不用提 PR，直接告诉你的 Agent。

`SKILL.md` 是入口，`references/` 是复制给每个人的初始模板。

## 注意

使用是自愿的。健康数据属于敏感个人信息，消息内容会由你的 Agent 所用的模型服务处理。助手不是医生，身体有问题请就医。
