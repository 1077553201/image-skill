# Image Skill · 商品详情页设计与生图

让 agent 根据商品图片、商品资料、目标客户和销售平台，逐项澄清需求、设计详情页、编写每页生图提示词，再按用户确认的路线制作画面、排入真实字体并归档。

本仓库的主要入口是 **[`image-generation` Skill](skills/image-generation/SKILL.md)**。可以只交付设计方案或提示词，也可以继续完成生图与排版。新增营销文字采用“模型生成底图 + 真实字体排版”，减少模型直接绘字造成的扭曲、错字和伪字。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [Skill 使用规则](skills/image-generation/SKILL.md) | agent 应遵循的完整工作流程与确认节点 |
| [两路生图说明](skills/image-generation/references/generation.md) | agent 内置生图、远程 ComfyUI、工作流和参考图要求 |
| [运行工具与数据格式](skills/image-generation/references/runtime.md) | 命令、批次清单、排版数据、检查与验收记录 |
| [官方提示词约束](skills/image-generation/references/official-prompt-constraints.md) | OpenAI、Google、Qwen 官方方法的简短提炼及来源 |
| [验证报告](reports/detail_page_validation/validation.json) | 已记录的自动检查范围、结果与限制 |

## 能做什么

- **完整澄清需求**：从拟采用的展示方式反推所需信息，记录来源、缺口和冲突，分轮追问到每项都有明确处理结果。
- **逐页设计**：根据当前商品安排页面顺序、卖点、文案、构图、配色和字体层级，不预设固定页数。
- **交付独立提示词**：方案确认后，每页保存可独立执行的完整画面提示词，以及准确文案和排版数据。
- **统一人物和道具**：保存独立素材设定、生成提示词、参考图与版本，供多页复用；生成素材须先验收。
- **两路制作**：选择当前 agent 实际提供的生图工具，或通过远程 ComfyUI 执行已确认的工作流。
- **真实字体排版**：校验字形、文字溢出、安全边距和商品保护区域；只改排版时复用原底图。
- **可追溯归档**：每个新方案在项目根目录创建独立子目录，保留资料、问答、方案、提示词、执行记录、失败尝试与最终交付。

## 开始使用

### 1. 准备 Skill 和运行环境

获取仓库：

```sh
git clone https://github.com/1077553201/image-skill.git
cd image-skill
```

在支持读取本地文件、查看图片和加载 Skill 的 agent 中打开仓库，让它读取 `skills/image-generation/SKILL.md`。仅下载仓库不会自动把 Skill 注册到所有 agent；自动发现或全局安装方式取决于所用工具。

资料分析、方案设计和提示词编写由 agent 完成。运行归档、执行和排版脚本需要 **Python 3.11+、Pillow**；排版还需要包含目标文字字形的实际字体文件。脚本不自动安装依赖，也不修改 ComfyUI 服务器环境。

若已有环境满足要求，直接使用即可。需要单独环境时，以下是 Windows PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install Pillow
.\.venv\Scripts\python.exe -X utf8 skills/image-generation/scripts/detail_runtime.py --help
```

后续命令中的 `python` 应替换为所选环境的 Python。Linux/macOS 的虚拟环境解释器通常位于 `.venv/bin/python`。

当前 Skill 的脚本可以独立运行，无需安装仓库根目录的 `pyproject.toml` 包。该包及 `product-studio` 命令属于仓库保留的旧摄影引擎，依赖和入口与本 Skill 不同。

### 2. 提供商品资料并说明交付范围

可以直接向 agent 发送：

```text
读取 skills/image-generation/SKILL.md，按这个 Skill 帮我制作商品详情页。

