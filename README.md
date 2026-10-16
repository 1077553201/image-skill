# Universal AI Product Photography Studio

通用 AI 商品摄影与多视角生成系统。目标覆盖电子产品、饰品、箱包、化妆品、金属零件、家居用品等商品，圆形装饰转盘只是一个专项测试案例。通用核心管理实例、证据、真实性和任务路由，商品专用测量由独立插件提供。

**当前：Design-First AI Product Creative Skill。已完成访谈、三方向提案、用户方向选择及五页设计草图；等待逐页设计确认，尚未生成本轮成品。** 先前阶段成果保留。Agent 读取实际商品/参考图并提交来源绑定的观察与原创创意数据，Python 执行事实门禁、动态规划、背景生成、保真合成和自适应排版；未另部署 VLM。遮罩审核与最终营销图审核分别管理。最新状态见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## 当前设计入口（源码验证）

```powershell
python scripts/design_campaign.py --session data/creative_sessions/bag_design_first status
```

[五页方案](data/creative_sessions/bag_design_first/page_designs.md)、[布局草图](reports/design_first/design_overview.png)、[审计与状态合同](docs/design_first_architecture.md)。先确认方向，再设计并确认指定页面；修改单页保留其他页批准。当前 design handoff 仅交接数据，不执行生图，旧 generate 不是新 Skill 默认流程。原 0.3.0 Wheel/ZIP 不含新增 design 命令；最终独立执行验证缺少报告，不能据旧说明认定全部部署验收通过。

## 阶段 4C 历史快照：独立安装与旧入口

发行产物位于 dist/phase4c/release/，其中 Skill ZIP 包含引擎 Wheel、启动器、安装脚本、配置与参考文档。将整个 ZIP 解压到任意新目录，使用其中的 scripts/install_engine.py --venv <新环境>，然后调用安装环境中的命令：

```text
product-studio preflight --output preflight.json
product-studio generate --request /explicit/campaign.json --output /explicit/new-output
```

使用具备图像能力的 Agent 读取安装 Skill 的 SKILL.md，由 Agent 准备请求、实际观察与消费者文案。原始图片分割模型、字体、ComfyUI 服务和密钥均为显式外部配置；不回退搜索工程目录。ComfyUI 背景设置 COMFYUI_BASE_URL。已存在商品可以 export-asset 导出为可携带审核证据的单实例 bundle。

当前工具默认使用新创意家族，独立记录 consumer_copy、internal_notes、provenance；读取来源/实例/版本绑定的已确认事实，不从其他 SKU 或参考图借用参数。原始前景合成与 image_guided_creative_edit 分路，后者只输出概念候选。最终图不自动批准。

新九图：data/outputs/phase4c/{bag_final,headphones_final,blue_left_final}/；中文回归图：headphones_zh。总体说明与验收入口见 docs/phase4c_results.md。旧阶段文件保留，以下属于历史记录；当前版本重现应使用新请求与新输出目录，避免旧文案/旧计划与新合同混用。

## 阶段 4B 历史记录：通用入口与 Skill

```powershell
python scripts/generate_product_campaign.py --request configs/examples/bag_campaign_v2.json
旧版 Skill 命令仅用于历史说明；当前安装命令见上方 4C。
```

同一入口完成包袋 6 张、耳机 7 张、蓝盘 7 张，以及两个新创意 SKU 的最小冷启动。只更换 JSON 数据，不改核心代码。原有 195 项和新增 29 项测试全部通过。20 张套图总览为 `reports/phase4b_comparison.png`；最新目录为 `data/outputs/phase4b/{bag_v2,headphones_v2,blue_left}/`。

正式项目内 Skill 位于 [SKILL.md](skills/universal-product-creative/SKILL.md)，配有实际 CLI 启动器；未安装到全局发现目录。新输入缺少可靠图像分析时会暂停交接，不凭空完成理解。Level 2 是环境广告面板，Level 3 互动仅接口。包袋/耳机前景保持 preview，所有成品 pending。[开发与验收记录](docs/phase4b_results.md) 说明实际能力和限制。

## 阶段 4A：参考驱动商业套图

最新候选位于 `data/outputs/phase4a/blue_left_v2/`，包含八张不同用途的 `final.png`、图集总览和逐图来源清单。参考图内部保存在 `data/references/amazon_B0HGGJZ92H/`，不会作为最终图层。用户提供的直径 30 cm、重量 500 g、复合材料记录在 `reports/phase4a/product_facts.json`。

