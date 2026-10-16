# 阶段 4A：参考商品链接驱动的商业套图

2026-10-15。已完成本轮开发与真实生成，**等待用户视觉验收**。当前推荐查看第二版 `data/outputs/phase4a/blue_left_v2/`；首版 `blue_left/` 完整保留。未进入后续阶段。

## 本轮输入与授权调整

- 自有商品：blue_left，沿用原始 RGB、最新中心孔遮罩和 mh 的有效具名遮罩审核。
- 参考：<https://www.amazon.com/dp/B0HGGJZ92H>。
- 用户明确调整：视觉理解由最终接入的 Agent 工具完成，不再另配 VLM。因此本轮由当前具备图像能力的 Agent 使用 `view_image` 读取参考总览和全部八张原图，写入逐图十四维分析。`provider=image_capable_agent`、`separate_vlm_api_called=false`，不声称调用了独立视觉 API，也未将 QwenImage 文本编码器当作分析器。
- 用户新提供：直径 **30 cm**，重量 **500 g**，材质 **复合材料**。记为本次对话用户明确确认，绑定 blue_left 来源/实例/遮罩版本；未做独立测量或材料鉴定。未把蓝色主体继续宣称为金属。
- 品牌、厚度、背面、适配型号、认证、包装清单及性能利益保持未知。未将竞品事实写入自有商品卖点。

## 真实参考获取与分析

正常 HTTPS 访问取得原始 HTML（1,511,596 字节），未遇验证码、登录或访问挑战。来源快照为 `reports/phase4a/amazon_page.html`；正式素材目录为 `data/references/amazon_B0HGGJZ92H/`。

从实际 `ImageBlockATF.colorImages.initial` 提取八张画廊图：一张主图为 1183×474，七张附图为 1500×1500。未扫描整页所有图片作为画廊，未混入广告和推荐商品。每张保留 URL、DOM/JSON 来源、角色、真实尺寸、字节数与 SHA-256。

本次 HTML 的 A+ / 品牌容器为空，`catalog.json.missing_assets` 明确记录缺失；未宣称获取了完整 A+。

交付文件：

- `data/references/amazon_B0HGGJZ92H/catalog.json`
- `data/references/amazon_B0HGGJZ92H/reference_contact_sheet.png`
- `data/references/amazon_B0HGGJZ92H/reference_style.json`
- `data/references/amazon_B0HGGJZ92H/reference_analysis.md`

实际视觉观察得到的可迁移方法是：浅灰留白、短标题层级、事实分组、真实局部特写、简洁标注和不同销售任务之间的节奏。新作品采用自己的蓝色强调、深海军蓝变化和原创版式，不使用参考图片作为图层或 img2img 输入，不复制品牌标识、芯片徽标、屏幕插画、原文案或原始布局。

采集器支持 Amazon ASIN、eBay item ID、本地目录、截图与 ZIP。当前 Amazon 已真实运行；**eBay 仅做解析与安全单元测试，未做真实站点成功验证**。下载仅允许指定公共 HTTPS 域名；逐跳验证重定向，拒绝内网 DNS，连接固定到已检查的 IP 并保留 TLS 主机验证；文件名由索引/哈希生成，空输出目录门禁防止覆盖。ZIP 不解压路径，只读取受限图片字节，拒绝路径穿越和超限大小。访问挑战会报错并要求用户素材，不绕过访问控制。

## 自有商品事实与设计规划

事实清单：`reports/phase4a/product_facts.json`、`product_facts.md`。新事实没有改写已经审核的旧 product_spec、旧遮罩或审核记录。

首版配置为 `configs/creative_presets/blue_left_4a.json`，第二版为 `blue_left_4a_v2.json`。最新完整八张 brief 在 `data/outputs/phase4a/blue_left_v2/creative_plan.json`，并存档为 `reports/phase4a/creative_plan_v2.json`。每张包含角色、受众、内容、真实素材、构图、配色、图层、文案、事实引用、AI 使用、尺寸、真实性限制和检查条件。