我会提供商品图片和已有资料；客户、平台、语言和设计偏好可以继续向我确认。
请先核实本次商品项目的根目录，并在其中新建方案子目录。
缺少信息时逐项追问，不猜测商品参数。
先完成逐页设计方案，等我确认后再编写每页提示词。
需要生图时，再确认使用的工具、候选数量和尝试次数。
```

建议提供：商品名称及型号、整体与细节图、已知规格和功能、目标客户、销售平台、市场与语言、品牌素材、风格参考、尺寸或页数要求。**这些是信息维度，不是所有商品都必须填完的固定表单**；agent 会按本次展示需要补问。也可以明确要求“本次只要提示词，不执行生图”。

商品项目根目录可以是当前仓库，也可以是另一个明确指定的工作目录；它与 Skill 安装目录是两个概念。

### 3. 按阶段确认

| 阶段 | agent 的交付与处理 | 继续条件 |
| --- | --- | --- |
| 资料澄清 | 整理图片与事实来源，保存问答及信息清单 | 相关缺口和冲突已解决；不能提供的内容已获准省略或调整范围 |
| 逐页方案 | 页面顺序、文案、排版、视觉方向、人物和道具设定 | 用户确认方案版本 |
| 提示词与设置 | 每页提示词、素材依赖、字体排版数据、路线和执行范围 | 用户确认提示词、路线、候选数和尝试上限 |
| 一致性素材 | 按需制作人物或道具参考图 | 用户验收后供页面复用 |
| 一页样张 | 生成底图、看图检查、真实字体排版 | 用户验收样张后制作其余页面 |
| 批量与交付 | 逐页制作、检查、定向修正、核对批次 | 仅已检查且获用户验收的页面进入最终交付 |

已经确认的内容直接沿用；影响事实、设计或执行结果的变更，需要确认相应新版本。用户只要求某个阶段时，在该阶段交付后停止。

## 两路生图如何选择

| 路线 | 前提 | 执行方式 |
| --- | --- | --- |
| `agent` 内置生图 | 当前 agent 确实提供图片生成或编辑工具，且支持本次输入要求 | 运行工具创建待调用记录，agent 调用实际生图工具，再导入真实输出及调用标识 |
| `comfyui` 远程生图 | 可访问的 ComfyUI 服务、真实 API 格式工作流，以及匹配的节点、模型和参考图能力 | 核查节点与参数，上传并核对参考图，提交工作流，查询原任务并取回输出 |

首次使用 ComfyUI 时，由 agent 询问服务器地址、验证连接，再保存到**商品项目根目录**的 `detail-page.connection.json`。已有当前有效配置时沿用；更换服务器后重新验证。地址不写死在 Skill 中，本地路径也不会直接作为远程图片路径使用。

ComfyUI 工作流必须适配任务尺寸、候选数和参考图数量。预检会检查真实节点、输入参数、重复绑定以及各绑定是否连到输出；通过预检仍需看图核实商品保真。

当前不提供会员额度代理或登录账号接入。`agent` 路线使用当前工具实际提供的能力与额度，脚本本身不会连接会员账号或自动切换服务。详细操作见[两路生图说明](skills/image-generation/references/generation.md)。

## 文字、商品和画面质量

**商品事实必须有依据。** 不凭外观推断尺寸、材质成分、性能或认证，不编造参数、评价和承诺。参考图片须注明型号及用途；商品、人物、道具、风格、构图和背景参考各自声明保留项、允许变化和排除项。风格参考不能覆盖商品身份。

**新增营销文字用真实字体绘制。** 生图提示词描述文字留白，准确文案单独保存；商品原有商标和包装文字仍需保留并检查。排版工具遇到缺字、超界或溢出会停止，不会静默删字、改写或缩小字号。

**先看实际底图，再确定保护区域。** agent 必须打开本次输出，核对商品、人物互动、数量、光影和留白，记录实际商品位置。工具中的保护框和辅助叠框来自声明坐标，不能当作自动检测结果。最终文字笔画、对比度与商品身份仍需视觉检查。

**按问题修正并保留版本。** 仅文案或排版调整，通过 `approve-layout` / `rerender` 复用底图；画面问题记录具体区域和差异后再编辑或重生图。新版排版、底图检查或样张选择会使相关旧验收失效；多次退回不会覆盖未解决的画面问题。

生成模型重绘过的商品不能仅凭提示词宣称保真。要求严格还原时，优先保留原始商品前景并合成；无法验证的结果保留待确认状态。

## 文件保存在哪里

每个新方案都绑定一个明确的项目根目录；继续已有方案时在原方案目录保存新版本。工具拒绝磁盘根目录、用户主目录、系统目录、Skill 安装目录及路径越界。

```text
用户确认的项目根目录/
├── detail-page.connection.json          # 使用 ComfyUI 时保存的本项目连接配置
└── 详情页-日期时间-商品简称/
    ├── task.json                        # 根目录绑定和阶段状态
    ├── 项目索引.md
    ├── 01-原始资料/                     # 原始说明、图片、来源与归档记录
    ├── 02-需求澄清/                     # intake.json、问题与答复
    ├── 03-设计方案/                     # 逐页方案及确认版本
    ├── 04-一致性素材/                   # 人物、道具设定、提示词与参考图
    ├── 05-提示词与排版数据/             # 每页 prompt、layout.json、batch.json
    ├── 06-工作流与执行记录/             # 工作流、确认、任务编号、尝试与状态
    ├── 07-生成结果与检查/               # 底图、排字图、实际检查及退回记录
    └── 08-最终交付/                     # 已获验收的页面及验收记录
