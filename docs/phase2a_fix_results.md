# 阶段 2A-Fix：局部遮罩修复

2026-10-14 实施与真实回归完成，等待用户质量验收。没有进入 2B，没有安装新依赖/模型，没有执行具名人工审核。初始分割器仍是已有 BiRefNet Lite ONNX。

## 失败分析与最小方案

读取阶段 2A 记录、验收 JSON、原始照片、左右盘自动 mask 和之前左盘修正候选。先前左盘候选已清除大块残留，但中心白色圆形仍不能确定；此次从原始自动结果重新产生独立候选，保留之前成果。

蓝色真正可见的背景开口位于深色内壁内侧。可见白色中心结构、螺丝反光不能按颜色删除。插件给出的轮廓是可见背景投影，不能等同于整个加工开孔。外沿暗色内壁应保留；中心小圆区域缺乏实物依据，状态为 `requires_physical_confirmation`。

错误与疑似边缘区域的全图坐标、面积见 `reports/phase2a_fix_failure_regions.json`。面积是轮廓内原 Alpha>32 的像素数，包含边缘疑似像素，不全部认定为确定背景残留：

| 实例 | 可见开口 ROI（x,y,w,h） | 原不透明/半透明疑似像素 |
| --- | --- | --- |
| 左盘右上开口 | 364,436,194,186 | 3078 |
| 左盘左上开口 | 76,440,188,181 | 215 |
| 左盘下方开口 | 246,702,139,156 | 191 |
| 右盘右上开口 | 986,436,194,190 | 8977 |
| 右盘左上开口 | 696,440,190,181 | 225 |
| 右盘下方开口 | 870,702,139,156 | 17607 |

右盘各区域数据保存在相同 JSON，禁止用左盘 mask 平移替代。右盘轮廓由同一来源图的另一个插件实例独立检测。

通用修复器使用 OpenCV GrabCut 的明确前景/背景种子与未知区域机制，参见 [OpenCV 官方说明](https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html)。不使用全图白色、黑色或低亮度删除规则。

1. 明确指定所绑定实例内的修复 ROI、可编辑区域、背景种子、保护前景和未知边界。
2. 背景点/区域和前景保护不得冲突；越过实例 ROI 的提示拒绝。
3. GrabCut 在局部图像上分类，未知边界做轻微软化；硬背景种子为0，保护前景严格保持原 Alpha，ROI 外与不可编辑区域完全不变。
4. 可改用外部 mask 或现有 SegmentationProvider 局部重分割，受相同范围和保护约束。第二 Provider 仅进行了接口合成测试，没有安装或声称运行第二个真实模型。
5. 导出新资产、保留原始模型 mask 与父版本、重新检查质量，记录变化连通区域/像素数/证据/trimap。所有结果 pending。

蓝色验证脚本单独使用 planar_geometry 可见开口轮廓：内缩3像素作为明确背景种子，轮廓附近保留未知边界带，外部区域保护。**没有直接把整个轮廓填透明**；边界由 GrabCut 判断。标注由助手从图像证据准备，属于 estimated，不是用户审核或独立真值。专项逻辑只存在回归脚本，通用修复器没有颜色或商品几何规则。

## 实际效果与限制

- 左盘修改 **9,104** 像素，右盘修改 **31,000** 像素；修改包含软边界调整，不仅是不透明残留。
- 深色背景完整图及局部放大图中，两个盘大孔原有白色块已消除。
- 各自开口内部种子核心原 Alpha>32 数从 2,283 / 23,274 降到0。硬种子透明是约束的结果，不是独立准确率或真实孔洞 IoU。
- 保护区域 Alpha 全部不变。左右可见深色内壁各取三个观测点，修复前后均255；中心金属强反光也均255。采样与视觉检查不等于整件商品真实几何已验证。
- 中心小圆区域左 `[292,657,46,48]`、右 `[915,657,46,48]` 完全未修改，标记 `requires_physical_confirmation`。
- 放大后仍有很细的白/青色边缘线，可能包括原始反光、抗锯齿或背景污染；此次未改 RGB，未做颜色去污染，需要用户审核。不能声称所有孔边像素完美。
- 银色、黑色、红色、手提包、耳机、腕表六个真实样例也实际运行了修复器。采用保守背景内部提示，所有商品/软边缘保护，修改0像素；提手、头梁间隙、表链、高光没有新增损坏。这是提示范围下的非退化检查，**不代表已修好它们原有未知细节，也不证明错误提示时一定安全**。

