# 阶段 3A：ComfyUI + QwenImage 背景生成与商品保真合成

2026-10-15。使用现有远程 QwenImage 2.1 工作流生成独立背景，本地确定性合成；没有上传商品给模型，也没有开发新视角、3D、Web UI、Agent 或阶段2B。最终商品图/背景的视觉验收仍由用户执行。

## 实际审核与工作流

读取最新中心贯穿孔候选 `phase2a_fix_confirmed_openings_20261014T144510578271Z`。blue_left 与 blue_right 的具名审核人为 **mh**，当前mask版本、source_id、instance_id、源文件SHA、RGBA SHA、Alpha及review_request均核对有效。blue_left使用strict遮罩门禁；手提包的mask尚未具名批准，因此三个输出均preview。strict表示使用有效审核的前景，不表示新背景或整张生成结果已经人工批准。

blue_left mask版本 `50925f5bfb9d14acbf7c867de328f475f2f437b82adf6943a6e15ba08b67f495`；blue_right `b844b8508abbf364c5c538ec0646db799246b698b5b84237a544d76220537959`。右盘只验证审核，没有参与生成或修改。

API地址 `http://192.168.1.171:8188`。实际读取system_stats、object_info、history、queue及工作流列表。Windows沙箱首次网络读取出现WinError10013，获网络执行授权后访问正常；未修改DGX环境或服务。初始队列为空。

从实际成功历史任务 `b6a9195f-d37e-41cd-8a7e-90edb6460379` 提取API prompt原件，保存在 `configs/workflows/qwen_image21_api_original.json`，记录来源和固定SHA，不修改远程保存的工作流。无需用户再手工导出。参数映射经真实object_info检查：

| 用途 | 实际节点/参数 |
| --- | --- |
| 正/负提示词 | 452 TextEncodeQwenImage21 / prompt、negative_prompt |
| 分辨率 | 456 EmptyLatentImage / width、height |
| seed | 458 KSampler / seed |
| 保存前缀 | 461 SaveImageAdvanced / filename_prefix |
| 输出图片 | 461 SaveImageAdvanced / images |

实际模型文件：451 UnetLoaderGGUF `qwen-image-2.1-UC-BF16.gguf`；453 CLIPLoader `qwen3vl_8b_bf16.safetensors`；454 VAELoader `qwen_image_2.1_vae_bf16.safetensors`。沿用25步、cfg4.5、euler/simple；没有安装其他模型或依赖。实际文件名只是本服务器已存在配置，不假设3090机器也安装了它们。

