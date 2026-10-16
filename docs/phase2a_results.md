# 阶段 2A：通用商品实例分割与抠图

实施完成，等待用户人工验收。并未把真实遮罩标为 human_verified。蓝色样例自动抠图存在明显孔洞错误，不能认定所有样例已通过质量验收。

## 实际方案与环境

候选仅考虑 BiRefNet Lite 与 SAM2.1 Tiny。选择前者：通用前景分割、已有 ONNX CPU 运行环境、无需安装 Torch/CUDA 或额外提示模型。SAM2 未下载或安装。模型来源为 [rembg 官方导出的 Lite 权重](https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx)，模型许可证见 [BiRefNet Lite 官方模型卡](https://huggingface.co/ZhengPeng7/BiRefNet_lite)（MIT）。预处理依据 rembg 官方实现，不使用颜色阈值抠图。

- Windows Python 3.13.11；模型 BiRefNet-general-lite，checkpoint bb_swin_v1_tiny-epoch_232。
- 下载一个 224,005,088 字节 ONNX 文件，SHA256 `5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333`，运行前校验；后续推理离线。
- 复用已有 onnxruntime 1.30.0、NumPy 2.4.4、Pillow 12.2.0、opencv-python 4.13.0.92，没有升级全局业务依赖。
- `.venv-seg` 是独立启动前缀，通过 system-site-packages 只读复用现有依赖，不是完全独立的依赖副本。迁移时可按 `configs/requirements-segmentation.txt` 安装到全新环境。
- CPUExecutionProvider，4 线程；未启用或验证 RTX 4060/3090 GPU 推理。DGX Conda 未修改。
- DGX ComfyUI 只读 API 可访问，发现 RemoveBackground、RecraftRemoveBackgroundNode、TripoSegmentNode、TripoSmartSegmentNode 名称，但其权重/服务未验证。本阶段未使用这些节点、未提交生图任务。
- 11 个目标首次批量推理约每次 4.38–5.17 秒。关闭 CPU arena 和 memory pattern 后，蓝色复测 6.52 秒，进程峰值 6,347,939,840 字节（约 5.91 GiB），结束 RSS 386,351,104 字节；Alpha 与原运行逐像素一致。初始 arena 批量进程峰值约 11.88 GiB。建议单进程顺序运行，测量不是所有机器的内存保证。

## 运行与输出

在项目根目录执行，模型已下载时无需安装或联网：

```powershell
.venv-seg\Scripts\python.exe scripts/segment_product.py segment data/input/mmexport1791948355130.jpg --roi 0 250 626 700 --instance-id blue_left --risk reflective --risk internal_openings
.venv-seg\Scripts\python.exe scripts/segment_product.py segment data/input/手提包.jpg --single-instance --instance-id bag
```

默认创建新目录，或用 `--output-dir` 指定空目录。不会覆盖历史实例资产。`--single-instance` 是用户明确声明，不是自动检测证明；多商品使用 ROI。ROI 包含另一商品的分离片段时可以重复 `--keep-point X Y` 选定目标连通区域。该功能不能解决真正连成一片的前景，也不能重建被遮挡商品；这种情况需要外部 mask。

输出 `product_rgba.png`、`alpha_mask.png`、`raw_alpha_mask.png`、`mask_overlay.png`、`checkerboard_preview.png`、`dark_background_preview.png`、`light_background_preview.png`、`segmentation_result.json`、`product_spec.json`、`source_original.*` 和 `mask_review_request.json`。

输出使用**完整原图尺寸与原图存储像素坐标**，ROI 外 Alpha 为 0；模型 1024×1024 缩放与恢复关系记录于 JSON。EXIF 方向不自动旋转并记录警告。RGBA 的 RGB 与原图解码 RGB 完全一致，未重绘、未做边缘去色；RGB/RGBA 输入的 ICC 配置随导出保留。非 RGB 色彩配置需要额外审核。已透明输入不会恢复隐藏像素。灰度 Alpha 是分割估计，不是玻璃物理透射率。

## 修正与审核闭环

导入完整原图尺寸的灰度 mask，或明确 `--coordinates roi` 导入 ROI 尺寸：

```powershell
.venv-seg\Scripts\python.exe scripts/segment_product.py correct data/intermediate/phase2a/blue_left/segmentation_result.json --mask data/intermediate/phase2a/blue_left_correction_input.png --coordinates source
```

导入结果是新版本，保存修正输入、原始模型 mask 与父版本来源，撤销旧 mask 审核。不会继承人为确认。

审核者应先检查深浅背景、叠加图与原图，再对实际选定目录使用下面命令（把姓名替换为本人；本项目未替用户执行）：

```powershell
.venv-seg\Scripts\python.exe scripts/segment_product.py review --request-file data/intermediate/phase2a/red_left/mask_review_request.json --reviewer "审核人姓名"
```

请求文件绑定 source_id、instance_id、ROI、来源 SHA、mask 版本；还核验当前 mask、RGBA、原图像素及 ICC，重新检查空遮罩。更换来源/实例/版本、篡改资产或错误借用审核会失败。审核只确认该遮罩，整件商品 remains partially_reviewed，不确认几何、隐藏部位或材质。记录具名审核历史。任务规划器验证当前资产绑定，不凭声明的 human_verified 放行。

## 测试结果与真实质量

最终 `python -m unittest discover -s tests -q`：**94 项通过（原 64 + 新增 30）**，实测 1.216 秒。覆盖 ROI、多实例、多形状、内部孔/内壁、软边缘、浅色与深色、空 mask、修正导入、坐标尺寸、异常路径、旧 JSON、RGBA/来源篡改、具名审核与过期版本、已有透明度、ICC。合成真值测试验证接口与像素映射，不能代表模型准确率。

实际运行模型的低对比合成测试：浅色同浅底 IoU 0.669，深色同深底 0.811（阈值128）；两者已知孔洞仍被模型填成不透明。这是失败风险记录，不是成功验收样例。

真实素材共 **8 张照片、11 个目标实例**，另有一次手提包 CLI 复跑及一个蓝色外部修正候选，最终 13 个资产目录。不是 13 种商品。

| 样例 | 实际观察与待处理问题 |
| --- | --- |
| 蓝色左、右盘 | 自动结果孔洞白背景残留；右盘下方大孔明显未透明。需要修正，不能通过。左盘修正候选清除了三个大开口残留，但中心小辅助孔仍不透明、局部边缘白晕待确认 |
| 两种银盘 | 主要孔洞与可见内壁视觉保留；高光及细边缘需审核，不代表金属背面已验证 |
| 黑色两实例 | 用各自 ROI 与显式点选移除邻盘分离片段；不规则镂空可见，细小断裂/孔边需放大审核 |
| 红色两实例 | 大开口与小辅助开口视觉透明、内壁保留；金属高光与薄边缘待审核 |
| 手提包 | 不规则主体、五金与提手间背景分离，软边缘待检查 |
| 头戴式耳机 | 头梁间开口透明，主体深色纹理保留，细边缘待检查 |
| 腕表 | 主体/表链/金属反光保留，细小链节缝隙及高光需审核 |

13 个最终资产完整性核验通过：原始 RGB、RGBA Alpha、一致尺寸、ROI 外零 Alpha、ICC、RGBA 哈希与 pending 状态。此核验不证明语义边界正确。真实图没有独立人工真值 mask，因此不报告虚构真实 IoU；所有人工审核仍 pending。

蓝色修正 mask 是助手根据阶段 1A 可见开口轮廓准备的**候选**，不是用户真值，也未进入通用算法。只修改已观测三个开口范围内 5,569 个像素，范围外模型 Alpha 不变。详见 `reports/phase2a_correction_provenance.json`。

## 文件与验收产物

新增 `segmentation/{base,provider,mask_processing,quality,pipeline,cli}.py`、`core/asset_binding.py`、`scripts/{setup_segmentation,segment_product,validate_phase2a_assets}.py`、两份 segmentation 测试、依赖清单；修改 task_planner、pyproject、gitignore、README、architecture。阶段 1A 算法与旧测试保留。

汇总 `reports/phase2a_validation.json`；实际推理日志 `phase2a_model_runs.json`；内存复测 `phase2a_memory_probe.json`；最终资产核验 `phase2a_asset_integrity.json`；来源 `phase2a_source_manifest.json`。检查图 `phase2a_automatic_dark_sheet.png`、`phase2a_light_sheet.png`；每个实例另有完整分辨率预览。

- [x] 真实通用模型、透明 PNG、灰度软 Alpha、独立实例、深浅预览、外部修正及绑定审核已实现。
- [x] 原测试保留，增加三类真实非转盘素材，未知信息不自动确认。
- [ ] 用户审核至少一个真实镂空样例及内壁；目前只有助手视觉检查，尚无人工已验证样例。
- [ ] 蓝色孔洞问题全部修复并经用户验收。
- [ ] 用户确认阶段 2A。

尚未验证透明玻璃、密集复杂背景、被遮挡实例恢复、GPU/3090 部署与所有类别自动多实例检测。自动 QC 的残留/光晕/碎裂指标是风险代理，不能自动判断语义正确。不开展下一阶段，等待验收。
