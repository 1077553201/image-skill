# 设计先行：最小交接层审计

更新：2026-10-16。本轮完成需求访谈至逐页草图，等待设计审核；没有实际生成新背景或成品。

旧流程问题：creative/executor.py 的 build_plan 先选择意图，再调用 director.compile_layout 分配构图家族坐标；背景按 studio/environment 角色共享风格提示。即使意图多样，也容易先生成背景、再将商品与标题装入布局。旧 generate 入口没有会话设计批准门禁。

保留组件：事实唯一入口 creative/facts.py、来源/实例/版本及审核模型、既有抠图与 RGBA、Provider/API 工作流、生成缓存、精确 Alpha 合成、消费者文字隔离、实际参考抓取和分析。专用几何插件不参与本轮。既有 director/layouts 保留为历史执行适配工具，不再决定新 PageDesign 的坐标。

新增最小组件：

- creative/design_workflow.py：完整 JSON 快照、父哈希、方向与逐页批准、自由 PageDesign 验证、批准后执行交接数据。没有 Provider 调用。
- creative/design_cli.py：显式文件输入的 design 子命令。scripts/design_campaign.py 仅供源码开发；安装模式使用 product-studio design，不搜索源码。
- creative/design_sketches.py：低成本草图，用真实前景/真实裁切检查比例、文字与层级。平面背景是占位，固定审核标签属于草图页脚，不进入 consumer_copy。
- Skill 主入口改为访谈与设计，旧请求合同标记为底层历史执行接口。

PageDesign 是 Agent 按页写入的数据，包含本页目的、受众、消费者文案、自由构图、位置/尺度、原视角、视觉焦点、背景/光线、配色/字体、装饰与图层、素材/路线、尺寸、真实性等级及质检标准。没有必填构图家族，不假设商品类型。消费者文字只取 consumer_copy；模型提示只取批准后的空间/光线等设计信息，不把内部记录当文案。

审核绑定：方向批准覆盖当前 brief/研究/概念及 source-instance-mask 哈希上下文；逐页批准另外绑定该页哈希与选定方向。改一页仅清除该页批准，修改 brief/研究/概念会清除下游批准及旧页设计。新资产版本使用新会话重新规划。每次修改独占创建 revisions/NNNN.json，保留旧快照及事件；读取时验证当前和父链。单写者本地机制，不宣称数字签名或身份认证。

状态与进入条件：

| 状态 | 条件与当前实现 |
|---|---|
| intake | 选定来源/实例/mask 绑定并创建会话 |
| awaiting_answers | Brief 有真正阻塞的问题；由 Agent 对话收集，不能伪造答案 |
| brief_ready | Brief 证据渠道完整、无阻塞问题 |
| concepts_ready | 用户选定当前方向；无页设计时可展开设计 |
| awaiting_concept_approval | 2–3 个概念及 Brief/研究已保存，尚未有效选定 |
| page_design_ready | 全部现有页面都有当前设计批准；单页可按本页批准独立交接 |
| awaiting_design_approval | 已有完整页设计，仍有未批准页；当前真实会话停在这里 |
| generating | 后续执行器须先取得本页有效设计批准与实时素材门禁；本轮未实现任务提交，不会写入此状态 |
| reviewing | 后续须已有真实输出及来源任务记录；本轮没有新成品 |
| revision_requested | 后续用户要求重做指定成品页，保存原因与父版；当前设计修订通过 put/page_designs 保存新快照 |
| delivered | 后续要求完成输出与逐页审核，不以测试通过冒充交付批准 |

生成路线交接仅支持 background_only；从精确批准设计导出商品占位、镜头、光线、留白、焦点、场景、配色、文字保留区及禁止冲突。handoff 实时复用 load_foreground 验证来源 RGB/Alpha/hash 与严格审核门禁，再检查完整实例绑定，返回 provider_submitted:false。尚未把自由图层接入正式生成执行器，必须在用户批准实际设计后完成并以两页验证，不能声称本轮已经出图。

旧 generate 作为兼容底层仍可被直接调用，不能声称 API 安全强制门禁覆盖所有旧入口。当前 Skill 默认入口使用 design，明确禁止借用旧入口绕过未批准设计。旧 0.3.0 Wheel/ZIP 是历史快照，没有新增 design 命令；本轮不重新打包或宣称已完成独立安装验证。
