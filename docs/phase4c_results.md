# 阶段 4C 交付与验收

本阶段完成 Engine / Skill 独立化、事实继承、文案隔离、创意多样性与一次真实参考图编辑。最终图片、创意与平台资格仍待用户审核。详细机器记录：reports/phase4c_validation.json。

## 安装与使用

发行目录 dist/phase4c/release/ 包含 product_photo_system-0.3.0-py3-none-any.whl、universal-product-creative.zip 和哈希清单。必须解压完整 Skill，不是仅复制 SKILL.md。

```text
python <解压Skill>/scripts/install_engine.py --venv <新虚拟环境>
<环境Python> <解压Skill>/scripts/preflight.py --output preflight.json
<环境>/product-studio generate --request <绝对请求JSON> --output <新输出目录>
```

Windows 环境命令在 Scripts，Linux 在 bin。安装脚本用宿主 pip --python 只安装到新 venv，可用于缺少 ensurepip 的已安装 pip 环境。依赖是 NumPy 2.4.4、Pillow 12.2.0、OpenCV headless 4.13.0.92。没有修改基础 Python 或 DGX Conda；没有新模型安装。离线安装需事先准备兼容依赖 Wheels，模型、字体、服务不包含在发行包。

ComfyUI 地址通过 COMFYUI_BASE_URL 或显式配置目录提供；新服务器须具有相应实际节点与模型，不能假定所有服务器兼容同一模板。资产可以 export-asset 导出；导入保留原源图、mask/RGBA、审核原字节与版本，仅重定位路径并记录旧 JSON 哈希。旧绝对路径可作为审计上下文留在记录，生产输入不读取它们。

## P0：真实隔离与第二 Agent

不是只换工作目录。WSL Ubuntu 24.04 的独立 mount/PID namespace 用 tmpfs 遮蔽 Windows 盘，再降权 UID1000、丢弃所有 capabilities、清 PYTHONPATH。原工程及 /proc/1/root 别名实际不可读，退出后宿主工程仍正常。日志在 reports/phase4c/isolation_probe/、p0_acceptance.json 和最终安装验证记录。

初始 0.2.0 Wheel 已从新 venv/site-packages 在 /tmp 调用 product-studio 生成新白底，并实际调用 QwenImage 商业背景。另一个独立 Agent 仅读取外部安装副本与当前耳机，完成六图任务。它没有修改核心或读取旧工程，文案没有混入蓝盘或工程介绍。

该测试揭示两类问题并保留失败：输入合同缺少安全 ID/平台枚举提示，已补全文档；首版 Qwen 空背景画出额外耳机，污染两图。数值质检未发现，Agent 逐图查看后拒绝。新修订只额外生成一张背景，共 2+1 次任务，第二版六张通过 Agent 视觉复核、保持 pending。第二 Agent 使用初始 0.2.0 发布快照，最终 0.3.0 另行重装与真实运行，具体版本/哈希不可混称。

## P1：事实与内容纠偏

实际根因：旧 organize_facts 仅组合 Agent 观察和请求 product_facts，没有读取 ProductSpec.verified_facts，handoff 也未携带确认值。当前生产 prepare/build 统一调用 resolve_product_facts：检查来源哈希、实例、当前 mask 版本、确认记录哈希与审核人；引用规范商品 ID 和证据位置。蓝盘中心下孔自动继承为 human_verified，不再要求重确认；耳机不继承。冲突拒绝，unknown 不降级确认值。结构确认、遮罩门禁与最终图片批准独立。

渲染节点来自 consumer_copy；internal_notes/provenance 留在报告。旧 copy 是受检查的兼容输入，不从项目说明回填文案。默认拒绝内部工程术语，需要单独具备真实用户授权的 production_disclosure 才能显示制作说明。关键词检查不是完整语义判断。中文真实图包含大段未渲染工程上下文，其实际成品只介绍耳机。

## 创意与参考

旧二十图审计见 docs/creative_diversity_audit.md 和 creative_diversity_before.json：固定分栏、双细节窗和白色环境面板重复明显。新 Director 区分买家/用途/目标/参考/情绪/构图/场景/密度/顺序；八种家族具有不同主体中心、比例和文字分区。每张计划保存选择理由和布局签名；相似性仅是风险提示，不作为审美通过。

本次三套最新候选：bag_final（封面/主导细节/错位编辑）、headphones_final（大字海报/耳罩特写/反向横幅）、blue_left_final（留白/开口结构/参数网格），各三张。中文补充图 headphones_zh。三个新 Qwen 背景实际生成；最终元数据修订及中文图显式复用对应原任务，零新提交。源 RGB/Alpha 不重绘、不制造新视角和接触阴影。所有新营销图仍 pending。

参考变更测试采用用户已有腕表真实照片建立新的本地目录，由 Agent 实际查看、按十四维记录可迁移的明亮留白/主体尺度；没有把腕表颜色、结构、参数和接触关系转给耳机。生成了新的计划，没有声称该单图是竞品营销套图，也没有凭空推断它的字体或整套广告叙事。计划位于 reference_change_plan_final，仅规划、未花生图预算。

## 图像编辑实验

独立 Provider image_guided_creative_edit 只允许 concept_creative，strict_product 在上传前拒绝。基于实际节点、官方接线和现有 Qwen 2.1 模型副本，真实上传一张手提包图并执行一次。任务 2ba74bd5-7952-4367-9a45-8d685f86c561，51.72 秒，1024×1024；上传回读哈希和远程 graph 与提交一致。没有修改原背景工作流。

结果保留大体棕色单提手、前盖与金色扣，但商品已重绘、缩小，五金与纹理无法逐一认证。报告 identity_quality_passed=false；这只是概念能力通过，不能作严格商品图。对比 data/outputs/phase4c/concept_edit_bag/comparison.png，详细报告 image_edit_experiment.json/.md。多参考、mask 控制、硬身份约束、穿戴/手持未验证，未推进完整 4D。

## 测试与已知限制

原 224 项保留并回归。新增测试覆盖携带审核/防篡改/路径隔离、事实继承/冲突/来源、内容通道、构图不变形与裁切、重复风险、编辑 Provider 成败/超时/上传回读/strict 拒绝。完整测试数量、真实任务与旧资产哈希检查以 phase4c_validation.json 为准；Mock 与实际远程试验分开。

原始边缘 RGB 未做无记录去污染，局部浅线与反光仍需看原尺寸。自动检测不能保证背景无额外物体，独立 Agent 测试已有明确反例。数字布局差异不保证优秀审美。白底/广告图的具体平台类目资格、隐藏结构、新视角、3090 实机性能没有被假定通过。

阶段 4C 完成后停止，等待用户验收。
