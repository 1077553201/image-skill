# 阶段 4B：通用商品创意引擎与 Skill MVP

2026-10-15。完成真实开发与跨品类执行，**待用户视觉验收**。最终入口对三类商品相同，不要求修改核心 Python、逐张设置坐标或 seed，也不修改 ComfyUI 节点。

## 交付结果

| 商品 | 最新目录 | 图数 | 遮罩模式 | 视觉方向 |
| --- | --- | --- | --- | --- |
| 包袋 | data/outputs/phase4b/bag_v2 | 6 | preview | 象牙/焦糖暖色，Georgia 衬线字，时尚编辑风格 |
| 耳机 | data/outputs/phase4b/headphones_v2 | 7 | preview | 石墨黑/鼠尾草灰，现代音频外观设计 |
| 蓝盘 | data/outputs/phase4b/blue_left | 7 | strict：当前有效 mh 遮罩审核 | 冷蓝建筑/科技编辑风格 |

合计 **20 张**，每套都有白底、商业主视觉或影棚、事实信息图、真实局部细节、环境场景和广告横幅。包袋以可见提手、纹理和扣件为内容；耳机展示耳罩、头梁和黑色外观；蓝盘有独立结构与规格说明。三份 Creative Plan 的数量、意图和文案不同，不是固定八图目录。

总览：`reports/phase4b_comparison.png`。各套 `creative_set_contact_sheet.png` 可单独看清；各意图子目录中的 `final.png` 是独立成品。

## 审计与最小改造

实施前审计在 `docs/phase4b_generality_audit.md`。实际发现并修正：

- 旧 create_plan 强制八张，改为可变数量；旧入口保留。
- 总览固定两行，改为按图数计算。
- 原渲染器读取低层坐标；新增通用布局编译器，根据当前 Alpha 边界、长宽比、输出尺寸和安全区域生成坐标与统一缩放。
- 文字加入文本框换行、字号适配、显式标题换行偏好及溢出报错，绝不静默截断。
- 参考分析 Markdown 曾带有本轮样例的固定图数/A+ 说明，改为按当前分析数量与 catalog 表述。原 4A 文件保留。
- 独立背景可明确等比例 cover/crop 适配横幅；这种适配只作用于背景，不作用于商品。

源代码没有蓝盘类别、三个孔、30 cm、500 g 或复合材料作为生成条件。旧 palette 的 blue/cyan 是兼容风格 token 名称，包袋实际取棕色，耳机取灰绿色，默认取中性灰，不能据名称认为商品必须蓝色。旧的圆盘插件和 4A 案例配置完整保留；无孔商品流程不执行圆盘结构算法。

没有重写 Provider、Compositor、Evidence/schema、分割模型或审核机制。没有安装新依赖、模型或修改 DGX Conda。

## 通用请求与 Agent 交接

`configs/campaign_request.schema.json` 定义输入，`creative/campaign.py` 做运行时校验和默认处理。支持 product_image 或 product_asset（二选一）、product_id、可选类别/事实/参考/风格，以及平台、语言、图数、尺寸、创作模式、预算和审核策略。任意扩展属性通过事实字典和 fact_kinds 表达，不要求直径、孔或螺丝字段。

已有资产读取真实 segmentation_result 与 product_spec，核对原图/Alpha/RGBA 哈希和版本；auto 模式只有当前真实具名审核有效时才用 strict。包袋、耳机、腕表及新增银色 SKU 均保持 preview，没有代用户批准。

原图输入复用现有 segmentation CLI。必须由 Agent/用户明确 ROI 或单实例声明；无法区分时暂停，不能合并商品。缺视觉数据时返回 exit 2、needs_agent_analysis 和 handoff，而不是假装完成商品识别。交接中的 source_image 从实际规格来源读取，支持 PNG/JPEG 等真实后缀，不猜 source_original.jpg。

Agent 实际看图后提供 product_understanding.4b.1：来源绑定、可见视角、观测事实、特征、原图细节窗口、意图建议、原创文案与风格。事实和文案绑定当前商品，视觉观测不得自升 human_verified；性能/兼容/材料成分等不能仅凭外观填写。人类参数需要实际用户陈述、reviewer 与 product_id 来源。未知属性为 null。

本轮视觉理解仍由当前 Agent 工具承担，未额外配置 VLM。新商品的观察、文案和背景 brief 是 JSON 数据，不是商品专用 Python。缺少图像能力的 Skill 环境必须暂停或取得可靠分析，**不是无人值守自然语言 Agent 服务**。

## 创意意图和场景能力

十一类 ShotType 均定义适用条件、素材、事实要求、策略、版式、真实性、平台与回退：white_hero、studio_photo、brand_signature、feature_infographic、material_detail、structure_explainer、specifications、lifestyle_scene、editorial_campaign、wide_banner、comparison。

