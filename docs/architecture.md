# Universal AI Product Photography Studio 架构

产品定位：通用 AI 商品摄影与多视角生成系统。电子产品、饰品、箱包、化妆品、金属零件、家居用品和圆形转盘都通过同一通用规格与真实性机制管理。几何测量按插件扩展，不作为所有商品的前提。

阶段 0 已验收；阶段 1A 的成果保留为独立专项插件；阶段 1G 重构已实现并等待用户验收。原阶段 1B 暂停。后续通用抠图和视觉商品理解需用户新授权后开发。

## 当前实现与依赖边界

```text
product_studio/core/schemas.py        通用规格、证据状态与 JSON 验证
product_studio/analyzers/base.py      分析请求、结果及 Analyzer 接口
product_studio/analyzers/generic.py   元数据与明确实例描述；不是视觉理解模型
product_studio/core/registry.py       显式注册、单插件路由、跳过/失败记录
product_studio/core/task_planner.py   六种策略的真实性条件与来源记录；不执行
product_studio/plugins/               注册组合入口；惰性创建专项插件
  planar_geometry/legacy.py           阶段 1A 原算法，内容完整迁移
  planar_geometry/analyzer.py         专项接口和新旧格式适配
product_studio/cli.py                 描述、显式插件及计划的命令入口
product_photo/environment.py         原环境检测，保留
product_photo/extract_structure.py   原专项导入路径兼容转发
```

核心、接口和通用分析器不导入 plugins 或 product_photo，也不导入 OpenCV/NumPy/Pillow。组合入口注册 generic_product 与 planar_geometry，不把未实现的插件注册为成功分析器。CLI 的图片元数据读取使用 Pillow；只有选中蓝色圆盘插件时才加载旧像素算法。测试检查实际 Python 导入图无循环，并用禁用 site-packages 的独立 Python 证明核心通用路由可运行。

## 通用 product_spec

新 schema_version 为 studio.1g.1，字段如下：

| 字段 | 用途 |
| --- | --- |
| product_id | 独立商品记录标识；实例分别建记录，不自动合并 SKU |
| source_images | 来源 ID、路径、SHA-256、像素宽高 |
| product_category | 类型证据；未知时 value=null，不从几何直接断言类别 |
| detected_instances | 明确提供或算法检测的实例、来源、ROI、证据、可选 SKU |
| selected_instance | 当前记录对应实例；没有实例证据则为 null |
| visible_view | 可见视角证据；猜测不能作为目标角度验证依据 |
| product_mask | 遮罩证据、资产位置、质量范围；未知时为 null |
| geometry_features | 插件名称到证据记录的对象，可为空，不要求任何固定形状 |
| appearance_features | 外观证据扩展；当前通用分析不自动填颜色、材质 |
| protected_regions | Logo、文字、接口等保护区域证据；当前未自动检测 |
| verified_facts | 仅接受具名人工确认事实 |
| unknown_properties | 值和置信度均为 null 的未知项 |
| confidence | 可选分数；插件详细分数保留在插件命名空间 |
| human_review_status | pending / partially_reviewed / reviewed / rejected |
| analysis_records / warnings | 能力范围、方法、跳过、失败和不确定记录 |

每条 Evidence 记录 value、status、sources、method、confidence、reviewer 和 note。五种状态分别为 observed（原图观测）、estimated（算法/输入标注估计）、human_verified（具名人工确认）、unknown（未知）和 conceptual（仅概念推测）。非未知属性必须有来源和方法；unknown 不能携带虚构数值或高置信度；自动转换不能提升验证等级。

字段缺失/为空不代表已经检测确认不存在该特征。通用元数据分析将未实现的颜色、材质、保护区域、实例总数等明确记为未知，并写 metadata_only 记录。ROI 是来源图的矩形实例标注，不是像素分割 mask。

## 专项插件与兼容

当前 planar_geometry 仅有 blue_disc_phase1a 变体，包含蓝色阈值、圆拟合、孔筛选、半径归一化和专有调试图。名称不代表已经实现一般平面商品分析。rigid_object、soft_goods、transparent_object 等只是设计扩展点，选择时记录 skipped。