```powershell
python scripts/generate_creative_set.py --config configs/creative_presets/blue_left_4a_v2.json --render-only
python scripts/validate_phase4a.py --run-tests
```

生成已实际调用三个 QwenImage 任务，第二版只复用缓存。195 项测试通过，包含原有 161 项。全部最终图片仍 pending；A+ 缺失、原图细节像素有限和平台类目复核要求见 [阶段 4A 记录](docs/phase4a_results.md)。不把文字营销图当作 eBay 商品图片合规输出。

用户已确认开发时使用本机配合 DGX Spark，最终统一部署到 RTX 3090 电脑。DGX Spark 使用 Conda 环境，当前暂不调整。Blender 未安装，优先避免使用，不作为初期必需依赖；后续确定性建模与渲染后端另行评估。

## 阶段 1G：通用描述与任务路由

在项目根目录运行：

```powershell
python scripts/analyze_studio.py data/input/mmexport1791948355130.jpg
```

默认 `generic_product` 仅读取图片元数据、哈希和明确提供的实例，导出通用规格。不执行分类、视觉理解或分割：没有实例标注时 `detected_instances=[]`、`selected_instance=null`，类别、视角、材质、颜色与 mask 均保持未知，不假定图中只有一个商品。

人工指定多个实例时，重复提供 ROI；可按顺序关联 SKU，各实例始终分开保存：

```powershell
python scripts/analyze_studio.py data/input/mmexport1791948355130.jpg --roi 0 250 626 700 --roi 626 250 628 700
```

这些矩形由用户提供，证据状态为 estimated，不是自动分割 mask。`--sku` 可重复并与 ROI 一一对应，SKU 不会从图片相似度推断。`--selected-instance instance_001` 可选择已提供的 ROI 实例；未指定则分别处理所有明确实例。

显式调用已有专项插件：

```powershell
python scripts/analyze_studio.py data/input/mmexport1791948355130.jpg --analyzer planar_geometry --strategy visible_crop
```

`planar_geometry` 当前只有蓝色近正视圆盘变体，不能据名称认为已支持所有平面商品。插件不支持某张图片时记录 skipped，继续导出通用元数据；内部错误记录 failed，命令返回非零。`rigid_object`、`soft_goods`、`transparent_object` 尚未注册，只作为后续扩展点，选择这些名称会明确跳过。

输出到独立的 `data/intermediate/studio_任务标识/`。根目录 `run_manifest.json` 记录路由、来源和 `generation_executed=false`；每个实例有通用 `product_spec.json`，可选 `task_plan.json`。插件产物在实例目录下的 `planar_geometry/`，包含旧 JSON 与四张调试图。

通用规格使用 `studio.1g.1`，不要求圆心、半径或孔。专用字段位于 `geometry_features.planar_geometry`，保留 `legacy_payload` 以无损转换回阶段 1A `1a.1`。每条特征记录 observed、estimated、human_verified、unknown 或 conceptual 状态及来源；未知值为 null，转换不会提升审核状态。

六种任务策略只产生计划：原图合成、AI 背景、可见区域裁剪、多参考图编辑、已验证几何渲染、单图概念生成。所有计划标明真实性等级、来源、待满足条件和 `execution_status=not_implemented_in_phase1g`；`planned` 不是执行成功。未验证隐藏角度被阻止，概念任务始终为 concept_only，输出没有自动标为 verified。Provider 与渲染后端尚未接入。

跨品类验证目前仅使用矩形设备、细长瓶体、不规则包袋三类**合成接口样例**；真实图片回归仍只有蓝色转盘。具体验收证据见 [phase1g_results.md](docs/phase1g_results.md)，通用数据模型与依赖边界见 [architecture.md](docs/architecture.md)。

## 阶段 1A：蓝色商品图分析

以下是保留的专项兼容入口，算法实现现位于 `product_studio/plugins/planar_geometry/legacy.py`。旧命令、导入路径、数据与测试保留，不能将此入口当作通用商品分析器。

当前实测环境已有 NumPy 2.4.4 与 OpenCV 4.13.0.92，无需安装任何新软件。在项目根目录执行：