第一种方案已经解决大块残留，故没有必要下载 SAM2 或其他大型模型。若未来更复杂商品的未知区域无法可靠分类，应提供更精确提示/外部 mask，再评估第二模型。

## 文件、使用与审核

新增：

- `src/product_studio/segmentation/repair.py`：通用局部修复与资产导出。
- `scripts/repair_product.py`：命令行提示/外部遮罩入口。
- `scripts/run_phase2a_fix_validation.py`：真实专项与跨品类回归标注、汇总。
- `tests/test_mask_repair.py`：17项新增测试。

完整实例目录：`data/intermediate/phase2a_fix/{blue_left,blue_right,silver_round,black_lower_left,red_left,bag,headphones,watch}/`。每例包含要求的九份输出：original_preview、before_mask、after_mask、before_dark、after_dark、before_light、after_light、changed_pixels_overlay、repair_report；同时有 trimap、输入提示、透明前景、来源快照、规格和版本绑定审核请求。

以下命令可用已保存的提示重跑到新空目录：

```powershell
.venv-seg\Scripts\python.exe scripts/repair_product.py data/intermediate/phase2a/blue_right/segmentation_result.json --roi 626 250 628 700 --editable data/intermediate/phase2a_fix/blue_right/editable_input.png --foreground data/intermediate/phase2a_fix/blue_right/foreground_input.png --background data/intermediate/phase2a_fix/blue_right/background_input.png --output-dir data/intermediate/phase2a_fix_manual_rerun
```

提示灰度图必须是原图完整尺寸。`--background-point X Y`、`--foreground-point X Y` 可重复；`--external` 导入完整尺寸灰度 mask，但仅采纳可编辑且非保护区域。已有人工修正入口也继续可用。ROI 格式为全图像素 x,y,w,h。

修复继承原图 hash、source_id、instance_id 和原始实例 ROI，父结果路径与旧绑定记录于报告。源文件改变、跨实例 ROI、冲突提示拒绝。蓝色 mask 内容改变，版本随之改变；六个零变化资产的内容版本与旧版相同，另有新的修复记录，不制造虚假的不同 mask 内容。旧审核不继承。审核仍使用阶段 2A 的 `segment_product.py review --request-file ... --reviewer ...`，必须用户看图确认后主动执行，助手没有执行。

全部产物保持原图 RGB，RGB 色彩 ICC 配置随预览保留；原图和原始自动 mask 不覆盖。修复不是补造被遮挡像素或物理玻璃透明度估计。

## 测试和验收

`python -m unittest discover -s tests -q` 实测 **111项通过，原94项保留＋17项新增**，最终运行1.371秒。新增覆盖 ROI外不变、前景保护、点冲突、浅色商品、高光/暗内壁、未知待审核、外部导入、第二Provider映射、原Alpha保留、尺寸错误、来源变更、同图跨实例拒绝、版本与历史保留。首次新增集成测试的临时目录在受限系统目录中写入失败；改为项目内临时目录后通过，没有修改系统权限。

机器可读报告 `reports/phase2a_fix_validation.json`，失败区域 `phase2a_fix_failure_regions.json`，汇总对比 `phase2a_fix_comparison.png`（左前右后），蓝色原图/前/后/变化放大图 `phase2a_fix_blue_detail.png`。

- [x] 实际左右盘大块白色背景残留改善，可见深色内壁保留。
- [x] 中心小圆待实物确认且未修改。
- [x] 六个其他真实样例保护回归，无新增像素变化。
- [x] 完整变化记录、父资产、源绑定、原mask与新候选；111项测试通过。
- [ ] 用户审核孔边、内壁及细白/青线，确认候选可接受。
- [ ] 用户提供中心白色小圆的实物结构确认。
- [ ] 阶段 2A-Fix 人工验收通过。

尚无自动错误区域语义检测，也没有真实全像素人工真值；本次是辅助证据/明确提示驱动的修复，不承诺全自动任意商品。停止在阶段 2A-Fix，等待验收。