```

原始图片采用复制归档，不移动或覆盖源文件；无法取得原文件时明确记录限制。方案目录整体移动后，需要显式确认并更新根目录绑定。项目资料是否提交 Git 由使用者决定；本仓库忽略本机连接配置，但新建方案目录没有统一的自动忽略规则。

## 脚本与维护

日常使用由 agent 按 Skill 调用脚本。下面的命令用于查看接口，不会提交生图：

```powershell
python -X utf8 skills/image-generation/scripts/detail_runtime.py --help
```

| 命令组 | 用途 |
| --- | --- |
| `init`、`archive`、`connection` | 建立项目绑定、复制资料、验证并保存连接 |
| `approve-plan`、`approve-batch`、`preflight` | 记录实际确认、冻结输入版本、执行生成前检查 |
| `run`、`resume`、`import-agent`、`agent-failure` | 创建或执行任务、查询远程任务、导入内置工具输出、记录失败 |
| `inspection-preview`、`inspect-image`、`reject` | 生成辅助检查图、记录实际看图结果、保存具体问题 |
| `render`、`approve-layout`、`rerender`、`review`、`status` | 排字、确认新版排版、验收及核对完整交付 |

`preflight` 不上传图片或提交生图；`connection` 会访问服务器验证连接。`agent` 路线的 `run` 只创建待调用记录，不能把它的成功当作图片已生成。完整命令、所需文件及 JSON 示例见[运行工具与数据格式](skills/image-generation/references/runtime.md)。

运行本 Skill 的自动检查：

```powershell
python -X utf8 -m unittest discover -s skills/image-generation/tests -v
```

截至 **2026-10-16** 保存的[测试记录](reports/detail_page_validation/tests.txt)为 **74 项通过**，覆盖需求状态、参考职责、工作流结构、排版、版本失效、退回和重复提交保护。测试使用合成图片和本机模拟 ComfyUI；中文排版样图也经过目视检查。这些记录不代表真实模型在某个商品上已通过质量验收，后续任务仍须制作并验收实际样张。

## 仓库结构与其他模块

```text
image-skill/
├── README.md
├── skills/
│   ├── image-generation/               # 本文主要介绍的详情页 Skill
│   │   ├── SKILL.md
│   │   ├── references/                 # 生图路线、数据格式、官方提示约束
│   │   ├── scripts/                    # 执行、排版与工作流检查
│   │   └── tests/
│   ├── visual-report-generator/        # 独立的品类视觉策略报告 Skill
│   └── universal-product-creative/     # 旧摄影引擎的 Skill 入口
├── reports/detail_page_validation/     # 当前详情页 Skill 的验证记录
├── src/、scripts/、tests/、configs/     # 旧摄影引擎及相关工具
├── docs/                               # 旧引擎架构与阶段记录
└── pyproject.toml                      # 旧引擎的 Python 包定义
```

[`visual-report-generator`](skills/visual-report-generator/SKILL.md) 面向品类、市场和视觉策略报告，可以单独调用；它不是 `image-generation` 的运行依赖。使用外部报告作输入时，报告中的商品主张仍要回到实际资料核实。

旧摄影引擎保留用于回查和独立使用，`image-generation` 的运行脚本不导入其 `src` 包。历史入口与设计可查阅[旧 Skill README](skills/universal-product-creative/README.md)、[架构说明](docs/architecture.md)、[Design-First 设计记录](docs/design_first_architecture.md)及[阶段 4C 记录](docs/phase4c_results.md)。这些文件中的阶段状态、安装包和命令适用于对应历史模块。

本文档最后核对：**2026-10-17**。
