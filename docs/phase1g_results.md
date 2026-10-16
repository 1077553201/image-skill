# 阶段 1G：通用商品分析架构重构与验收

产品名称：**Universal AI Product Photography Studio / 通用 AI 商品摄影与多视角生成系统**。

本阶段实现与测试完成，等待用户验收。原阶段 1B 暂停；没有开始通用抠图模型、视觉商品理解、3D、生图、Web UI 或完整 Agent。

## 检查结论与重构范围

原阶段 0 的环境检测无需重构，保留原文件与测试。阶段 1A 的蓝色阈值、圆/椭圆拟合、孔面积筛选、半径归一化、中心区域排除与专有调试图都属于商品插件能力。旧顶层 outer_circle/cutouts 不作为通用规格必需字段。

采用最小增量方案：新增 product_studio 通用包，原 product_photo 包、分发包名、脚本入口和历史文件保留。旧识别算法完整复制迁移到 plugins/planar_geometry/legacy.py，原模块转为显式兼容导出，没有重写算法，也没有修改原有两份测试。

实际新增文件：

- `src/product_studio/core/schemas.py`：通用规格与证据验证。
- `src/product_studio/analyzers/base.py`、`generic.py`：接口与元数据/输入实例描述。
- `src/product_studio/core/registry.py`：惰性工厂注册、显式单插件路由、跳过与失败记录。
- `src/product_studio/plugins/planar_geometry/legacy.py`、`analyzer.py`：原算法和新旧格式适配。
- `src/product_studio/core/task_planner.py`：六种策略的真实性、来源与前置条件。
- `src/product_studio/cli.py`、`scripts/analyze_studio.py`：可运行的阶段 1G 描述/分析/规划入口。
- `tests/test_studio_schemas.py`、`test_studio_routing.py`、`test_studio_cli.py`：通用、跨几何类型、真实性、兼容和命令测试。
- 包初始化文件与本记录。

修改旧 `extract_structure.py` 为兼容转发；更新 pyproject 的产品描述、CLI 与 Pillow 可选 image-io 组，更新 README 和架构说明。现有 NumPy/OpenCV/Pillow 直接复用，没有安装或升级依赖，没有改动 DGX 环境。

## 通用数据模型与兼容

新规格 studio.1g.1 包含 product_id、source_images、product_category、detected_instances、selected_instance、visible_view、product_mask、geometry_features、appearance_features、protected_regions、verified_facts、unknown_properties、confidence、human_review_status 及分析记录。完整字段说明见 architecture.md。

geometry_features 可以为空，并按插件命名空间扩展。Evidence 区分 observed、estimated、human_verified、unknown、conceptual，包含来源、方法、可选置信度与审核人。未知值和置信度为 null；非未知属性必须有来源和方法；人工确认必须有具名 reviewer；来源与实例必须关联已记录的图片，ROI 不能越界。

旧 CLI 和 1a.1 JSON 不变。通用圆盘特征位于 geometry_features.planar_geometry，保留完整 legacy_payload；外像素边界属于观测，圆拟合与可见开口属于算法估计。to_legacy_spec 可无损转换回旧格式，普通商品不能凭空转换成圆盘。转换不提升 geometry_verified/human_review 状态。

同图多个实例分别得到 product_id 和 selected_instance；SKU 未提供时保持 null，不靠图片相似度补齐，也不自动合并。通用描述中的实例由输入 ROI 或专用算法提供，不假装已有通用实例检测。实例列表与插件特征不会跨记录共享可变列表。

## 分步实施与测试

每步实际运行 `python -m unittest discover -s tests -q`：

| 步骤 | 结果 |
| --- | --- |
| 重构前基线 | 原 38 项通过 |
| 通用模型/接口/元数据分析器 | 46 项通过 |
| 原算法迁移与兼容入口 | 46 项通过，原 38 项仍通过 |
| 注册路由、适配与任务规划 | 59 项通过 |
| 新 CLI 与集成测试 | 63 项通过 |
| 同图跨实例资产绑定约束 | **64 项通过** |

最终为原 38 项 + 新增 26 项。测试中一次括号语法错误已修正后重跑通过，未绕过失败测试。

新增测试证明：

- 任意商品可生成无圆/孔字段要求的通用规格并 JSON 往返；五种证据状态保留。
- unknown 不能填虚构默认值，估计不能进入 verified_facts，无来源或无人工审核人的确认被拒绝。
- 无实例资料时不虚构一个商品；提供不同 SKU 的两个实例时分别输出，修改一份列表不影响另一份。
- 矩形、细长椭圆、不规则柔性形状三类合成图通过通用接口，圆盘专用分析明确 skipped。
- 未注册插件或插件内部错误保留通用结果，分别标记 skipped/failed；不能制造 processed 空结果或 skipped 假产物。
- 新旧圆盘格式无损往返，通用顶层不出现圆盘字段，不提升验证状态。
- 禁用 site-packages 的独立 Python 可运行通用核心与路由，没有加载 cv2/numpy/PIL；实际源码导入图无循环，核心没有插件反向依赖。
- 隐藏角度、猜测模型、部分 mask、无实例、多参考图未确认同商品等情况不能走正式策略；同图另一实例的审核 mask/模型也不能串用。
- 概念始终标为 concept_only；有人工模型证据也不意味着已有渲染后端或已生成验证图片。
- 新 CLI 读取输入、导出多实例/不同 SKU、保留旧插件文件、记录计划及 generation_executed=false。

