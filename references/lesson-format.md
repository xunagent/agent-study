# 结构化学习内容

以 `assets/react.example.json` 或 `assets/claude-loop.example.json` 为结构示例；它们是较短的公开样例，真实每日笔记需要按用户时长扩展。不要复用其访问日期来表示今天已核实。

必填字段：

| 字段 | 约束 |
| --- | --- |
| title / summary / recommendation | 标题、短摘要、为什么现在学 |
| source | kind、url、title、authors、version、accessed_at、locator、reading_scope |
| source.kind | paper / official_doc / official_blog / source_code |
| source.reading_scope | full_text / relevant_sections / source_code；摘要不能正式发布 |
| topics | 至少一个，关联学习路线 |
| sections | why、problem、claims、solution、evidence、application 六段 |
| diagram | nodes 数组（id,label）；edges 数组（from,to,label 可选） |
| pseudocode | code、basis、explanation |
| references | url、claim、locator、basis 的数组 |
| reviewed | 人工/宿主核对原始材料后设为 true |

`accessed_at` 为 ISO 日期。源码 `version` 为 7～40 位 commit hash。官方文档无版本号时可用 `accessed-YYYY-MM-DD`；同一天多次实质更新加章节内容摘要哈希后缀。

`references.basis`：`author_claim` 作者或官方主张，`reported_evidence` 原文报告的实验，`implementation` 实际源码，`inference` 讲解者的推断。`pseudocode.basis`：`source_algorithm` 或 `teaching_reconstruction`。

## 内容表达

标题不带系统编号。材料信息压缩为摘要、原文链接、作者/材料类型/版本/主题的一行信息；阅读控件放在这一区域，不另设大标题。查阅日期是 AI 核对来源的日期，放入文末“证据定位”，不要暗示为论文发表日期或用户阅读日期。

发布器为每个材料版本建立独立“图示源文件”，保存 JSON 图源；图片发布器继续将生成 prompt 和图片指纹保存到该文档。正文流程图节只显示图，文末提供源文件链接。算法伪代码是学习内容，仍留在正文。旧笔记迁移先复制并回读源文件，再按原块内容和版本校验后移除正文中的技术记录，保留用户修改及图像资源。

中文默认正文约 1500～2500 字，术语首次出现时解释。围绕具体场景推进问题—机制—证据—适用边界。图和代码帮助解释状态变化，不用长段落重复同一意思。复杂推导放文末扩展段（可放相应 sections 字符串后半部分）。其他语言依用户时长控制长度。

图为简单机制图，2～8 个节点，ASCII 唯一 ID，节点标签尽量 18 字以内（硬上限 30），边标签尽量 6 字以内。默认按 [diagram-style.md](diagram-style.md) 生成 AIGC 手绘图，并保留提示词和 JSON 图源。脚本 SVG 是结构预览或经用户选择的替代图，可用 `diagram <lesson.json> --output <file.svg>` 本地预览。复杂机制拆成主要回路，把支线解释放正文，不将几十个节点挤在一张图中。

伪代码描述输入、关键状态、决策、工具调用、反馈和退出。与原文不同的预算、重试、权限机制要标为教学补充。不得为了满足模板而编造算法或实验。

用户区和讨论区由发布脚本创建，JSON 不包含用户感悟。不要代填“我的收获”“我的疑问”。

## 发布前检查

1. 所有主要结论都能定位到来源，推断不混入事实。
2. 流程图、伪代码与文字中的回路、分支和停止条件一致。
3. 数字注明设置与指标；没有实验就不声称已证实提升。
4. 初学者能回答：为什么需要这个机制？输入输出是什么？下一步受什么影响？什么时候不适用？
5. `validate` 只检查结构，`reviewed: true` 是宿主的质量声明，不能用字段通过代替实际审阅。

脚本逐节写入、回读文字/链接/代码、导出图示预览。检查返回图片后才向用户确认可读。正式发布中断时保留原 JSON，不改写成另一个草稿覆盖已写内容。
