# 4C P0 运行依赖与部署审计

## 已确认的旧路径依赖

旧 Skill 启动器以自身父目录定位 checkout，检查 scripts/src 并插入 root/src；入口固定 ROOT，输出限制在 root/data/outputs。原始图片分割调用 checkout/scripts/segment_product.py 和 .venv-seg；平台规则、工作流和字体也位于工程或系统路径。仅复制 SKILL.md 没有复制引擎，不能独立运行。

## 最小部署改变

- pyproject.toml 保留原包名与旧命令，新增 product-studio / python -m product_studio；Wheel 包含两个现有 Python 包，既有算法和旧脚本兼容入口保留。
- 安装后 generate 固定使用 portable 路由，输入相对 request，显式 output 相对调用 cwd；不搜索 checkout、旧样例、旧商品或旧输出。
- NumPy 2.4.4、Pillow 12.2.0、OpenCV headless 4.13.0.92 是基本依赖，WSL 新 venv 已实际安装。分割另需可选 ONNX Runtime 与显式模型，不随 Wheel 发布。
- 工作流 API JSON、原始模板哈希、真实节点参数映射、四个平台预设随 Wheel 发布。ComfyUI 地址必须通过环境变量或独立配置提供，无开发地址默认值。不同服务器须显式配置自己的实际工作流。
- 英文字体使用已安装 Arial/DejaVu；中文需可用中文字体或显式路径。没有发布字体版权文件、模型权重、密钥。
- portable asset bundle 携带选定实例源图/alpha/RGBA/spec/result/审核证据；导入仅重定位文件引用，记录原 JSON 哈希与映射。源图、mask_version、RGBA、审核记录字节保持不变；不创建审核或提升状态。
- Skill 启动器只导入安装模块；缺失引擎时 exit 3，不查找开发目录。输入缺少真实视觉分析时 exit 2，生成 handoff 而非伪成功。

## 验收边界

原 224 测试在修改前通过；首次受限沙箱系统临时目录存在权限错误，改用 reports/phase4c/test_tmp 后重跑通过。没有修改测试断言以绕过错误。

P0 隔离采用 WSL mount/PID namespaces：以 tmpfs 遮蔽 /mnt 和 /run/WSL，隐藏 /init，再降权 UID1000、清全部 capabilities、no_new_privs、清 PYTHONPATH。探针同时验证原工程路径与 /proc/1/root 别名不可读。不是仅仅换 cwd 或设置一个“不读取”的提示。

独立引擎预检和新白底图、真实 ComfyUI 商业背景图已运行；第二 Agent 的行为验收与完整 P0 结论另见 phase4c_results.md 和 validation JSON。技术成功不等于最终图片人工批准。
