# 人工确认驱动的中心贯穿孔修正

2026-10-14，仅 blue_left 与 blue_right。依据用户本次明确确认：“蓝色转盘中心金属件下方的小白圆区域，是真实贯穿孔；当前看到的白色是透过孔看到的背景，不是实心零件，不是装饰件。”

审核人如实记录为“项目用户（本次对话）”，不虚构个人姓名。reviewed_at 使用 UTC 写入记录时间，明确其不是无法获取的用户消息精确时间。结构事实已确认，像素边界仍为算法估计，最终资产未 approve。

## 真实修正结果

最终交付目录：

`data/intermediate/phase2a_fix_confirmed_openings_20261014T144510578271Z/`

| 实例 | 修复ROI x,y,w,h | 变化像素 | 实际变化bbox | 状态 |
| --- | --- | --- | --- | --- |
| blue_left | 290,655,50,52 | 1087 | 297,661,38,34 | fact confirmed / revised candidate / asset pending |
| blue_right | 913,655,50,52 | 1104 | 919,661,39,34 | fact confirmed / revised candidate / asset pending |

重新放大原图后，白色背景主要位于 y663..693；y695..701 有灰色下缘金属结构。局部提示由助手逐实例配置：内部背景种子、附近未知边界、外部金属保护，尤其保留 y>=695 的下缘。复用通用 GrabCut 修复器，未使用模型重绘、全图亮度规则或其他商品实例。只修改指定ROI，原RGB逐像素一致。

初次试运行沿用原不透明mask初始化，留下厚白圈（左509/右569像素变化），未选作验收产物。将未知区域初始化为 probable_background，同时保留明确金属前景保护后，白色大块残留消除；最终两个候选已实际看图检查。所有试运行目录保留，不覆盖。

孔内中心 Alpha=0，下缘保护位置 Alpha=255；未知边界有软Alpha。细反光/抗锯齿边界仍需看图确认，不能把结构事实确认等同于像素级mask已人工批准。

## 审计与数据状态

每个实例独立包含：

- product_rgba.png、after_mask.png、alpha_mask.png、before_mask.png、原模型raw_alpha_mask.png。
- before_dark/after_dark、before_light/after_light、changed_pixels_overlay、trimap及输入提示PNG。
- review_record.json：结构确认，原文/英文确认文本、来源SHA、source_id、instance_id、region、旧待确认区域、父mask版本、新mask版本、reviewer与时间；scope=structure_fact_only、asset_approved=false。
- revision_audit.json：parent_result、parent/new_mask_version、changed_pixels、changed_region_bbox、方法、确认依据与分级审核状态。
- repair_report.json与updated_repair_report.json：新报告，旧区域移至resolved_regions，human_verified_opening=true，但mask_boundary_human_verified=false。
- parent_repair_report.json与parent_segmentation_result.json：旧文件字节快照，与父文件SHA一致。
- product_spec.json：verified_facts.central_lower_through_hole 为 human_verified；product_mask仍estimated；全商品human_review_status=partially_reviewed。
- segmentation_result.json：fact_review_status=human_confirmed_opening；mask_revision_status=revised_candidate_generated；asset_human_review_status=pending。
- mask_review_request.json：绑定新mask版本的最终遮罩审核请求，未执行。

左父版本 `a4dcfb7afd71977a71bf7f37d648aeac9a0a75152c2da760eb5475d5646e9a6e` → 新 `50925f5bfb9d14acbf7c867de328f475f2f437b82adf6943a6e15ba08b67f495`。

右父版本 `301aed2cbd75c56f738e8b3558874b2eca628fb524899fb69fec4440deae9465` → 新 `b844b8508abbf364c5c538ec0646db799246b698b5b84237a544d76220537959`。

确认仅适用于这两个来源绑定的实例，不将所有白色小圆自动处理。旧候选/旧记录保持原样，不追溯篡改历史。最终运行前587份已有中间文件的SHA逐项核对，运行后完全不变，包括其他所有实例。

## 代码与验证

新增 segmentation/confirmation.py（结构确认附加、来源/父版本/待确认区域验证，不批准资产）、scripts/run_confirmed_blue_opening_repair.py（本次授权的蓝色局部提示和回归）、tests/test_structure_confirmation.py（9项测试）。修改 segmentation/repair.py，增加可选未知区域初始化；默认prior不变。没有改通用schema，没有调整ComfyUI或环境。

最终运行 `python -m unittest discover -s tests -q`：120项通过（原111＋新增9），2.318秒。新增覆盖结构事实确认/遮罩仍estimated、仅指定未知区域解决、审计快照、父子版本、跨实例/过期父版本拒绝、禁止覆盖确认记录、缺失审核人拒绝、局部初始化保护边缘。

报告 `reports/phase2a_fix_confirmed_openings_validation.json`；最终目录下validation.json与preexisting_file_hashes.json。汇总图 confirmed_openings_comparison.png，包含左右盘前后和小孔放大对比。报告另列保留但未选中的两次开发运行，防止混淆。

## 如何批准最终遮罩

确认新候选整张遮罩及原始结构一致后，由具名审核者执行以下命令。此次未替用户执行 approve；结构事实无需重新确认。

```powershell
$confirmedRoot = "data/intermediate/phase2a_fix_confirmed_openings_20261014T144510578271Z"
.venv-seg\Scripts\python.exe scripts/segment_product.py review --request-file "$confirmedRoot/blue_left/mask_review_request.json" --reviewer "您的姓名"
.venv-seg\Scripts\python.exe scripts/segment_product.py review --request-file "$confirmedRoot/blue_right/mask_review_request.json" --reviewer "您的姓名"
```

必须使用这次新目录的请求文件，不要批准旧版。审核仅确认指定来源、实例和当前mask/RGBA版本，不确认整件商品的隐藏几何/厚度。停止在此任务，没有进入2B。