本轮包袋/耳机没有尺寸和材料成分，因此没有生成尺寸图、真皮、容量或性能宣传；耳机没有 ANC、续航、蓝牙或音质声称。对比图缺实际已验证资料时跳过；没有生成假的竞品对比。comparison 是有证据的数据/排版扩展点，本轮没有真实比较数据验收，不宣称完成了自动竞品性能研究。

Level 1：现有原像素前景＋独立背景。Level 2：实际生成包含建筑、窗、植物、家具/木饰面的环境，前景处于清晰的平面广告面板中，不假装放在透视桌面上或与场景发生接触。所有环境图使用同一原图视角，不修改姿态和隐藏面。Level 3 返回 interface_only/unsupported；concept_creative 仅是明确标记的路线，不代表已经实现生成。没有人物穿戴或手持图。

## 真实背景及参考

每商品两个新任务，总计 **六次真实 QwenImage 2.1 调用**，所有任务的远程 history、提交图哈希、下载图片哈希已核对。商品和竞品图片均未送入生成模型。

| 商品 | 背景 | prompt_id | seed |
| --- | --- | --- | --- |
| bag | environment | fb92be58-8e05-4062-b56f-ca7f437f4bce | 2699166622 |
| bag | studio | b6c4f668-ed1a-4b00-86b0-5af96d8b3581 | 851831448 |
| headphones | environment | f5098b51-153b-4594-bc6f-38696ba67a75 | 2033675200 |
| headphones | studio | 07c5443d-ac3d-4491-b075-274cabaa8101 | 3481157374 |
| blue_left | environment | 909205dd-78a4-424f-b837-08dc25c9d0aa | 4047480552 |
| blue_left | studio | 0521f551-564c-4ea8-b669-bcad56184ec7 | 308585544 |

工作流与实际模型信息在各任务 execution/model_nodes 中；原模板 SHA-256 仍为 `580a958bfb5f679d0b2cb79fda32b965a28f31a667e992e43fb5a258720c699b`。原始图、graph、history、seed、prompt 和状态均在各首版商品目录的 background_tasks，v2 记录父缓存来源。总览：`reports/phase4b_backgrounds.png`。

科技方向复用已真实获取的 Amazon 八图分析。时尚方向使用项目自己阶段 3B 的暖色包袋成图作为本地参考，已实际读取并重新作十四维分析，保存在 `data/references/phase4b_fashion_local/`。它是自己的 AI 背景＋真实前景合成，不是新抓取的时尚品牌营销页，未伪装为外部竞品研究。参考像素不作为成品图层。

## 实图驱动修正与恢复

先完成包袋，看到标题分词过碎和细节窗格间距偏紧，修复通用换行与窗格间距后生成 bag_v2。再完成耳机与蓝盘。耳机的第二版只调整数据文案，去掉偏实现说明/易歧义的措辞，使用同一核心和原背景；初版完整保留。

还验证并修复了两个通用交接问题：暂停的请求补入 Agent 分析时可继续，并保存 request_before_handoff 历史；白底最小任务不需要 ComfyUI 配置或模型；PNG 交接读取真实源路径。

已成功任务有不可覆盖缓存；恢复查询原 prompt_id，不盲重试、不 interrupt 别人的任务。新请求/文案版本使用新目录，支持显式复用同源/同实例/同 mask/同工作流参数的父背景。通过 Skill 启动器在冻结代码后复跑三套成品，全部成功、**新增任务零**。日志：`reports/phase4b/frozen_cli_smoke.json` 和 skill_smoke_*.txt。

## 冷启动与通用性证据

- 腕表此前只有分割资产，没有创意布局/场景配置。新增最小 Campaign Request 与观测 JSON，通过同一 Skill 启动器生成真实白底图，默认中性风格、零 AI 预算、未知参数保持未知。其横向主体没有旋转或拉伸。
- 完成 PNG 交接路径的通用修正后，重新冻结最终 **65 个 Python 文件**，再选择此前无创意配置的银色 SKU 做第二次冷启动。只新增两个 JSON 数据文件，同一入口生成一张真实白底图；冻结前后源码列表和哈希完全相同。腕表初次冻结/验证证据另行保留，不用缓存重放冒充最终版本的新资产首跑。
- 两个冷启动只验证通用最小流程与资产保真，不冒充完整六图集或全品类质量验证，均为 preview。银色中心结构及孔边未获人工批准，没有继承蓝盘的孔洞确认或尺寸材质。

