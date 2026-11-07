# Agent Study

每天围绕一个问题学习 Agent 应用开发：论文、官方文档、工程博客或开源模块，生成中文原理讲解、流程图和伪代码，保存到自己的飞书学习库。

**当前为 0.1.0-alpha。** 已在 Codex 中完成真实个人飞书建库、论文发布、图示回读、中断恢复和新本地目录恢复；33 个自动测试通过。Claude Code 实测因宿主登录过期未完成，其他验证边界见 [验证范围](references/verification.md)。

## 使用方式

安装后对宿主说：

- “配置我的 Agent 学习。”
- “开始今天的学习。”
- “学习这篇论文。”
- “这篇读完了，下一步学什么？”
- “比较我读过的几种记忆方案。”
- “看看这篇文档里我写的问题。”

当前一篇未读完时不会自动生成下一篇。文档顶部的“已读”是原生勾选框：勾选表示已读，普通“已读”框取消勾选表示待学习；下次调用 Skill 时读取生效。阅读中、跳过仍可通过对话设置，未勾选时会在标签中注明当前状态。你的感悟由你填写，只有主动请求时 AI 才读取和讨论。更换电脑后，用学习首页链接恢复配置与进度。

## 安装

依赖：Python 3.10+、[官方 lark-cli](https://github.com/larksuite/cli)，以及能联网研究、读写文件、执行脚本的 Skill 宿主。Python 代码仅使用标准库；Windows 缺少 IANA 时区数据时安装 `tzdata`。

```sh
# Codex 示例；如果已存在同名目录，请先检查，不要覆盖。
git clone https://github.com/xunagent/agent-study.git ~/.codex/skills/agent-study
python3 ~/.codex/skills/agent-study/scripts/study.py doctor
```

Claude Code 可安装到 `~/.claude/skills/agent-study`。其他遵循 [Agent Skills 规范](https://agentskills.io/specification) 的宿主按各自目录规则安装；规范兼容不代表已完成实测。重启或刷新宿主的 Skill 列表后调用。

首次使用由 Skill 问答配置。真实配置和草稿保存在仓库外，凭据由 lark-cli 管理。完整步骤见 [初始化与恢复](references/setup.md)。

流程图默认使用宿主图像生成能力，采用白底、石墨线条与淡彩蜡笔手绘风格，中文标签。保留结构化图源和生成提示词；发布前逐条核对连线。成品为位图，不能逐个编辑节点。没有图像生成能力的宿主会说明限制，由用户选择替代方式。详见 [绘图与发布](references/diagram-style.md)。

## 数据与调度

飞书目录包含首页、配置、路线、索引、阅读历史、运行记录和每篇笔记。笔记链接保留原文；用户感悟与 AI 讨论分别位于独立章节。材料版本更新追加到原笔记。

定时任务由 Codex、Claude 或其他宿主的已有能力触发。Skill 输出定时提示词，不安装后台服务。默认通过宿主通知；飞书消息是另行授权的可选宿主能力，Python 脚本不发送消息。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
python3 scripts/study.py validate assets/react.example.json
python3 scripts/study.py validate assets/claude-loop.example.json
python3 scripts/study.py diagram assets/react.example.json --output /tmp/agent-study-react.svg
```

`SKILL.md` 负责编排和行为规则；`scripts/agent_study` 负责内容校验、飞书适配与恢复；`assets` 是不含个人数据的结构示例；`references` 提供按需阅读的指引。

示例基于 [ReAct](https://arxiv.org/abs/2210.03629v3) 与 [Claude Code 官方循环说明](https://code.claude.com/docs/en/how-claude-code-works#the-agentic-loop)，篇幅短于正式学习内容，用来展示结构与出处标注，不表示最新推荐。

当前索引采用追加快照，适合初版个人库；长期大量材料需要后续归档优化。跨设备并发有冲突检测，不承诺严格只创建一份。故障处理见 [恢复说明](references/recovery.md)。

MIT License。第三方材料归原作者，本仓库保留来源链接，不收录全文。
