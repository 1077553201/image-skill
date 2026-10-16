# 运行工具与数据格式

`scripts/detail_runtime.py` 可从任意工作目录调用，不依赖本仓库的 `src` 包。需要 Python 3.11+ 和 Pillow；不自动安装。以下命令中的 `<runtime>` 替换为本 Skill 内脚本的实际绝对路径，`<task>` 是 `init` 返回的方案目录绝对路径。文件参数除源文件和 `--images` 外均为方案内相对路径。

## 建立目录与保存资料

```text
python -X utf8 <runtime> init --project-root <项目绝对路径> --name <商品简称>
python -X utf8 <runtime> archive --task <task> --source <源文件绝对路径> --destination 01-原始资料/图片/product-001.png
```

`init` 拒绝磁盘根目录、用户主目录、系统目录及 Skill 安装目录；同名方案自动编号。`archive` 复制源文件并记录 SHA-256，不覆盖同名目标。需求、方案、提示词等由 agent 先写在可访问的临时文件，再使用 `archive` 归档。版本更新另存新文件。不要直接写成品来绕过目录校验。

记录实际用户确认：

```text
python -X utf8 <runtime> approve-plan --task <task> --file 03-设计方案/方案-v001.md --message <用户实际确认原文>
```

确认命令只保存证据和校验值，不会判断消息真实性；agent 必须在真正收到用户确认后调用。不要把运行文档中的示例当作用户确认。

## 批次清单

agent 编写 `05-提示词与排版数据/v001/batch.json`。以下仅为结构示例，文字与尺寸不代表任何商品事实：

```json
{
  "route": "agent",
  "plan": "03-设计方案/方案-v001.md",
  "max_attempts": 2,
  "candidates_per_job": 1,
  "jobs": [
    {
      "id": "character-001", "kind": "asset", "width": 1024, "height": 1024,
      "prompt": "04-一致性素材/character-001/生成提示词-v001.txt",
      "references": []
    },
    {
      "id": "page-001", "kind": "sample", "width": 1024, "height": 1536,
      "prompt": "05-提示词与排版数据/v001/page-001-prompt.txt",
      "layout": "05-提示词与排版数据/v001/page-001-layout.json",
      "seed": 42,
      "references": [
        {"path": "01-原始资料/图片/product-001.png"},
        {"from_job": "character-001"}
      ]
    },
    {
      "id": "page-002", "kind": "page", "width": 1024, "height": 1536,
      "prompt": "05-提示词与排版数据/v001/page-002-prompt.txt",
      "layout": "05-提示词与排版数据/v001/page-002-layout.json",
      "references": [{"from_job": "character-001"}]
    }
  ]
}
```

没有人物时省略素材任务。一个批次恰有一个 `sample`，它也是正式页面，无需再重复提交。其余页面使用 `page`。单页详情页只有 `sample`。`from_job` 只可引用本批次的素材任务，工具在执行时解析到已验收的实际图片，不以未来路径冒充现有文件；循环依赖会被拒绝。

`max_attempts` 是每个任务最多提交次数（含第一次）；`candidates_per_job` 是每次提交的候选图数量。ComfyUI 要生成多个候选时，工作流必须有明确的 `candidates` 参数映射。不同任务需要不同工作流时，在各任务上设置 `workflow_config` 覆盖批次默认工作流；它同样纳入确认校验，不能擅自扩大用户同意的范围。

选择 `comfyui` 路线时增加 `workflow_config`，指向 `06-工作流与执行记录/workflow-config.json`。配置格式见 [生图路线](generation.md)。选择路线、候选数、尝试上限以及样张页后，将其连同最终提示词和排版数据展示给用户确认：

```text
python -X utf8 <runtime> approve-batch --task <task> --file 05-提示词与排版数据/v001/batch.json --message <用户实际确认原文>
python -X utf8 <runtime> run --task <task> --batch 05-提示词与排版数据/v001/batch.json --job character-001
```