| 成品目录 | 用途与设计 | 输出尺寸 |
| --- | --- | --- |
| 01_white_hero | 单件纯白底主图候选，无文字、无阴影 | 1024×1024 |
| 02_signature | 深色商业主视觉，短标题与真实商品 | 1024×1024 |
| 03_material | 复合材料、蓝色外观和 500 g 重量信息图 | 1024×1024 |
| 04_detail | 总览和两个原图局部细节窗口 | 1024×1024 |
| 05_structure | 三个大开口与已确认中心下方贯穿孔的结构说明 | 1024×1024 |
| 06_campaign | 浅色抽象宣传图；不声称真实安装或接触场景 | 1024×1024 |
| 07_specifications | 30 cm 直径标线、500 g、复合材料规格图 | 1024×1024 |
| 08_wide_banner | 宽幅原创宣传图，无虚构品牌名 | 1536×864 |

共八张，包含四张带实质信息或细节说明的图片，超过至少六张、至少两张信息图的数量要求。`creative_set_contact_sheet.png` 是套图总览；每张成品为独立目录下的 `final.png`。

Arial 字体使用已存在的本机文件；未安装字体，也未分发字体文件。文字、分隔线和尺寸线由 Pillow 确定性渲染。图中尺寸、重量有自己的 fact_id 和对应数值/单位校验。所有图片仍使用同一真实正面视角。

## 真实 QwenImage 执行

复用现有 ComfyUI Provider、API 原始工作流及节点映射，未重写 Provider 或修改 DGX 环境。工作流模板 SHA-256 为 `580a958bfb5f679d0b2cb79fda32b965a28f31a667e992e43fb5a258720c699b`。

| 背景 | prompt_id | seed | 实际等待/执行总时长 |
| --- | --- | --- | --- |
| signature | 1675b91e-ba08-44e2-94bb-9d6af336f281 | 4101501 | 80.85 s |
| campaign | a298b9f2-978e-4f73-b1db-676d6f5dafed | 4101502 | 80.85 s |
| wide | 993c2ade-f358-4f44-9604-7f10736b72ba | 4101503 | 95.05 s |

三个任务都取得真实远程 success history，已比较 history 中的工作流、提交图哈希和下载图哈希。原始生成背景、submission、workflow、history、execution 全部在首版 `blue_left/background_tasks/` 的各缓存目录中；验证报告记录完整路径。白底和浅灰信息底由 Python 生成，未冒充 AI 结果。

Agent 查看首版后发现：结构引线关联不清，两个背景底部的横向光带容易引起地平线联想。因此保留首版，生成第二版，简化结构图文字分组，并在**独立背景层**进行显式裁剪及等比例适配：campaign `[0,0,752,752]`，wide `[200,0,1136,639]`。原始背景未覆盖，派生变换写入清单；没有对商品做透视、旋转、拉伸或补绘。

第二版只复用同三个真实任务。禁止网络的缓存恢复检查实际通过，记录于 `reports/phase4a/cache_reuse_check.json`，新增任务为零，最终成品哈希不变。

## 工程验证与视觉检查

- **195 项自动化测试全部通过：原有 161 项 + 新增 34 项，0 失败、0 错误、0 跳过。** 日志和逐次测试 JSON 在 `reports/phase4a/tests_*.txt` / `.json`，最新摘要为 `automated_tests.json`。
- 新测试涵盖 URL/ASIN/eBay ID、内网 DNS、恶意重定向、画廊排除广告、A+ 作用域、验证码失败、本地截图、ZIP 路径、不可覆盖、分析图像哈希、事实绑定、未知值、推测卖点拒绝、数量/单位、文案词表、多行文字、安全边距、对比度、文字保护、真实局部细节与分辨率、主图/营销图分离等。
- 实跑修复过 Pillow 多行锚点不兼容问题。Codex 重定向的系统临时目录一度拒绝写入，测试入口改用项目内独立临时目录，不修改现有 Python/Conda 环境。
- 八张图均验证文件完整、尺寸、来源绑定、当前遮罩审核、原始 RGBA/Alpha 哈希、未裁主体、精确重算合成结果、文字不遮挡真实商品。
- 八张 × 四个实际孔内点，合计 **32 个背景透出探针全部通过**。这证明这些位置透明，并非对全部边缘质量的自动认证。
- 主图最长轴占比约 **86.9%**，纯白背景、无文字。仍需目标类目审核。
- 文字处于 56 px 安全区；最小实测字形对比度约 **4.31**。大字/粗字门槛 3.0，小字门槛 4.5，均通过。受控词表不是通用英文拼写词典；Agent 已逐张检查本轮文案。
- 套图 28 对缩略图平均 RGB 差异最低约 28.24/255，未出现像素近重复；这个指标不能证明营销语义不同，图片用途由 brief 和 Agent 视觉检查共同判断。
- **800 个此前商品资产、3A/3B 产物和原始工作流文件哈希保持不变**，其余实例未写入。
- Agent 已逐张查看第二版八张成品：未见竞品图像、品牌标识、裁掉主体、明显文字越界或新增部件；深色图仍能看到原图边缘细亮线。该检查不替代用户验收。

