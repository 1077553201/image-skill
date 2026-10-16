# 阶段 0 实测与验收记录

检测时间：2026-10-14 18:34:46，Asia/Singapore（UTC+08:00）。原始 JSON 时间为 `2026-10-14T10:34:46.578615+00:00`。队列与可用内存均为当时快照。

证据文件：`reports/environment.json`；离线检测对照：`reports/local_only.json`。

## 已确认环境

| 项目 | Windows 工作区本机 | ComfyUI 服务端 API 返回 |
| --- | --- | --- |
| OS | Windows 11，10.0.26300 | Linux |
| 架构 | AMD64 | API 未提供，待服务端本地检测 |
| Python | 3.13.11，Anaconda 发行 | 3.12.14 |
| Python 路径 | `E:\ruanjian\miniconda\python.exe` | API 未提供 |
| GPU | RTX 4060 Laptop，8188 MiB | NVIDIA GB10 |
| NVIDIA 驱动 | 591.59 | API 未提供 |
| PyTorch | 2.11.0+cpu | 2.13.0+cu130 |
| 本地 CUDA 运算 | 当前 PyTorch 不支持 CUDA | 未执行服务端张量测试，API 报告设备类型为 cuda |
| ComfyUI | 未提供本机安装路径 | 0.37.0；实际安装路径待补充 |
| Blender | 未出现在 PATH；是否安装待确认 | API 未提供，待服务端本地检测 |

本机已确认 NumPy 2.4.4、OpenCV 包 4.13.0.92（模块版本 4.13.0）、Pillow 12.2.0 能实际导入。Shapely 未安装。`nvcc` 未出现在本机 PATH，不据此声称没有 CUDA Toolkit。

远程服务返回的 GB10 与用户所述 DGX Spark 相符，机器身份、CPU 架构及目录仍需用户确认。不能把本机 RTX 4060 误当作 DGX Spark 或最终 RTX 3090。API 返回的内存字段也不能作为 RTX 3090 容量验证。

## 实际运行结果

1. `python scripts/check_environment.py --output reports/environment.json`：退出码 0；Python、项目目录可写性、两条 API 响应结构检查通过。报告的 `acceptance.required_checks_passed=true`，`user_confirmation=pending`。
2. `python scripts/check_environment.py --skip-api --output reports/local_only.json`：退出码 0；API 为 `skipped`，验收状态为 `incomplete`，并未被误标为通过。
3. `python -m unittest discover -s tests -v`：**19 项测试全部通过**。覆盖 CPU 控制端、跳过 API、错误服务响应、网络失败、子进程缺失/超时/崩溃、缺失包元数据、未知 Blender 状态、错误配置、UTF-8 原子报告和 CLI 退出码。
4. 使用现有 setuptools 80.9.0 进行无网络、无新依赖的 wheel 构建成功；产物为 `reports/wheels/product_photo_system-0.1.0-py3-none-any.whl`。随后在 `reports/package_check` 测试安装成功，确认从该目录导入版本 0.1.0 并显示 CLI 帮助。未安装到全局 Python 或 ComfyUI 环境。

ComfyUI 实际只读检查使用用户给出的 `http://192.168.1.171:8188`，`GET /system_stats` 与 `GET /queue` 均返回有效结构。当时运行任务 1、等待任务 0。没有提交、停止、修改任务。

测试中的故障案例使用 mock，不连接或改动现有 ComfyUI。实际 API 可访问性由单独的完整脚本运行验证，不能以 mock 测试替代。

## 已解决问题

- 执行沙箱的默认系统临时目录权限导致首次测试和打包未完成。测试临时目录改为项目内；打包时 TEMP/TMP 指向项目 `reports/build_tmp`，重跑成功。这些环境变量只在该次打包进程使用。
- Windows 管道默认编码使中文终端输出显示异常。CLI 已明确设置 UTF-8，重跑显示正常；JSON 报告始终使用 UTF-8。
- 第一次通过 Python 脚本进行完整 API 检测时，自动审批审查超时，命令未启动；按工具允许重试一次后成功。该超时不是服务不可用的证据。

## 用户补充确认

1. 开发阶段使用本机配合 DGX Spark；最终系统统一部署到 RTX 3090 电脑。
2. DGX Spark 虚拟环境由 Conda 创建；用户要求暂不处理。具体 ComfyUI 安装路径、Python 路径保留未确认，不作为当前阶段的补充要求。
3. Blender 未安装。优先避免使用 Blender，不把安装它作为阶段 0 或阶段 1/2 的前提。

以上是用户提供的信息，未改写原始检测快照中的机器观测结果。阶段 3/4 再评估不使用 Blender 的确定性建模与渲染路线；最终 RTX 3090 电脑需在部署前单独检查 OS、Python 和 CUDA 兼容性。

## 验收进度

- [x] 工作区根目录 `D:\xiangmu\kglaoshi\shengtu-skill` 核实并创建最小 Python 骨架。
- [x] README、pyproject、环境配置、检测入口、测试与架构记录已创建。
- [x] 环境检测脚本已真实运行并保存有效报告。
- [x] 本机与服务端环境分开记录；未知信息、CPU 版与跳过项目均正确标记。
- [x] 两条 ComfyUI 只读 API 通过。
- [x] 19 项测试、wheel 构建与项目内安装验证通过。
- [x] 用户确认开发与最终部署位置；DGX Conda 路径按用户要求暂缓处理；Blender 未安装且优先避免使用。
- [x] 用户明确确认阶段 0 验收通过，授权开始阶段 1A；不授权提前进入 1B、1C 或 3D 建模。

本阶段未验证实际 QwenImage 工作流、商品图片处理、DGX Spark 直接运行此脚本或 RTX 3090 部署。本阶段没有安装大型模型、更新已有节点或实现阶段 1 以后的功能。
