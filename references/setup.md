# 初始化、安装与恢复

## 宿主前提

需要 Python 3.10+、联网检索/读取、文件读写、脚本执行，以及官方 [lark-cli](https://github.com/larksuite/cli)。脚本本身不调用大模型 API，也不包含网页抓取器；使用当前宿主的搜索、浏览和源码阅读能力。任何能力缺失都具体报告，不生成假摘要。

将仓库目录作为 Skill 安装到宿主识别的 skills 目录；目录名保留 `agent-study`。Codex 可使用 `~/.codex/skills/agent-study`；Claude Code 可使用 `~/.claude/skills/agent-study`。也可在宿主支持的位置使用符号链接。检查既有目录，避免覆盖其他安装。

运行 `python3 scripts/study.py doctor`。Lark CLI 初次配置/授权使用其当前版本内置指南：

若 `python3` 指向 3.9 或更旧版本，改用已安装的 `python3.12`，或 `uv run --python 3.12 python scripts/study.py ...`；不要让旧版本运行写入命令。

```sh
lark-cli skills read lark-shared
lark-cli auth status --json --verify
```

展示账户名称和目标个人目录，由用户确定。配置登录凭证由 CLI 自己保管；不复制到 Skill、Git 或学习文档。仅在缺少权限时申请需要的 docs/drive 权限，画板预览所需权限按 CLI 错误补充。所有资源操作以 `--as user` 执行。授权 URL/二维码使用 CLI 当次输出，遵循其 split-flow，不循环发起授权。

若授权页提示“没有应用的使用权限”，这是应用可用范围问题，重复补 scope 无法解决。已有工作账号配置时，先 `lark-cli profile list`，为个人账号创建独立命名配置：`lark-cli config init --new --name agent-study-personal --brand feishu`。不要执行会替换已有配置的无名称初始化，也不要切换全局默认账号。

若网页显示创建成功但回传链接失效，复用已创建应用。用户可在自己的终端运行 `python3 scripts/bind_profile.py --profile agent-study-personal --app-id <已创建应用ID>`，将 App Secret 粘贴到隐藏输入框，不要发到聊天或写进配置文件。脚本通过 stdin 交给官方 CLI 保存。

第一次运行学习命令时显式指定 `python3 scripts/study.py --profile agent-study-personal init ...`。此选择会保存到私有本地状态，之后 daily 等命令自动沿用。新设备恢复时重新选定本机 profile，云端不保存本机账号配置。

## 初次问答

每轮最多询问 2～3 个相关问题，普通对话即可，不依赖某宿主独有问答工具。已有答案沿用。收集：

1. 已有基础、学习目标、优先主题和关注产品。默认路线为执行循环 → 工具调用 → 上下文管理 → 记忆与检索 → 规划与长任务 → 多 Agent 协作 → 评测 → 工程可靠性。
2. 语言、单篇时长、时区；默认中文、10 分钟。不能从语言猜时区。
3. 个人飞书目录链接及当前登录账户是否匹配。不要默认工作账号就是个人账号。
4. 是否启用宿主定时、时间（建议当地 09:00）、通知渠道。无宿主定时能力时说明仅手动运行；不要宣称已配置自动任务。

配置结构见 `assets/config.example.json`。将真实配置放到仓库外，例如 `~/.local/share/agent-study/config.json`。Windows 可通过 `--state-dir` 指定私有目录。每个学习库使用独立状态目录。

```sh
python3 scripts/study.py validate /private/path/config.json --config
python3 scripts/study.py init --folder FOLDER_TOKEN --config /private/path/config.json
python3 scripts/study.py schedule-prompt
```

初始化创建首页、配置、路线、材料索引、主题索引、阅读历史和运行记录。首页含恢复描述。索引使用追加快照，最后一个快照为最新，用户添加内容保留；配置修改通过 `configure`，不要手工修改运行记录中的 JSON。单篇状态段落可以直接改成四个状态之一。

生成路线后解释前置依赖，允许调整配置中的主题顺序。主题推进由宿主依据已读材料和前置知识判断，通过 `topic` 落盘，不能假定每读一篇就掌握整个模块。

## 换设备

在新设备安装 Skill 和 lark-cli，登录同一个有权限的用户：

```sh
python3 scripts/study.py restore 'https://your-domain.feishu.cn/docx/HOME_TOKEN'
python3 scripts/study.py daily
```

已发布正文、配置、候选、当前篇及阅读状态在云端。本地故障日志可重建。发布开始前的草稿只在原设备；开始发布后原始结构化草稿保存在云端运行记录，`daily` 会提示 `resume <operation>`，可在新设备继续。

## 定时与通知

`schedule-prompt` 生成可复制的提示词，并返回时间及时区。使用宿主正式定时功能建立任务；在首次配置时说明宿主是否支持休眠补跑/开机补跑。一个学习库只启用一个自动端。配置 `enabled: true` 本身不会创建任务。

默认通过宿主通知展示结果，不额外发飞书消息。`notification: none` 不发额外通知。选飞书消息时先明确 `chat_id` 和发送身份，并要求用户明确授权发送；`notification: feishu` 只是偏好记录。宿主须使用已安装且可用的飞书消息工具，读取其当前指南，发送标题、推荐原因和已有笔记链接。脚本不内置消息发送，以免把内容发布权限误用成发消息权限。若没有工具能力，保留文档并报告通知未发送，不伪称推送成功。