```powershell
python scripts/analyze_product.py data/input/mmexport1791948355130.jpg
```

默认选择最左侧可靠分离的圆盘，每次新建 `data/intermediate/图片名_UTC时间_随机标识/`，避免重跑时混用旧产物。命令不调用 GPU、ComfyUI 或 Blender。

真实图已验证可使用以下矩形 ROI 单独选择左盘；ROI 参数仅是该图片的示例，不写死在识别代码里：

```powershell
python scripts/analyze_product.py data/input/mmexport1791948355130.jpg --roi 0 250 626 700
python scripts/analyze_product.py data/input/mmexport1791948355130.jpg --instance all
```

`--instance` 支持 `left`（默认）、`right`、`all`。`--roi X Y W H` 为全图坐标中的矩形，右/下端不包含，必须完整包含商品，超界或截断外轮廓会明确拒绝。两个商品连成一片而无法可靠分离时，报告失败并提示设置 ROI，不强行拟合成一个盘。若遮挡导致完整轮廓本身不可见，ROI 也不能恢复未知边界。

每个实例输出五个文件，`--instance all` 时按实例子目录隔离：

| 文件 | 内容 |
| --- | --- |
| `product_spec.json` | 来源、哈希、ROI、实例列表、外圆、完整外轮廓、大型可见开口轮廓、置信度与警告 |
| `outer_contour.png` | 绿色观测外边界、品红色近似拟合圆、红色圆心 |
| `cutouts_overlay.png` | 每个大型可见开口的真实像素轮廓与 H 编号 |
| `product_mask.png` | 实际外轮廓内为白，背景和检测到的大型可见开口为黑 |
| `debug_overlay.png` | 外轮廓、拟合圆、开口与 ROI 的汇总叠加图 |

全部图片保持原图尺寸。JSON 中的轮廓与圆心使用**完整原图**像素坐标，即使输入了 ROI 也不改成 ROI 局部坐标。保存全部 `CHAIN_APPROX_NONE` 轮廓点，不把孔改成圆，也不简化成凸包。闭合轮廓最后一点连接第一点。归一化坐标为 `(point_px - center_px) / radius_px`，无毫米尺度。

孔数由区域检测得到；默认大型开口面积范围为观测盘面积的 2%–25%，且至少 80% 区域有亮中性色证据，同时检查是否处于盘内。中心金属件、螺丝和小辅助孔只保留原图，不做类别识别。`--min-cutout-area-ratio` 和 `--min-neutral-fraction` 可覆盖下限，变化会写入 JSON；无需修改代码。面积过滤对不同型号并不普适，小孔不属于本阶段的目标。

**可见背景开口不等于已验证的加工孔口。** 暗色内壁保留在前景遮罩中，中心小孔尚未抠除，当前遮罩不是生产级完整抠图。封闭白色涂层或高光仍可能与孔混淆，不能从单张图保证其物理类别。所有结果保持 `geometry_verified=false`、用户审核 `pending`、`thickness_mm=null`；置信度是启发式证据分数，不是经过统计校准的概率。外边界偏离理想圆时保留原轮廓并记录椭圆、残差，不自行校正透视。

分析命令退出码：0 表示输出了未经审核的候选结果；1 表示几何识别失败或部分识别失败；2 表示输入、参数或 I/O 错误。大区域证据不足会输出 `partial_failure` 和调试证据；完全定位失败只输出 `status=failed` 的 JSON，外圆为 null，轮廓为空，不生成虚假调试图。输出目录非空时拒绝复用，以免遗留结果混入新任务。

阶段 1A 的独立真实图审阅、具体偏差和验收清单见 [phase1a_results.md](docs/phase1a_results.md)。用户验收通过之前，不开始 1B、1C 或建模。

## 环境检测

在项目根目录运行，无需安装额外 Python 依赖：

```powershell
python scripts/check_environment.py
```

当前工作区根目录已核实为 `D:\xiangmu\kglaoshi\shengtu-skill`。脚本也可以用绝对路径从其他目录启动，它会按脚本位置确定项目根目录。

结果写入 `reports/environment.json`，终端显示每项 `PASSED`、`WARNING`、`FAILED` 或 `SKIPPED`。报告将本机信息放在 `local`，远程推理服务信息放在 `comfyui`，记录 UTC 检测时间。

检测内容包括：

