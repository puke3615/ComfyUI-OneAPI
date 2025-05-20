# ComfyUI-OneAPI ✨

ComfyUI-OneAPI 是一个为 ComfyUI 提供简单REST API接口的插件，只需一个API请求即可执行复杂的ComfyUI工作流。

[English Documentation](README.md)

## ⚡️ 快速开始

### 🚀 仅需一个请求即可执行工作流

```bash
curl -X POST "http://localhost:8188/oneapi/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": {...}  # 替换为您的工作流JSON
  }'
```

### 📝 最简单的请求格式

```json
{
  "workflow": {...}  // 工作流的API版JSON
}
```

### 📤 常见响应格式

```json
{
  "status": "completed",
  "images": ["http://server/image1.png", "http://server/image2.png"]
}
```

## 🔥 进阶用法

### 1️⃣ 动态替换参数 - 告别工作流修改 🔄

在节点标题中添加标记，轻松替换参数：

```json
// 请求
{
  "workflow": {...},
  "params": {
    "prompt": "cute cat",
    "input_image": "https://example.com/image.jpg"
  }
}
```

**✨ 如何标记节点：**
- 📝 文本提示：在CLIPTextEncode节点标题添加 `$prompt.text`
- 🖼️ 输入图像：在LoadImage节点标题添加 `$input_image`

### 2️⃣ 区分多个输出 - 处理复杂工作流 🧩

当工作流有多个SaveImage节点时，轻松区分不同输出：

```json
// 响应
{
  "status": "completed",
  "images": ["http://server/image1.png", "http://server/image2.png"],
  "images_by_var": {
    "background": ["http://server/image1.png"],
    "character": ["http://server/image2.png"]
  }
}
```

**✨ 如何标记输出节点：**
- 💾 在SaveImage节点标题添加 `$output.background` 或 `$output.character`

## 📋 高级功能

### 📦 安装

1. 下载或克隆此仓库到ComfyUI的`custom_nodes`目录
2. 重启ComfyUI

### 🔌 API参数详解

```
POST /oneapi/v1/execute

请求体:
{
    "workflow": {...},               // 工作流的API版JSON
    "params": {...},                 // 可选：参数映射
    "wait_for_result": true/false,   // 可选：是否等待结果（默认true）
    "timeout": 300                   // 可选：超时时间（秒）
}
```

### 🏷️ 节点标题标记规则

#### ⬇️ 输入参数标记

1. 🖼️ LoadImage节点：使用 `$image_param` 格式
2. 🔄 其他节点：使用 `$param.field_name` 格式

示例：
- `$input_image` - LoadImage节点使用params.input_image作为图片
- `$prompt.text` - 使用params.prompt替换text字段

#### ⬆️ 输出标记

在SaveImage节点标题中添加标记：
- 格式：`$output.name`（如：`$output.background`）
- 无标记时使用节点ID作为标识

## 🔍 示例

### 📝 文生图示例

```bash
curl -X POST "http://localhost:8188/oneapi/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": '"$(cat workflows/example_workflow.json)"',
    "params": {
        "prompt": "a cute dog with a red hat"
    }
  }'
```

### 🖼️ 图生图示例

```bash
curl -X POST "http://localhost:8188/oneapi/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": '"$(cat workflows/example_img2img_workflow.json)"',
    "params": {
        "prompt": "a cute dog with a red hat",
        "image": "https://example.com/input.jpg"
    }
  }'
```

## ⚠️ 注意事项

- 🔄 此插件使用HTTP轮询获取结果，不提供WebSocket实时进度
- ⏱️ 长时间运行的工作流可能导致超时，请设置合适的timeout值
- 🏷️ 参数映射和输出标记依赖于节点标题中的特殊标记 