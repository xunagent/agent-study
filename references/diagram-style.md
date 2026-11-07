# AIGC 手绘技术图

默认采用白底、石墨轮廓、淡彩蜡笔填色的技术手绘图。风格依据用户提供的 aigc-prompts 示例提炼；原始压缩包及参考图片不随公开仓库分发。

## 生成

使用宿主原生图像生成能力（例如 imagegen），无此能力时明确说明限制；只有用户接受后才使用脚本 SVG 图作为替代。不要静默改成普通方框图，也不要自行配置付费图片 API。

先写结构化 `diagram.nodes/edges`，再将节点标签和每条有向边逐项展开到提示词。源材料决定图的内容，样式参考只决定视觉；不可把示例里的节点、箭头或英语要求复制到新图。默认沿用学习语言。

可复用的风格模板：

```text
Use case: infographic-diagram.
Pure WHITE background. Dark graphite / crayon hand-drawn outlines and clear
arrowheads. Pale blue for context / reasoning, soft green for actions / feedback,
restrained warm orange for completion / decisions. Visible wax-pencil grain,
slightly irregular rounded boxes, legible handwritten lettering.
Compact near-square or portrait composition, large phone-readable labels,
generous whitespace. No paper tint, shadows, watermark or decorative prose.

Language: {learning_language}
Exactly these nodes, each once: {node_id_and_exact_label_list}
Exactly these directed edges: {from_to_and_edge_labels}
Layout: {layout_appropriate_to_this_graph}
No extra nodes or arrows. Keep return loops in separate lanes, no merged shafts,
crossings through boxes, or text covered by arrows. Accuracy over decoration.
```

逐项核对节点、箭头起终点、分支标签和中文错字；尤其检查生成器是否擅自把相邻节点连成一条流水线。有错时用图像编辑工具做局部修正，再检查。把最终 PNG/JPEG 和包含修正要求的完整 prompt 放在私有状态目录。

## 发布

目前采用两步发布：`study.py publish` 建立正文和结构图；随后用 `illustrate.py` 替换图示块。第二步及图片回读完成前，不向用户宣称图示验收完成。两步之间会短暂显示结构图。

1. `study.py publish` 会建立独立图示源文件并在文末链接。`python3 <skill>/scripts/illustrate.py` 仅读取当前篇的流程图节；可用 `--material <id>` 指定笔记。结合独立源文件中的图源检查生成图，取得目标文档 token。
2. 先上传成品，使用相同个人 profile，在图片所在目录运行 `lark-cli docs +media-insert --doc <doc> --file ./image.png --width 800 --as user --format json`。立即将返回的 `block_id` / `file_token` 保存到私有恢复记录。此步骤把图片临时追加到文末，不读取个人区域。若请求超时且未知上传结果，停止盲目重试，先核实已有上传；不要重复创建图片。
3. 上传后再次运行 `illustrate.py`，取得当前旧视觉块 ID 和最新 `revision_id`，再发布：

```sh
python3 <skill>/scripts/illustrate.py \
  --image <private/image.png> --prompt <private/prompt.txt> \
  --expected-block <visual_block_id> --expected-revision <revision_id> \
  --uploaded-block <block_id> --image-token <file_token> --reviewed
```

脚本先验证上传的图片块、移动到流程图节并回读，将 prompt 和指纹保存到独立源文件并核实，然后才移除指定旧视觉块。正文不插入 prompt 或指纹，保留正文与个人记录。显式 `--state-dir` / `--profile` 同主脚本。完成后的重试使用相同文件和参数：回读已生效结果，不重复插图。若移动中断或版本冲突，保留已上传图片，重新检查现有块和版本后继续，不重新上传。

4. 用官方 `lark-cli docs +media-download --token <image_token> --output ./readback.png --as user` 下载到私有目录。命令使用相同个人 profile。核对下载图与本地成品的 SHA-256，并打开图片确认可读，才交付文档链接。失败时修复现有图，不重建整篇。

已经上传的图片、prompt 和 JSON 图源都在飞书，换电脑后仍可访问。若更换电脑发生在上传前，需重新生成并检查图片，然后重新读取目标块开始发布；不要假定另一设备的本地图片还存在。AIGC 成品是位图，不能逐个编辑节点；JSON 图源仍可用于重绘。
