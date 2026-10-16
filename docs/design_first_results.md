# Design-First 本轮结果

日期：2026-10-16。状态：awaiting_design_approval。当前只完成用户要求的访谈、策划和逐页设计半程；未生成正式成品。

用户已回答平台/用途/语言（亚马逊、商品销售、中文）、受众（高端用户）、参考（暂无），并明确选择“都市秩序：不对称空间与编辑节奏”。完整提案保留三个不同方向，而非换颜色的同一构图。选择记录明确 scope=concept_only，没有 page 或 mask/final_asset 批准。

## 本轮验收入口

- [五页详细设计](../data/creative_sessions/bag_design_first/page_designs.md)
- [草图汇总](../reports/design_first/design_overview.png)
- [Creative Brief](../data/creative_sessions/bag_design_first/creative_brief.json)
- [商品实际分析](../data/creative_sessions/bag_design_first/product_analysis.json)
- [无参考的明确记录](../data/creative_sessions/bag_design_first/reference_analysis.json)
- [三个创意方向](../data/creative_sessions/bag_design_first/creative_proposals.md)
- [选定方向及原话](../data/creative_sessions/bag_design_first/selected_concept.json)
- [机器可读逐页设计](../data/creative_sessions/bag_design_first/page_designs.json)
- [当前会话与历史](../data/creative_sessions/bag_design_first/session.json)
- [验证报告](../reports/design_first_validation.json)

五页依次为整体轮廓、提手与翻盖、金色调扣件、纹理切片、整包收束。位置、尺度、标题层级、图层和留白按页设计；不调用旧固定家族编译器。草图仅由真实前景/真实裁切、色块和文字形成，页脚持续标注“布局草图/非成品/背景尚未生成”。源 RGB 与遮罩资产未更改。

## 实际验证

完整测试 290 项通过（原 271 + 新增 19）；日志在 reports/design_first/unittest.log。新增覆盖方向/逐页批准隔离、Brief 变更、单页修订保留兄弟页批准、未知不造值、哈希历史、实例/概念隔离、自由坐标、文字渠道、实时素材门禁和提示词交接。测试中的批准均为临时合成 fixture，不代表真实用户批准。

Skill quick_validate 通过。真实 bag 前景使用 load_foreground 验证源图/原 RGB/Alpha/版本，当前 mask_review_valid=false。真实 CLI status 成功读取会话；对真实 p01 未批准设计执行 handoff，明确返回 blocked，没有提交任何 Provider 任务。实际查看原图与五页草图汇总：五页尺度/阅读节奏不同；细节来源真实，需注意分辨率与最终边缘。

复现检查（源码开发环境）：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='src'
$env:TEMP=(Resolve-Path reports/phase4c/test_tmp).Path
$env:TMP=$env:TEMP
python -m unittest discover -s tests -v
python scripts/design_campaign.py --session data/creative_sessions/bag_design_first status
```

待真实用户批准指定设计后，才记录 approve-page 的真实审核人及原话，再通过 handoff 取得该页执行数据。不要仅为跑通测试批准真实页面。命令合同和状态边界详见 [架构审计](design_first_architecture.md)。

## 已知限制与下一步

本轮没有真实 Qwen 背景或新成品，没有改 DGX/安装依赖/重新抠图。当前 design handoff 只输出数据；自由图层到正式执行器的适配与两页真实生产必须在设计批准后继续。建议先验证 p01 与 p03，但此建议不构成用户授权。

包袋仍为 source_preserving_preview；高端是受众定位，未宣称真皮/容量/品牌。扣件和纹理裁切可用源像素有限，正式放大需审查，必要时降低局部尺寸或补真实照片。发布前仍须确认站点与类目；附图方案不是平台批准。

历史 0.3.0 Wheel/ZIP 未更新，没有把源码测试当作独立部署验收。旧 4C 最终验证缺少报告，已纠正 README/PROJECT_STATUS 当前表述，保留历史资产与包。