最新冷启动：`data/outputs/phase4b/cold_start_new_sku/`，附加腕表：`cold_start_watch/`。它们不计入主验收的 20 张。`core_frozen_before_cold_start.json` 以及最终报告记录完整文件哈希与结果。

## 自动化与质量结果

**224 项通过：原有 195 项＋新增 29 项，零失败、错误或跳过。** 包括：可选输入、请求校验、SKU 事实隔离、未知值、人类确认来源、Agent 不自升审核、性能不凭空推断、动态意图/事实缺失回退、场景等级拒绝、四种长宽比、等比例映射、真实细节范围、文字换行/溢出、无视觉交接、PNG 路径、strict 门禁、无网络白底执行、请求历史与恢复、输出路径保护。单元测试中的模拟模型与真实六个任务分别记录。

所有实际成品检查尺寸、PNG 完整性、来源/实例/遮罩版本、原 RGB/Alpha 快照、精确重算合成、主商品像素不被图文覆盖、商品范围内透明像素透出布局背景、真实细节窗口逐像素重现、等比例变换、文本安全区/对比度和 pending 状态。Level 2 检查真实背景来源与明确图文面板。包袋/耳机文案未混入蓝盘 30 cm、500 g、复合材料。

**1001 个此前资产/4A 图片配置/参考图/工作流哈希不变。** 具名遮罩审核记录未改动。模型/Provider/Compositor 继续复用。实图总览、环境图、规格图和冷启动已由 Agent 观察；原图细亮边、未审核前景风险、素材清晰度仍需用户逐图验收，自动检查不等于语义、审美、全部边缘或平台合规证明。

## 正式 Skill MVP 与运行

Skill 文件：`skills/universal-product-creative/SKILL.md`；依照 skill-creator 规范编写并通过 quick_validate。配有真实启动器、Agent 数据契约与恢复说明，启动器实际调用统一 CLI 和质检工具，不是纯提示词文档。

项目内可显式读取 SKILL.md 使用，或运行启动器。**没有擅自安装到全局 Skill 目录**；创建文件不代表客户端已自动发现该 Skill。没有做独立子 Agent 的无人值守前向测试；已做实际工具启动、三类真实执行和冷启动验证。

统一入口：

```powershell
python scripts/generate_product_campaign.py --request configs/examples/bag_campaign_v2.json
python scripts/generate_product_campaign.py --request configs/examples/headphones_campaign_v2.json
python scripts/generate_product_campaign.py --request configs/examples/blue_disc_campaign.json
```

当前请求已有成功缓存，以上命令不会再生成同一背景。纯本地复核可追加 `--render-only`。完整 Skill 工具路径：

```powershell
python skills/universal-product-creative/scripts/run_campaign.py --request configs/examples/bag_campaign_v2.json --render-only --validate
python scripts/validate_phase4b.py --run-tests --remote
```

第二条只读核查远程任务，并运行自动化回归；不追加生图。单商品质检入口 `scripts/validate_product_campaign.py --output <目录> [--remote]`。自然语言使用时明确要求 Agent 读取项目 Skill 文件，再由其组织请求与视觉交接；用户无需编写 Python。

## 文件与限制

新增 creative/{campaign,intents,layouts,executor,quality}.py，统一生成/质检/阶段验收 CLI，Campaign Request schema、商品请求和观察 JSON、test_campaign.py、Skill 文件与启动器、状态及本报告。最小修改 planning.py、marketing_renderer.py 和 references/analysis.py。各请求、计划、事实、任务、变换、图文质检及历史保存在独立输出目录。

未新增 Python 依赖；使用现有 Python 3.13.11、Pillow/NumPy/OpenCV、BiRefNet 与 QwenImage。真实原图输入重新分割分支复用旧工具，本轮主验收使用已有分割资产，未将其宣传为一次新的原始图片批量抠图验收。实际营销样例为英文；中文合同/字体配置路径存在，尚无中文商业套图视觉验收。字体默认基于当前 Windows，迁移时要指定实际可用字体。实际营销尺寸验收为 1024×1024 和 1536×864；更小画布、更多文案或用户自定大安全区可能触发排版拒绝，不能据输入 schema 允许尺寸就保证任意文案均能排入。

不同商品已有不同计划，但目前版式家族仍有限；尚未真实覆盖全部商品、透明物体、反射复杂物体、精确佩戴/手持或比较图数据。背景/布局/文案和 source mask 审核是不同状态。所有新资产仍 **pending**；只有蓝盘遮罩门禁 strict 有效，不能据此将其营销图标记为人工批准。平台类别与营销渠道需另行确认，文字营销图不能直接当作 eBay listing photo 合规图片。

本阶段到此停止。请审核三套总览、原尺寸 final.png、事实文案和环境面板效果后决定验收。
