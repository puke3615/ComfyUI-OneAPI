# ComfyUI-OneAPI

ComfyUI-OneAPI 是一个为 ComfyUI 提供简单REST API接口的插件，使您能够通过一个简单的API请求执行ComfyUI工作流。

[English Documentation](README.md)

## 特点

- **简单接口**：通过单个API接口执行复杂的ComfyUI工作流
- **参数映射**：支持动态替换工作流中的参数
- **异步执行**：支持同步或异步执行模式
- **无WebSocket依赖**：使用HTTP轮询获取结果，不需要处理WebSocket连接

## 安装

1. 下载或克隆此仓库到ComfyUI的`custom_nodes`目录
2. 重启ComfyUI

## API使用

### 执行工作流

```
POST /oneapi/v1/execute

请求体:
{
    "workflow": {工作流JSON},
    "params": {
        "参数名": "参数值"
    },
    "wait_for_result": true,
    "timeout": 300
}
```

## 工作流参数映射

要在工作流中使用动态参数，需要在节点标题中使用特殊标记：

1. LoadImage节点：使用 `$image_param` 格式
2. 其他节点：使用 `$param.field_name` 格式

例如：

- 标记为 `$input_image` 的LoadImage节点，将使用params中的input_image参数作为图片文件名
- 标记为 `$prompt.text` 的CLIPTextEncode节点，将使用params中的prompt参数替换text字段

## 示例

### curl示例

#### 文生图示例

```bash
curl -X POST "http://localhost:8188/oneapi/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": '"$(cat workflows/example_workflow.json)"',
    "params": {
        "prompt": "a cute dog with a red hat"
    },
    "wait_for_result": true
  }'
```

#### 图生图示例

```bash
# 执行图生图工作流
curl -X POST "http://localhost:8188/oneapi/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": '"$(cat workflows/example_img2img_workflow.json)"',
    "params": {
        "prompt": "a cute dog with a red hat",
        "image": "https://example.com/input.jpg"
    },
    "wait_for_result": true
  }'
```

## 注意事项

- 此插件设计为简化API调用，不提供WebSocket实时进度信息
- 超长时间的工作流可能导致请求超时，建议设置合理的超时时间
- 工作流中的参数映射依赖于节点标题中的特殊标记 