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

确认默认读取 `02-需求澄清/intake.json`；若明确使用其他版本，用 `--intake <方案内相对路径>`。格式如下，示例描述的是信息记录方式，不是商品事实：

```json
{
  "scope": "本次商品和交付范围",
  "coverage_review": "已对主视觉、人物交互、功能场景、包装配件及发布排版逐项核对；说明采用和不采用哪些展示方式及其依据",
  "items": [
    {
      "id": "visual-001",
      "decision": "本次使用哪个商品版本",
      "required_information": "图片与名称对应的型号、颜色和版本",
      "status": "resolved",
      "answer": "用户实际确认的版本，填写时替换此说明",
      "source": "实际资料路径、图片编号或问答记录中的对应位置"
    }
  ]
}
```

`scope`、`coverage_review` 和非空 `items` 必需。每项的 `id` 唯一，`decision`、`required_information` 均非空。`status` 只接受 `resolved`、`not_applicable`、`omitted_confirmed`、`pending`、`conflict`；确认方案前只允许前三种，均需非空 `answer` 与 `source`。不适用项写出决定及依据，省略项另附 `user_confirmation` 保存用户对省略影响的实际确认。清单更新后旧方案确认失效；新增展示需求需补充清单，不能靠沿用旧状态绕过。

确认命令核查登记状态并保存证据和校验值，不会判断消息、资料真实性或清单是否漏项；agent 必须先覆盖实际展示决策，并在真正收到用户确认后调用。不要把运行文档中的示例当作用户确认。

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
        {
          "path": "01-原始资料/图片/product-001.png",
          "role": "product", "target": "当前页商品本体",
          "preserve": ["已确认商品的轮廓、颜色、结构和标识"],
          "allow": ["仅按已确认构图调整位置和展示角度"],
          "exclude": ["原图背景和非随附道具"], "priority": 100
        },
        {
          "from_job": "character-001",
          "role": "person", "target": "character-001",
          "preserve": ["已确认人物的身份、发型和服装"],
          "allow": ["方案批准的姿态与表情"],
          "exclude": [], "priority": 80
        }
      ]
    },
    {
      "id": "page-002", "kind": "page", "width": 1024, "height": 1536,
      "prompt": "05-提示词与排版数据/v001/page-002-prompt.txt",
      "layout": "05-提示词与排版数据/v001/page-002-layout.json",
      "references": [
        {
          "path": "01-原始资料/图片/product-001.png",
          "role": "product", "target": "当前页商品本体",
          "preserve": ["已确认商品的轮廓、颜色、结构和标识"],
          "allow": ["仅按已确认构图调整位置和展示角度"],
          "exclude": ["原图背景和非随附道具"], "priority": 100
        },
        {
          "from_job": "character-001",
          "role": "person", "target": "character-001",
          "preserve": ["已确认人物的身份、发型和服装"],
          "allow": ["方案批准的姿态与表情"],
          "exclude": [], "priority": 80
        }
      ]
    }
  ]
}
```

没有人物时省略素材任务。一个批次恰有一个 `sample`，它也是正式页面，无需再重复提交。其余页面使用 `page`。单页详情页只有 `sample`。`from_job` 只可引用本批次的素材任务，工具在执行时解析到已验收的实际图片，不以未来路径冒充现有文件；循环依赖会被拒绝。

每张参考图必须填写 `role`、`target`、`preserve`、`allow`、`exclude`、`priority`；`role` 仅允许 `product`、`person`、`prop`、`style`、`composition`、`background`。后三个特征字段为字符串列表，`preserve` 明确对应职责，`allow`、`exclude` 无内容时显式为空列表。`priority` 为整数，越大越优先；商品事实与身份不能被风格优先级覆盖。示例中的特征文字须依据实际素材展开，不能用它代替具体设定。页面没有商品参考图时，必须有用户确认的不出现商品决定，记录为该任务的非空 `product_absence_reason`（含确认依据）。角色如何用于提示词和工作流见 [生图路线](generation.md)。

`max_attempts` 是每个任务最多提交次数（含第一次）；`candidates_per_job` 是每次提交的候选图数量。ComfyUI 的候选数必须通过 `candidates` 动态映射或固定绑定核对，包括单候选。不同任务需要不同工作流时，在各任务上设置 `workflow_config` 覆盖批次默认工作流；它同样纳入确认校验，不能擅自扩大用户同意的范围。

选择 `comfyui` 路线时增加 `workflow_config`，指向 `06-工作流与执行记录/workflow-config.json`。配置格式见 [生图路线](generation.md)。提交前先预检：

```text
python -X utf8 <runtime> preflight --task <task> --batch 05-提示词与排版数据/v001/batch.json
```

`preflight` 读取本地配置与字体；ComfyUI 路线还读取服务器 `/object_info` 与 `/queue`，不上传图片或提交生图。归档返回结果，并将其中 `effective_prompts`（展开参考图职责后的实际提示词）连同路线、候选数、尝试上限、样张页和排版数据展示给用户确认。`semantic_image_quality_verified=false` 表示预检不判定实际画面质量：

```text
python -X utf8 <runtime> approve-batch --task <task> --file 05-提示词与排版数据/v001/batch.json --message <用户实际确认原文>
python -X utf8 <runtime> run --task <task> --batch 05-提示词与排版数据/v001/batch.json --job character-001
```

每项输入、字体、现有参考图、工作流均加入批次校验。生成相关内容修改后旧确认无法用于新批次；仅排版改动按后文独立确认。`run` 返回执行目录的绝对路径，后续命令的 `--run` 使用其相对 `<task>` 的路径（以下简称 `<run-relative>`）。同一任务有未解决调用时拒绝再次提交；调用明确失败后可在上限内尝试下一次，不自动切换路线。已经生成图但视觉不合格时，再次 `run` 还需 `--repair-note <具体修正说明>`；不能无理由反复重抽。

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

`agent` 路线的 `run` 仅创建 `awaiting_agent` 记录，不生成图，也不扣额度。agent 读取该执行记录 `execution.json` 的 `effective_prompt` 与按顺序解析的参考图片，调用当前实际可用的生图工具，得到真实本地文件后归档；不能只读原始提示词而漏掉参考图职责：

```text
python -X utf8 <runtime> import-agent --task <task> --run <run-relative> --images <实际输出绝对路径> --tool <实际工具名> --call-id <实际调用标识>
```

`--images` 文件数必须等于已确认候选数量。工具验证文件格式和尺寸，再复制到 `07-生成结果与检查`。如果工具不能按要求输出尺寸或参考图数量，在调用前说明并调整设计或路线，不能隐瞒差异。生成工具只返回可下载链接时，用工具支持的导出方式取得原图，不能以截图替代。

内置调用明确失败后，记录实际失败才能在上限内重试：

```text
python -X utf8 <runtime> agent-failure --task <task> --run <run-relative> --tool <实际工具名> --call-id <实际调用标识> --message <失败原因>
```

## 实际底图检查

素材任务直接看图做身份与一致性验收，不调用页面排版命令。页面任务（含样张）取回真实输出后，先打开底图，与商品和素材参考逐项对照。可输出预设文字框和保护框的辅助图：

```text
python -X utf8 <runtime> inspection-preview --task <task> --run <run-relative> --candidate 1
```

辅助图只显示预计区域，不自动定位商品。agent 实际看图后，保存以下检查 JSON。`image_sha256` 从执行记录中该候选的实际 SHA-256 取得，不能拿示例值替代：

```json
{
  "image_sha256": "当前候选底图的实际SHA-256",
  "observations": "具体描述商品和参考的一致之处、光影、物品数量、实际商品位置及文字可用区域",
  "actual_protected_regions": [[100, 500, 824, 800]],
  "checks": {
    "composition": true,
    "lighting": true,
    "reference_fidelity": true,
    "no_extra_objects": true
  }
}
```

矩形仍为 `[左, 上, 宽, 高]`，坐标根据实际画面填写并覆盖商品本体与标识；有商品参考的页面不得为空。没有商品且用户已确认的页面可为空。检查不通过时使用后文 `reject`，不能为继续排字而把检查填写为 `true`。检查通过后保存：

```text
python -X utf8 <runtime> inspect-image --task <task> --run <run-relative> --candidate 1 --file 07-生成结果与检查/底图检查-v001.json
```

该记录绑定候选底图校验值；工具不做自动识别。底图发生变化必须重新看图；实际保护框会代替预计保护框用于排版冲突检查。实际商品位置与原文字框冲突时，底图检查会记录 `planned_layout_conflict`，先单独调整并确认新排版，再 `rerender`；不能把预计保护框缩小来隐藏冲突。更新 `inspect-image` 记录后，原渲染及其验收失效，须按新记录重排、看图并重新验收。

## 排版、验收与继续

页面底图检查完成后执行：

```text
python -X utf8 <runtime> render --task <task> --run <run-relative> --candidate 1
```

检查真实成图后，将检查结果保存为方案内 JSON。页面需要 `identity`、`consistency`、`text`、`layout` 全部为布尔 `true`；人物、道具素材需要前两项。两者都须附非空 `observations`，具体描述看图结论，不可仅为使程序通过而填写。检查失败先记录问题、按已确认范围修正，不调用通过验收命令。

获得用户实际验收后：

```text
python -X utf8 <runtime> review --task <task> --run <run-relative> --candidate 1 --checks 07-生成结果与检查/检查结果.json --message <用户实际验收原文>
```

素材验收后可供 `from_job` 解析；样张排版验收后解除本批次其余页面的执行限制。普通页面执行记录同时绑定当时已验收的样张版本；换样张或样张失效后，下游页面也失效，须重新制作与验收。页面验收后才复制到 `08-最终交付` 并附验收记录。上游素材选择改变时，已生成下游页面不能继续验收或作为有效样张使用，需重做受影响页面。

工具不执行 OCR，不自动判定商品身份或文字视觉质量。`rendered_pending_visual_review` 只说明字体排版完成；最终仍须实际看图并取得用户验收。

## 退回与独立排版修正

接口成功但图像或排版不合格时，保存具体退回报告；`region` 是位置描述，`correction` 写明修改动作和须保留的内容：

```json
{
  "issues": [
    {
      "category": "layout",
      "region": "主标题文本框与商品顶部的相邻区域",
      "expected": "已确认文案完整且不遮挡商品",
      "actual": "填写实际看图发现的差异",
      "correction": "调整文字框位置，保持文案、底图、字号和其他页面元素不变",
      "severity": "blocking",
      "repair": "retypeset"
    }
  ]
}
```

每个问题的上述文本字段均非空；`severity` 为 `blocking` 或 `minor`；`repair` 为 `retypeset`（重排字）、`local_edit`（局部编辑）、`regenerate`（重生图）或 `clarify`（返回澄清）。记录实际问题，不将示例文字用于通过检查：

```text
python -X utf8 <runtime> reject --task <task> --run <run-relative> --candidate 1 --file 07-生成结果与检查/退回-v001.json
```

排版修正可复用已生成底图，不需要再次生图。将新排版和新字体（若需要）另存路径，不能覆盖原批次、原排版或原字体；展示差异并取得用户确认后：

```text
python -X utf8 <runtime> approve-layout --task <task> --run <run-relative> --candidate 1 --file 05-提示词与排版数据/v002/page-001-layout.json --message <用户实际确认原文>
python -X utf8 <runtime> rerender --task <task> --run <run-relative> --candidate 1 --layout 05-提示词与排版数据/v002/page-001-layout.json
```

新布局画布必须与底图相同，继续按实际商品保护框检查。`approve-layout` 选定新版后，不得再验收旧渲染，须先对选定版本重排、看图并取得用户验收；旧排字图和验收历史保留。仅当全部未解决问题都是 `retypeset` 时，重排可解除该候选的排版退回；多次 `reject` 会保留全部未解决问题，后续排版退回不能覆盖先前的画面问题，画面问题必须真正修复。

局部编辑或重新生成前，先解释根因与修正内容；能力或素材不足时回到澄清。实质修改提示词、参考图或生图设置需另存并确认新批次；新增生图尝试仍受确认上限约束。

工作流预检也拒绝将不同受控参数绑定到同一节点输入，避免后写参数覆盖先写参数；所有动态或固定绑定的受控参数都须沿实际节点连接到达输出。通过这些检查仍不代表模型已保持商品保真。

跨会话继续时先读 `task.json`、项目索引、批次确认和各执行记录。索引可能列出失败尝试，不能把文件存在视为成功。每次验收或继续批次后执行以下核对；它会核对全部任务的验收、依赖及成品校验值，保存 `status.json` 并更新项目索引。`complete` 为 `false` 时不宣称整套已交付。

```text
python -X utf8 <runtime> status --task <task> --batch 05-提示词与排版数据/v001/batch.json
```