旧 CLI、product_photo.extract_structure 导入路径、测试、1a.1 JSON 和历史产物继续保留。新规格将圆盘数据放入 geometry_features.planar_geometry；其中原始边界为观测证据，拟合圆和可见开口为估计证据，legacy_payload 保留完整旧 JSON。to_legacy_spec 可无损返回旧数据；普通商品不能反向编造圆盘格式。

一张图中多个实例分别有 product_id 和 selected_instance。SKU 可由输入显式指定，未知则为 null；两个物体即使看起来相同也不自动合并。当前路由只选择一个专用分析器，不将不同分析器自行猜出的实例 ID 拼接为同一商品。

## 最小任务规划

计划包括策略、当前实例、来源图哈希、目标视角、真实性等级、待满足条件、状态和执行标记。真实性等级描述的是策略与证据基础，不是已生成图片的验证结果；所有计划 output_verified=false，execution_status=not_implemented_in_phase1g。

| 策略 | 基础真实性及准入条件 |
| --- | --- |
| original_composite | 保留原像素的意图；需要完整人工审核 mask，不能引入隐藏角度 |
| ai_background | 商品前景保真意图；还需真实 Workflow 和 Provider |
| visible_crop | 只规划当前实例的可见像素裁剪；未知/隐藏角度被阻止 |
| multi_reference_edit | 需验证；多张图须人工确认同一商品，不能按文件放在一起而合并 |
| verified_geometry_render | 需具名确认的模型资产及覆盖目标角度的 verified_views；渲染后端未实现 |
| single_image_concept | 始终 concept_only，需明确允许；侧面/背面推测不当真实商品图 |

planned 仅表示已满足当前规划条件，不表示执行。未配置 Provider、完整 mask、目标角度证据或渲染后端时为 blocked，保留原因。插件估计的圆、孔和部分 mask 不能满足正式模型/完整遮罩条件。

## 待实现的独立能力

| 模块 | 设计边界；当前未实现 |
| --- | --- |
| 通用视觉理解 | 模型输出类型、可见外观/结构、保护区域与未知项，附来源；分类不等于尺寸测量 |
| 通用实例分割 | 阶段 2A 已实现 BiRefNet Lite、ROI/点选、外部 mask 修正与审核；尚无自动多实例检测 |
| 图像生成 Provider | 统一生成请求/结果与能力声明；ComfyUI 使用实际 API Workflow，GPT Image 等独立接入，不反向依赖分析器 |
| 通用质量检查 | 形状、mask、文字、颜色、零件、分辨率、瑕疵；看不到的部位返回不可验证 |
| 专项质量扩展 | 插件可添加孔数量/轮廓等检查，不进入所有商品默认规则 |
| 合成与生产编排 | 资产来源、任务状态、审核、失败恢复、正式/概念隔离；不在阶段 1G 假装实现 |

没有机械创建这些模块的空实现或假的成功结果。优先复用现有 QwenImage 工作流；节点、模型文件名与连接只能依据用户实际导出的文件接入。

## 运行环境与真实性约束

开发为本机加 DGX Spark，最终统一部署到 RTX 3090 电脑；最终 OS/Python/CUDA 仍需部署前实测。DGX Conda 环境按用户要求暂不调整。Blender 未安装，优先避免；几何渲染路线后续再按实际产品证据评估。

真实厚度、背面、隐藏零件、材质成分没有证据就未知。原图可见开口不等同前表面加工孔口。二维透视变换不是三维结构恢复；概念推测不能用于正式真实性验证。人工审核决定哪些事实已确认，不因自动化测试通过而提升。

## 阶段 2A 的最小扩展

segmentation/base 定义接口，provider 仅运行固定哈希的离线 ONNX 模型；mask_processing 管理全图/ROI 坐标、透明度与原像素预览；quality 输出风险指标，不作人工确认；pipeline 管理资产、旧规格接入、外部修正与具名审核；cli 提供命令行闭环。无圆盘专有规则，蓝色修正候选只是验收数据。

core/asset_binding 只依赖标准库，验证来源、实例、ROI、mask 版本、RGBA 与具名审核记录。task_planner 使用该验证器阻止过期/跨实例遮罩进入正式计划，不导入 segmentation 或 CV 库。只有 segmentation 的旧规格适配显式调用 planar_geometry adapter；通用核心与插件没有循环依赖。

真实 mask Evidence 为 estimated，审核只提升该实例该版本的 product_mask；全商品最多 partially_reviewed。所有生成策略仍只规划而不执行。当前通用质量检查只实现 mask 风险，文字、颜色、部件语义检查未实现。