## 已知限制与审核状态

1. 原始单盘约 620×630 有效像素，白底主图放大 1.4 倍；不是重新拍摄的高分辨率实物照片。两个细节原始窗口仅 125×159 和 174×133，最多插值 1.6 倍，有分辨率限制，没有 AI 增补加工纹理。
2. 原图细亮边与反光按原 RGB 保留，深色背景中更显眼。此阶段未修改抠图或做边缘去污染；是否适合销售须用户看图。
3. 没有品牌、包装或适配事实，故未做品牌 Logo、配件清单、兼容承诺或真实安装示意；第八张是无品牌营销横幅。
4. A+ 未取得；eBay 实站获取和更多真实商品的参考驱动套图尚未实测。本阶段仅按授权处理 blue_left。
5. 四类平台配置独立于渲染。Amazon.com 主图规则查到官方搜索摘录，正文为 JavaScript/login 页面，具体类目仍未确认，不能宣称全平台合规。eBay 官方图片政策明确禁止附加营销文字/图案，因此这些文字营销卡片不能作为 eBay 商品图片直接上传。官方来源：
   - <https://sellercentral.amazon.com/help/hub/reference/external/G1881?locale=en_us>
   - <https://www.ebay.com/help/policies/listing-policies/picture-policy?id=4370>
6. 尚无自动 Logo 检测器、通用语义真实性验证器或完整拼写器。当前采用资产来源隔离、受控文案词表、数量事实校验和 Agent 视觉检查，不能把它们宣传为全自动品牌/真实性证明。
7. `mask_review_valid=true` 仅表示已审核前景可用。参考分析、创意设计和所有最终营销图仍为 **pending**；未代表用户执行任何具名最终审核。

## 文件变更

新增生产代码：

- `src/product_studio/references/{__init__,sources,analysis}.py`
- `src/product_studio/creative/{__init__,planning}.py`
- `src/product_studio/generation/marketing_renderer.py`
- `scripts/analyze_reference.py`
- `scripts/generate_creative_set.py`
- `scripts/validate_phase4a.py`
- `tests/test_references.py`、`tests/test_creative.py`
- `configs/creative_presets/blue_left_4a.json` 与 `_v2.json`
- `configs/platform_presets/{amazon,ebay,generic,social}.json`

文档：本文件、README 状态与运行入口、architecture 的 4A 边界。未修改既有核心 Evidence/schema、抠图、审核机制、ComfyUI Provider 或 Compositor；未安装新依赖或模型。实际使用 Python 3.13.11、Pillow 12.2.0、NumPy 2.4.4、OpenCV 4.13.0.92 和标准库。

## 运行与验收

在项目根目录运行。已生成的第二版可直接离线复现/复核，不需要你逐行修改参数：

```powershell
python scripts/generate_creative_set.py --config configs/creative_presets/blue_left_4a_v2.json --render-only
python scripts/validate_phase4a.py --run-tests
```

第二条需要访问 DGX，只读查询三个真实任务。加 `--offline` 可跳过实时远程核对，报告会明确显示未实时检查。完整执行命令不带 `--render-only` 时，本次配置也会命中父版本缓存，不重复提交已成功任务。

重新采集时必须指定新空目录，保留原研究：

```powershell
python scripts/analyze_reference.py --url "https://www.amazon.com/dp/B0HGGJZ92H" --output data/references/new_research
```

本地图片/截图/ZIP 可改用 `--local 路径`，截图附加 `--screenshot`。采集命令本身不做视觉判断。下一步由具备图像能力的 Agent 逐张读图、填写分析和配置，Python 验证图像哈希、事实及 brief 后执行；本轮该 Agent 步骤已实际完成，**尚未提前封装最终 Skill**。

请审核第二版总览及八张 `final.png`：信息是否准确、主图比例、深底细亮边、两处原图细节清晰度、版面留白和英文语气。用户批准前保持 `pending_user_visual_review`，不发布、不进入下一阶段。