每项输入、字体、现有参考图、工作流均加入批次校验。修改后旧确认无法用于新批次。`run` 返回执行目录的绝对路径，后续命令的 `--run` 使用其相对 `<task>` 的路径（以下简称 `<run-relative>`）。同一任务有未解决调用时拒绝再次提交；失败后可在上限内尝试下一次，不自动切换路线。

## 排版格式

```json
{
  "canvas": [1024, 1536],
  "protected_regions": [[100, 500, 824, 800]],
  "text_blocks": [
    {
      "text": "用户已确认的标题",
      "font": "01-原始资料/字体/regular.ttf",
      "size": 48, "color": "#102030",
      "box": [60, 60, 904, 160],
      "align": "left", "spacing": 12
    }
  ]
}
```

所有矩形为像素坐标 `[左, 上, 宽, 高]`。字体可以是 TTF、OTF 或 TTC（使用第一字体面），先以 `archive` 保存实际可用字体。工具检查 Unicode cmap 的实际字形覆盖；不自动替换字体。文案换行使用 JSON 字符串中的 `\n`，换行位置由 agent 设计并确认；不自动缩小字号或截断。文本框不得互相重叠或覆盖商品保护区域。可按需要指定 `background` 为文本框填色，未指定则保留底图。

画布尺寸必须匹配生成画面；需要调整画布或做图像处理时，在排版前完成并保留对应来源与版本，重新确认受影响配置，不伪造工具原始输出尺寸。真实商品标识、包装文字的视觉保真仍需检查。

## 内置生图归档

`agent` 路线的 `run` 仅创建 `awaiting_agent` 记录，不生成图，也不扣额度。agent 读取其对应提示词与解析后的参考图片，调用当前实际可用的生图工具，得到真实本地文件后归档：

```text
python -X utf8 <runtime> import-agent --task <task> --run <run-relative> --images <实际输出绝对路径> --tool <实际工具名> --call-id <实际调用标识>
```

`--images` 文件数必须等于已确认候选数量。工具验证文件格式和尺寸，再复制到 `07-生成结果与检查`。如果工具不能按要求输出尺寸或参考图数量，在调用前说明并调整设计或路线，不能隐瞒差异。生成工具只返回可下载链接时，用工具支持的导出方式取得原图，不能以截图替代。

内置调用明确失败后，记录实际失败才能在上限内重试：

```text
python -X utf8 <runtime> agent-failure --task <task> --run <run-relative> --tool <实际工具名> --call-id <实际调用标识> --message <失败原因>
```

## 排版、验收与继续

素材任务不排字。页面任务（含样张）生成后执行：

```text
python -X utf8 <runtime> render --task <task> --run <run-relative> --candidate 1
```

检查真实成图后，将检查结果保存为方案内 JSON。页面需要 `identity`、`consistency`、`text`、`layout` 全部为布尔 `true`；人物、道具素材需要前两项。附上具体检查说明，不可仅为使程序通过而填写。检查失败先记录问题、按已确认范围修正，不调用通过验收命令。

获得用户实际验收后：

```text
python -X utf8 <runtime> review --task <task> --run <run-relative> --candidate 1 --checks 07-生成结果与检查/检查结果.json --message <用户实际验收原文>
```

素材验收后可供 `from_job` 解析；样张排版验收后解除本批次其余页面的执行限制。页面验收后才复制到 `08-最终交付` 并附验收记录。上游素材选择改变时，已生成下游页面不能继续验收或作为有效样张使用，需重做受影响页面。

工具不执行 OCR，不自动判定商品身份或文字视觉质量。`rendered_pending_visual_review` 只说明字体排版完成；最终仍须实际看图并取得用户验收。

跨会话继续时先读 `task.json`、项目索引、批次确认和各执行记录。索引可能列出失败尝试，不能把文件存在视为成功。每次验收或继续批次后执行以下核对；它会核对全部任务的验收、依赖及成品校验值，保存 `status.json` 并更新项目索引。`complete` 为 `false` 时不宣称整套已交付。

```text
python -X utf8 <runtime> status --task <task> --batch 05-提示词与排版数据/v001/batch.json
```