原任务是像素画UI，因此同时替换了正向与负向提示词，防止原像素画限制污染摄影背景。每任务保存提交后的完整工作流、哈希、prompt_id、seed、history、远程图片名和下载文件SHA。API采用 `/prompt`、`/history/{prompt_id}` 与 `/view`，参考 [ComfyUI官方路由说明](https://docs.comfy.org/development/comfyui-server/comms_routes)。超时/HTTP/远程执行错误写入failed记录，不返回假成功；超时不全局interrupt其他用户任务，prompt_id可用于检查远程是否继续执行。

## 三种模板与合成

`configs/phase3a_scenes.json`：纯白背景由Python产生；中性商业影棚与高级场景由QwenImage实际生成。高级场景由人工配置名称选择，不把商品类别推断或圆盘规则写入通用合成器。模型不接收前景，背景保留为独立文件。

1024×1024输出；蓝盘scale=1.0，原图不透明前景按整数平移保持像素完全一致；手提包scale=0.85，使用同一个标量的二维仿射矩阵，进行确定性插值。没有拉伸、透视、商品重绘、补造背面或新角度。缩放后的像素来自原图插值，不能称手提包每个输出像素与原图逐一相等。

RGB/Alpha先预乘，再同步Lanczos4缩放和平移后合成，避免透明区域隐藏RGB污染边缘。前景原件、原Alpha、背景、变换后Alpha、compose_config和composite_manifest独立保留。没有边缘RGB去污染版本，仍保留真实原始前景；微细白边/反光需视觉审核。当前无ICC素材按sRGB值合成；有ICC素材会明确拒绝，需后续受控色彩转换，不静默变色。

阴影默认关闭，采用正视悬浮/平面背景展示，不伪造桌面接触关系。引擎支持可选独立平面背景柔影层，仅backdrop模式；不实现伪造地面阴影。

## 文件与运行

新增 providers/comfyui.py、generation/compositor.py、scripts/generate_background.py、scripts/run_phase3a.py、scripts/validate_phase3a.py、tests/test_phase3a.py；新增实际API模板与两份配置。现有通用schema、专项插件、分割/修复及旧测试保留。历史通用任务规划器仍只规划，本阶段使用显式场景配置的最小生成脚本，并独立复用现有资产审核校验。

```powershell
python scripts/run_phase3a.py
python scripts/validate_phase3a.py
python -m unittest discover -s tests -q
```

运行根目录为项目目录。再次执行会核验并复用**已成功且配置/背景SHA一致的真实任务**；不会把静态图片伪装成新任务。失败目录或来源/config变化应使用 `--output-root data/outputs/phase3a_new_run`，保留旧记录。运行需要本机能够联网访问DGX，模型推理与下载期间每次HTTP请求有超时，总等待预算1800秒。当前最小实现不自动重提交可能已被远程接受的任务，避免重复排队。

两实例分别位于 `data/outputs/phase3a/blue_left/` 与 `.../bag/`，各有white_hero.png、studio.png、lifestyle.png及manifest.json；模板子目录中是final.png与完整合成记录；独立背景及真实任务记录位于 `data/outputs/phase3a/backgrounds/`。

核验图 `reports/phase3a_comparison.png`，机器报告 `reports/phase3a_validation.json`，遮罩审核实测报告 `reports/phase3a/mask_review_verification.json`，初始API响应快照 `reports/phase3a/`。

## 验证边界

新增单元测试使用mock-not-real标识，只验证错误处理/映射/门禁。实际GPU工作流运行另保存四个真实prompt_id，不将Mock测试算成真实生成。

自动检查输出尺寸和PNG完整性、来源/实例/遮罩版本、裁切、原始前景快照、透明区透出背景、1:1不透明区域像素、preview未提升为strict；真实任务还比对history中工作流与提交哈希。蓝盘逐点检查三个大孔与中心小孔，手提包检查提手间隙。这些是可复核的采样和像素映射检查，不是完整语义/文字检测或用户视觉批准。

视觉需审阅位置、光照、合成感、微细边缘和背景语义。蓝盘工业场景背景出现了提示词未要求的下方地面线：保留为悬浮展示候选，不制造接触阴影，等待审核。现阶段没有自动语义检测多余商品/Logo，助手视觉检查也不提升human_review_status。

最终测试数量、各真实任务时长、六张结果及视觉检查明细以phase3a_validation.json为准；完成后等待用户验收，不进入下一阶段。

## 本轮最终运行结果

140项自动化测试通过（原120＋新增20），2.741秒；mock错误测试与以下真实GPU任务分开记录。

| 实例/模板 | 实际prompt_id | seed | 远程调用总秒数 |
| --- | --- | --- | --- |
| blue_left/studio | aa1a469c-5199-4c77-b8f8-d27795e2085b | 315001 | 81.0 |
| blue_left/lifestyle | 35bb629f-5517-4575-b771-6786bfcfd1cb | 315002 | 81.07 |
| bag/studio | 424ab221-fa57-48d2-8100-f4838f8590a4 | 315101 | 80.82 |
| bag/lifestyle | f12e2f17-77e6-497a-8d6a-6164540b3043 | 315102 | 80.86 |

六张1024×1024最终合成图已真实导出，独立验证全部通过。四个任务各生成一张背景，不含两张纯白Python背景。商品原始资产未修改。蓝盘三图不透明区域原像素完全一致；手提包三图为0.85统一缩放后的原图插值。

助手已查看六图汇总及背景/细节：未观察到额外商品或文字，尚不等于自动语义检测或用户验收。两个高级场景都存在下方表面/背景纸弯折；手提包暖色背景顶部有不均匀灰泥纹理。全部等待审核，不称其物理摆放已验证。

- [x] 有效蓝盘具名审核门禁、手提包preview隔离。
- [x] 四个实际QwenImage任务与六张最终图片、哈希和来源记录。
- [x] 三大孔、中心小孔、提手间隙采样透出背景。
- [x] 原120项测试保留，新增20项通过。
- [ ] 用户审核构图、场景表面、边缘/白晕和整体搭配。
- [ ] 阶段3A验收通过。
