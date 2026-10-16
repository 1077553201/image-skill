# 两路生图

## 共同边界

一个批次只选 `agent` 或 `comfyui`，先询问并记录用户对最终提示词、路线、候选数量和尝试次数的确认。不可用时说明问题，未经用户选择不切换其他路线、模型或计费服务。不得把用户对 Skill 开发的同意视为具体商品批次的确认。

以批准的版本执行；人物、道具先生成统一参考图并验收，样张完成排字验收后制作其他页。普通页面的新增营销文字通过真实字体排版，不要求图像模型绘制。图片输出自动归档，成功、待检查、失败、远端状态不明分别记录。

## agent 内置生图

使用当前环境中实际暴露的图像生成工具，例如支持生图的 Codex 环境。不同 agent 的能力、输入参考图数量、输出尺寸和额度不同，先检查，不硬编码模型或会员权益。执行工具本身不会调用 OpenAI API、代理或处理登录凭据。

工作方式：`run` 创建待调用记录 → agent 读取对应提示词和参考图 → 按该生图工具自身要求调用 → 使用 `import-agent` 保存真实输出。调用标识和工具名必须来自实际执行。工具不可用或受限时报告，等待用户调整；不要用本地画图代替模型图来通过验证。

## 远程 ComfyUI 连接

先读取项目根目录的 `detail-page.connection.json`。没有配置时询问服务器地址，若用户在当前会话已提供地址直接验证使用；不从旧配置或历史报告自动猜地址。验证并保存：

```text
python -X utf8 <runtime> connection --project-root <项目绝对路径> --url <用户提供的服务器地址>
```

该命令只读取 `/object_info` 和 `/queue` 验证连接，然后保存地址、验证时间与节点数；不会提交工作流，不测试生图能力。更换地址后重新执行；连接失败不会覆盖已有配置。此文件是项目连接设置，不放到系统根目录或 Skill 目录。服务器路径和本地项目路径分开，不将 Windows 本地路径直接传给远程 `LoadImage`。

## 工作流配置

先检查实际 `/object_info`，选择服务器已安装且功能相符的工作流。保存 **API prompt 格式**（节点 ID → class_type/inputs）；编辑器的 `nodes/links` JSON 不能直接提交。现有工作流必须确认其模型、参考图编辑能力及用途，背景专用工作流不能冒充商品参考图编辑。

将真实工作流归档到 `06-工作流与执行记录/workflow-api.json`，并依据真实节点编写配置。以下是格式示意，节点名和 ID 都必须由实际工作流替换，不能直接拿来提交：

```json
{
  "workflow": "06-工作流与执行记录/workflow-api.json",
  "output_node": "save-node-id",
  "mapping": {
    "prompt": {"node": "text-node-id", "class_type": "实际编码节点类型", "input": "实际提示词参数"},
    "prefix": {"node": "save-node-id", "class_type": "实际保存节点类型", "input": "filename_prefix"},
    "reference_0": {"node": "image-node-id", "class_type": "LoadImage", "input": "image"}
  }
}
```

支持映射 `prompt`、`negative_prompt`、`width`、`height`、`seed`、`prefix`、`candidates` 和按任务参考图顺序编号的 `reference_0`、`reference_1` 等。`prompt` 与 `prefix` 必需；多候选时 `candidates` 必需。尺寸、seed 未映射时，模板固定值必须与批准任务一致，agent 在提交前核对。参考图数量和接口必须适配，每个 LoadImage 都需要显式绑定批准的参考图。其他自定义图像载入节点的行为必须单独检查，不能夹带模板残留的商品图片。

不同任务需要不同工作流或数量不一致的参考图接口时，给对应任务指定 `workflow_config`，选择适配模板并一并确认执行设置。禁止为了跑通而丢弃参考图、变更商品身份或忽略人物道具依赖。

## 执行与取回

`run` 先验证图和真实节点，再上传本地参考图并校验上传字节，保存实际提交工作流，向 `/prompt` 提交一次。执行目录记录原服务器地址与 `prompt_id`。随后轮询：

```text
python -X utf8 <runtime> resume --task <task> --run <run-relative>
```

每次 `resume` 只检查一次历史。返回 `remote_pending` 时由 agent 适度等待后继续查询，不重复 `run`。工作流成功后核对历史中的图与实际提交图一致，再下载配置输出节点的真实 `output` 图片，检查尺寸和数量后写入本地方案目录。不能将 `input` 或 `temp` 图当成输出。

提交响应丢失时保存 `submission_uncertain`；保留 `submission.json`（若有）、工作流及时间，检查原服务器的队列和历史，先定位原任务。不能直接重新提交或全局中断其他用户任务。原服务器变更地址后，确认确实为同一服务且任务历史仍在，才更新该执行记录的连接地址并继续查询。

生成错误、依赖缺失、超过用户同意的等待时间或尝试上限时报告具体任务与状态，不删除记录或自动启动无限重试。当前工具不会自动更新 ComfyUI、安装自定义节点、接入会员代理或切换付费 API。