## 阶段3A的最小执行路径

providers/comfyui 使用明确配置的真实API模板，生成独立空背景；generation/compositor 从来源/实例绑定的mask资产读取原RGB，校验当前具名审核，再进行统一缩放与平移。输入商品不发送给QwenImage。run_phase3a 按显式配置选择场景并执行六张验证，不扩展通用Agent或重构旧规划器。strict与preview由实际资产门禁决定，生成后的视觉审核独立保持pending。

模型、节点与参数映射均从真实history/object_info读取；源工作流不变，每任务保存提交副本、prompt_id、种子、哈希与下载结果。通用schema/分割与圆盘插件没有反向导入生成后端。旧task_planner仍是阶段1G规划接口，本轮执行入口是显式场景脚本，不通过伪造规划成功启动生成。

## 阶段 4A：Agent 视觉研究与确定性商业排版

用户已验收阶段 3B。参考源由 references/sources 处理，公共网络采集使用独立于 ComfyUI 内网客户端的 HTTPS 安全策略，保存不可覆盖的来源图片、哈希与获取缺失记录。references/analysis 验证 Agent 逐图分析与实际文件的绑定，不将商品标题或 QwenImage 文本编码器当作视觉理解结果。

按用户最新要求，视觉理解和创意决策由具备图像能力的 Agent 工具负责，Python 不另部署 VLM。Agent 实际读图后提交 reference_style 和逐图 brief；缺少该分析时不能跳过验证假装完成。此次没有提前实现完整 Agent 框架或最终 Skill。

creative/planning 复用 Evidence 状态校验独立商品事实清单，再将设计配置、已审核前景绑定、参考分析与事实哈希组成八张设计计划。商品尺寸、文案、局部窗口、构图和可选专用结构均位于案例配置，通用代码没有圆心、孔数或蓝色阈值规则。平台预设独立存储，主图与营销图分别检查，不能自动宣布平台审核通过。

generation/marketing_renderer 复用现有 compositor 生成受保护商品图层，在背景层绘制图形，使用明确原图区域制作细节窗口，并用 Pillow 渲染确定性文字。营销文字不得覆盖主体像素。独立背景由既有 QwenImage Provider 和 BackgroundCache 实际生成；派生背景裁剪需显式记录，商品仍仅做等比例缩放/平移。

新执行脚本 generate_creative_set 读取 Agent 完成的设计配置，生成或复用背景后输出每张图及追踪清单。validate_phase4a 单独核查真实远程历史、工作流、所有来源绑定和合成重现；测试中的模拟后端不能代替真实任务记录。背景、Agent 视觉判断、商品遮罩与最终图片人工审核仍是四个不同状态。

## 阶段 4B：通用 Campaign 与 Skill 入口

creative/campaign 管理请求默认值、实例绑定的 Agent 观察和自有事实；intents 注册十一类意图并按证据选取，明确 Level 1/2/3 能力；layouts 根据 alpha bbox、长宽比和画布编译声明式构图；executor 负责选择/复用分割资产、参考交接、动态计划、持久缓存和执行历史；quality 按当前商品检查像素与来源，不含圆盘探针。

generate_product_campaign --request 是新商品通用入口，旧 4A CLI 保留。商品事实、原始细节窗口、文案和风格放在输入 JSON，不通过 SKU 分支选择 Python。商品标识与 instance_id 分开；未知属性为 null，Agent 观测不能自升人工审核。没有独立视觉服务时，Skill 使用宿主 Agent 的图像工具；没有该能力就停在结构化交接。

marketing_renderer 继续调用既有 compositor，仅增加可选文本框换行、动态总览、显式背景尺寸适配和环境图文面板。真实产品统一缩放/平移，图文不覆盖前景像素。Level 2 不伪造接触关系；Level 3 仅数据/真实性接口，不生成穿戴、手持或遮挡。审核仍独立 pending。

skills/universal-product-creative/SKILL.md 连接实际 CLI、视觉观察、事实整理、意图规划、生成、质检和用户审核。启动器支持定位项目，既不复制引擎也不启动后台 Agent 服务。项目文件存在不等于客户端自动发现或无人值守完成；实际三类执行、冷启动及技能格式验证分别记录。