- OS、CPU 架构、Python 可执行文件、环境前缀与已安装依赖版本。
- NVIDIA 驱动、显卡型号与显存；PyTorch 实际导入、CUDA 构建版本及小张量运算。
- NumPy、OpenCV、Pillow、Shapely 的导入情况，导入错误会保留证据。
- `nvcc` 与 Blender 的版本，找不到 PATH 项时标记未确认。
- 项目目录写入权限；可选的本机 ComfyUI 目录检查。
- ComfyUI `GET /system_stats` 和 `GET /queue` 的响应结构与队列数量。

检测不会安装模型、提交工作流、清空队列、卸载远程模型或修改 ComfyUI 配置。局域网 API 直连，不使用系统 HTTP 代理，不跟随重定向。队列工作流内容、系统全部环境变量和服务端启动参数不会写入报告。

## 配置与其他机器

`configs/environment.json` 已填写用户给出的 API 地址 `http://192.168.1.171:8188`。尚未确认的 ComfyUI 路径、Blender 路径为 JSON `null`。

命令行参数可覆盖配置，无需手动编辑代码：

```powershell
python scripts/check_environment.py --comfyui-url http://192.168.1.171:8188 --timeout 10
python scripts/check_environment.py --skip-api --output reports/local_only.json
python scripts/check_environment.py --help
```

`--comfyui-root` 和 `--blender` 接收实际目录或可执行文件路径。只填写已确认的路径；相对路径按项目根目录解析，包含空格的路径需用引号包裹。`--comfyui-root` 只检查**运行脚本这台机器**的目录，不能拿 DGX Spark 的 Linux 路径在 Windows 上检查。

同一脚本可放到 DGX Spark 或最终 RTX 3090 机器上运行，以便确认各自的架构、Python、CUDA 和 Blender。应使用该机器实际环境中的 Python。若需要验证 ComfyUI 的 Python 依赖，使用启动 ComfyUI 的同一个 Python 执行脚本。通过远程 API 读到的系统信息不能替代远程机器的完整本地检测。

配置中的 `local_root`、`blender_executable` 同样按项目根目录解析。个人机器配置可另存为 `configs/environment.local.json`，然后用 `--config configs/environment.local.json` 指定；此类文件已加入 Git 忽略规则。

退出码：

| 退出码 | 含义 |
| --- | --- |
| 0 | 检测已完成，没有必需项失败；可有警告或明确跳过的项目 |
| 1 | 必需项失败，或报告无法写入 |
| 2 | 参数或 JSON 配置错误 |

**不能只看退出码验收。** 必须检查 `acceptance.required_checks_passed`：Python、项目目录、两条 ComfyUI API 检测全部通过时才为 `true`。`--skip-api` 会使状态为 `incomplete`，不会伪造 API 验收通过。

CPU 版 PyTorch、缺少 Shapely 或未确认 Blender 会产生警告，不阻止 Windows 作为远程 ComfyUI 控制端。它们也不能被视为本机推理或后续建模已准备好。GPU 查询中的显存使用 MiB；PyTorch 与远程 ComfyUI 的显存字段使用 bytes。DGX Spark 返回的共享内存数值与 RTX 3090 的独立显存不能直接等同。

## 初始目录

```text
shengtu-skill/
├── pyproject.toml                 # 项目元数据；阶段 0 无运行时第三方依赖
├── README.md
├── configs/
│   ├── environment.json           # 实际 API 地址；未知路径为 null
│   └── workflows/                 # 后续放真实导出的 API 工作流
├── src/product_studio/            # 通用核心与独立插件
│   ├── core/                     # 证据模型、注册路由、任务规划
│   ├── analyzers/                # 接口与通用元数据描述
│   ├── plugins/planar_geometry/   # 阶段 1A 算法与格式适配
│   └── cli.py                    # 阶段 1G 命令入口
├── src/product_photo/            # 历史兼容包
│   ├── __init__.py
│   ├── environment.py             # 环境检测逻辑及 CLI
│   └── extract_structure.py       # 转发到插件的阶段 1A 兼容入口
├── scripts/check_environment.py    # 不安装项目也可运行的入口
├── scripts/analyze_product.py      # 阶段 1A 图片分析入口
├── scripts/analyze_studio.py       # 阶段 1G 通用描述/显式插件/任务规划
├── tests/test_environment.py       # 失败、跳过及验收状态的测试
├── tests/test_extract_structure.py # 合成几何真值、ROI、异常输入与导出测试
├── docs/
│   ├── architecture.md            # 模块边界与真实性约束
│   ├── phase0_results.md           # 阶段 0 实测与已通过验收记录
│   ├── phase1a_results.md          # 历史专项检测记录，审核状态保持未验证
│   └── phase1g_results.md          # 重构步骤、兼容与跨类型测试证据
├── data/
│   ├── input/                     # 参考原图，后续按 SKU/任务隔离
│   ├── intermediate/              # 阶段 1A 任务产物
│   ├── work/                      # 中间产物，后续按 SKU/任务隔离
│   └── output/
│       ├── verified/              # 后续存放可验证的正式商品图
│       └── concept/               # 后续存放有未确认结构的概念预览
└── reports/                       # 检测报告及验证产物，默认忽略
```