## 真实蓝色转盘回归

输入仍为 `data/input/mmexport1791948355130.jpg`。首先通过旧兼容接口重新分析，与历史 `data/intermediate/blue_left/` 对比：

- 除运行时间、保存资产列表和来源元数据这些运行相关字段外，所有旧结构字段一致。
- 四张调试图逐像素相同。
- 历史五个文件的 SHA-256 在新 CLI 运行后仍相同，未覆盖历史产物。
- 左侧仍为 3 个大型可见开口，圆心 (315.456839, 593.606650) px，半径 312.339950 px，RMSE 2.448339 px。

证据：`reports/phase1g_planar_regression.json`。

新通用入口实际执行：

```powershell
python scripts/analyze_studio.py data/input/mmexport1791948355130.jpg --analyzer planar_geometry --strategy visible_crop --output-dir data/intermediate/phase1g_blue_final
```

导出两个独立实例，每个 `product_spec.json` 是 studio.1g.1；实例下 `planar_geometry/` 有旧规格和四张图。两实例各有 3 个大型开口，所有 mask 为 partial、与实例显式绑定，类别仍未知，用户审核仍 pending。新规格中的旧 payload 与同时保存的旧 JSON 完全一致。

主要实测产物：

```text
data/intermediate/phase1g_blue_final/
  run_manifest.json
  instance_001/product_spec.json
  instance_001/task_plan.json
  instance_001/planar_geometry/{product_spec.json,四张调试PNG}
  instance_002/...同样独立输出
```

## 跨类型验证范围

实际创建并运行三类合成输入（不是实际商品照片）：

| 合成样例 | 来源 | 产物目录 | 专项分析 |
| --- | --- | --- | --- |
| 蓝色矩形设备 | phase1g_synthetic_inputs/rectangular_device.png | phase1g_device | skipped，不强行拟合圆 |
| 绿色细长瓶体 | phase1g_synthetic_inputs/elongated_bottle.png | phase1g_bottle | skipped |
| 橙色不规则包袋 | phase1g_synthetic_inputs/irregular_bag.png | phase1g_bag | skipped |

以上路径均位于 data/intermediate/。各样例以显式 ROI 和 SYNTHETIC SKU 验证接口，导出通用规格，geometry_features 为空；类别、材质、颜色、视角、mask 未填写推断值。样例名称和 SKU 是测试标注，不是算法分类结果。

**尚未经过真实跨品类验证。** 本阶段证明数据模型、插件跳过、实例绑定与路由兼容性，不证明通用视觉理解或通用抠图能力。

## 任务规划验证

六种策略按每个真实蓝色实例产生共 12 份计划，保存在 `reports/phase1g_validation.json`。可见像素裁剪满足最小规划条件可为 planned，但仍 execution_status=not_implemented_in_phase1g、output_verified=false。合成/背景、编辑、几何渲染及概念生成因缺完整 mask、同商品多参考证据、Provider 或渲染能力而 blocked，附原因。

来源只使用当前实例的来源图；多参考编辑额外要求具名确认 same_product_source_ids。mask 和 geometry_model 需显式绑定当前 instance_id，不能借同张图的来源 ID 串用另一商品资产。计划真实性等级是意图/证据基础，不是已输出商品图的通过结论。

没有生成商品展示图，没有调用 QwenImage/GPT Image 或创建虚假的 Provider 执行成功记录。后续 Provider、通用/插件质量检查、分割接口的设计边界已记录，但未机械创建空成功实现。

## 运行与已知限制

默认通用描述：

```powershell
python scripts/analyze_studio.py data/input/mmexport1791948355130.jpg
```

默认不自动选择图片中的商品，输出 unassigned 规格。ROI 可重复以提供多个明确实例，--sku 与 ROI 一一对应，--selected-instance 选择已提供的 ROI。输出目录非空会拒绝复用；复查时不指定 --output-dir 即自动新建任务目录。

通用 core 使用标准库；图片 CLI 需要已有 Pillow，圆盘插件需已有 OpenCV/NumPy。尚无模型分类、通用 mask、颜色/材质估计、文字/Logo 检测或自动插件选择；源图片 EXIF/色彩管理与跨平台兼容还需后续图像模块验证。圆盘原有可见开口与加工孔口不同、中心小孔未抠除等限制保持不变。

## 验收清单

- [x] 圆盘专项功能、原测试、旧接口及产物保留，真实几何/调试图回归一致。
- [x] 通用规格不要求圆心、半径、镂空孔或螺丝数。
- [x] 普通图可导出通用描述结构，尚未实现的理解/分割明确未知。
- [x] 不支持或未实现的专用分析可跳过，失败留下证据，不影响通用描述。
- [x] 无循环依赖；通用核心无商品规则及 CV 库依赖。
- [x] 未知项不填虚构值；五种证据状态与审核来源可验证。
- [x] 多实例、不同 SKU 独立处理；同图资产不能跨实例串用。
- [x] 原 38 项与新 26 项测试全部通过，总计 64 项。
- [x] 至少三种几何类别合成接口样例运行成功，并明确标记真实跨品类验证未完成。
- [x] 用户已明确确认阶段 1G 验收通过，并授权阶段 2A。

完成后停止，等待用户确认；本阶段没有开启下一阶段。