`verified` 只是预留目录，不代表当前具备自动验证能力。正式输出准入规则需要在后续阶段实现和测试。阶段 1A 的 `product_spec.json` 来自实际图像分析并保持未验证状态，不生成虚假结构样例或工作流节点占位值。

## 依赖与版本管理

使用 `pyproject.toml` 统一管理项目。阶段 0 使用 Python 标准库，最低语法版本为 Python 3.11，实际测试版本见实测记录；不把当前机器上的 CPU 版 PyTorch 自动复制为部署依赖。

阶段 1A 将已实测的 NumPy 2.4.4 与 opencv-python 4.13.0.92 声明为可选依赖组 `vision`。没有执行安装或升级，不改变已有环境；这些固定版本当前仅实测 Windows/Python 3.13.11，不当作 DGX Spark 或最终 RTX 3090 机器的兼容性结论。新环境需要时可在隔离环境中安装 `.[vision]`；基础环境检测依然只有标准库依赖。

阶段 1G 的数据模型、通用元数据分析器、注册路由与规划器仅使用标准库。图片命令入口使用已安装的 Pillow 12.2.0 读取元数据，单独声明可选组 `image-io`，没有安装或升级。只有显式选择圆盘插件时才加载其 OpenCV/NumPy 算法。保留原分发包名 `product-photo-system`，避免破坏已存在的安装/命令；产品定位与新核心包名分别为 Universal AI Product Photography Studio / product_studio。

后续按阶段确定 OpenCV/NumPy、Shapely、分割模型等版本；首先检查 Python、Windows/Linux、x86_64/aarch64 以及实际导入兼容性，再安装到隔离的项目环境。ComfyUI 的 Python 环境独立保留，不为项目初始化升级它的 PyTorch、模型或节点。最终部署时为已验证的平台分别保存版本锁定清单；当前报告中的 `installed_packages` 只是环境清单，不是可直接安装的锁文件。

直接运行脚本无需安装本项目。如需使用正式 CLI，可在已创建的独立虚拟环境中执行：

```text
python -m pip install -e .
product-photo-check --help
```

安装时构建工具可能需要从包源获取 setuptools；默认环境检测命令没有此要求。阶段 0 未向全局 Python 或 ComfyUI 环境安装任何软件。

## 验证与验收

运行测试：

```powershell
python -m unittest discover -s tests -v
```

阶段 0 验收清单：

- [ ] 项目根目录及预期运行位置已确认：本机配合 DGX Spark 开发，最终部署到 RTX 3090 电脑。
- [ ] 检测脚本可运行并保存有效的 UTF-8 JSON 报告。
- [ ] 本机 Python、GPU 驱动、PyTorch/CUDA 情况已记录，CPU 版不会误标为 CUDA 可用。
- [ ] 两条实际 ComfyUI API 返回有效结构，`acceptance.required_checks_passed` 为 `true`。
- [ ] Blender 与 ComfyUI 安装路径已确认，或明确记录为待补充；不阻止阶段 1 的图片分析。
- [ ] 自动测试通过；失败 API、错误响应、跳过检查不会被标记为通过。
- [ ] 用户审阅报告与限制，确认可以进入阶段 1。

本阶段通过并不意味着 QwenImage 工作流已运行成功、ARM 和 RTX 3090 部署已验证或完整商品图系统已可用。当前尚未取得 API Workflow JSON，不提交生图测试；正式集成安排在阶段 5，并使用实际导出文件。

ComfyUI 探测路由依据：[官方服务端 API 路由说明](https://docs.comfy.org/development/comfyui-server/comms_routes)。


## 阶段 2A：真实商品抠图

模型离线位于 models/segmentation/birefnet-general-lite.onnx，CPU 运行。当前独立启动环境只读复用现有依赖，没有升级全局环境。首次新机器安装请先检查 Python/依赖，再使用 scripts/setup_segmentation.py；只有显式 --download 才下载已固定哈希的一个模型。

```powershell
.venv-seg\Scripts\python.exe scripts/segment_product.py segment data/input/手提包.jpg --single-instance --instance-id bag
.venv-seg\Scripts\python.exe scripts/segment_product.py segment data/input/mmexport1791948355130.jpg --roi 0 250 626 700 --instance-id blue_left
python -m unittest discover -s tests -q
python scripts/validate_phase2a_assets.py
```

输出完整原图尺寸的透明 PNG、Alpha、原始模型遮罩、深浅背景与棋盘预览、来源快照和审核请求。--single-instance 是用户声明；多实例必须指定 ROI，必要时 --keep-point 点选。所有结果默认 pending。外部修正、具名审核命令、模型许可证、真实质量缺陷及环境限制见 [阶段 2A 记录](docs/phase2a_results.md)；机器可读结果见 [验收报告](reports/phase2a_validation.json)。

最终测试 94 项通过，其中原有 64 项；真实 8 张照片共 11 个目标，包含手提包、耳机、腕表。蓝色自动孔洞抠图未通过质量验收，修正候选也需要审核；所有真实样例人工状态仍 pending。

## 阶段 2A-Fix：质量修复候选

保留 BiRefNet Lite，新增明确 trimap/前景保护/背景点驱动的 OpenCV 局部修复。左右蓝盘大块白色残留已在真实候选中清除，中心小圆保持不变且待实物确认，细孔边仍需审核。银/黑/红盘、包、耳机、腕表完成保守零变化回归，不代表其所有原有细节已经验证。

111 项测试通过；没有新依赖或新模型。见 [修复记录与运行方法](docs/phase2a_fix_results.md)、[前后对比](reports/phase2a_fix_comparison.png)、[蓝色细节](reports/phase2a_fix_blue_detail.png) 和 [验收 JSON](reports/phase2a_fix_validation.json)。所有候选 pending，等待阶段 2A-Fix 验收；未开始 2B。

## 阶段 3A：QwenImage 背景与原图商品合成

蓝色左右最新中心孔mask已实测具名审核有效（mh）。本轮生成 blue_left 三张strict遮罩流程图片、手提包三张preview图片。strict只表示前景审核有效，新背景与最终合成仍待视觉验收。

```powershell
python scripts/run_phase3a.py
python scripts/validate_phase3a.py
```

真实工作流来自远程成功API任务副本，节点和模型未编造；配置在 configs/comfyui_phase3a.json 与 configs/phase3a_scenes.json。纯白由Python生成，影棚与场景通过实际QwenImage调用。已有成功任务仅在来源/配置/哈希一致时复用；新一轮可用 --output-root 指定新目录。

[阶段3A记录](docs/phase3a_results.md)、[六图汇总](reports/phase3a_comparison.png)、[验收JSON](reports/phase3a_validation.json)。没有重绘商品、制造新角度或进入2B。

## 阶段3B：高级场景候选与推荐

新增两种正面无地平线场景预设，蓝盘和手提包各两个真实QwenImage候选，共四个新增任务。按硬约束和明确启发式排序；主观视觉质量始终待审核，不存在自动AI审美评分。当前均推荐B、保留A；蓝盘strict指前景审核有效，手提包仍preview，最终资产都pending。

```powershell
python scripts/run_phase3b.py
python scripts/validate_phase3b.py
```

相同成功任务命中缓存，不重复提交。图集配置为configs/phase3b_product_set.json，场景预设为configs/scene_presets.json。可选 --ranking-file 调整硬通过候选顺序，不能代替审核。

[3A/3B对比](reports/phase3b_comparison.png)、[结果记录与评分边界](docs/phase3b_results.md)、[真实任务验收报告](reports/phase3b_validation.json)。原140项测试加新增21项共161项通过；原3A图片、日志及来源资产保持不变。
