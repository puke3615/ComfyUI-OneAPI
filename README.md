# ComfyUI-OneAPI ✨

ComfyUI-OneAPI is a plugin that provides simple REST API interfaces for ComfyUI, allowing you to execute complex ComfyUI workflows through a single API request.

[中文文档](README_CN.md)

## ⚡️ Quick Start

### 🚀 Execute Workflow with Just One Request

```bash
curl -X POST "http://localhost:8188/oneapi/v1/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": {...}  # Replace with your workflow JSON
  }'
```

### 📝 Simplest Request Format

```json
{
  "workflow": {...}  // API version of workflow JSON
}
```

### 📤 Common Response Format

```json
{
  "status": "completed",
  "images": ["http://server/image1.png", "http://server/image2.png"]
}
```

## 🔥 Advanced Usage

### 1️⃣ Dynamic Parameter Replacement - No More Workflow Edits 🔄

Add markers in node titles to easily replace parameters:

```json
// Request
{
  "workflow": {...},
  "params": {
    "prompt": "cute cat",
    "input_image": "https://example.com/image.jpg"
  }
}
```

**✨ How to Mark Nodes:**
- 📝 Text Prompt: Add `$prompt.text` to CLIPTextEncode node title
- 🖼️ Input Image: Add `$input_image` to LoadImage node title

### 2️⃣ Distinguish Multiple Outputs - Handle Complex Workflows 🧩

When your workflow has multiple SaveImage nodes, easily distinguish different outputs:

```json
// Response
{
  "status": "completed",
  "images": ["http://server/image1.png", "http://server/image2.png"],
  "images_by_var": {
    "background": ["http://server/image1.png"],
    "character": ["http://server/image2.png"]
  }
}
```

**✨ How to Mark Output Nodes:**
- 💾 Add `$output.background` or `$output.character` to SaveImage node titles

## 📋 Advanced Features

### 📦 Installation

1. Download or clone this repository to the `custom_nodes` directory of ComfyUI
2. Restart ComfyUI

### 🔌 API Parameters

```
POST /oneapi/v1/execute

Request Body:
{
    "workflow": {...},               // API version of workflow JSON
    "params": {...},                 // Optional: Parameter mapping
    "wait_for_result": true/false,   // Optional: Wait for results (default true)
    "timeout": 300                   // Optional: Timeout in seconds
}
```

### 🏷️ Node Title Marker Rules

#### ⬇️ Input Parameter Markers

1. 🖼️ LoadImage node: Use `$image_param` format
2. 🔄 Other nodes: Use `$param.field_name` format

Examples:
- `$input_image` - LoadImage node uses params.input_image as the image
- `$prompt.text` - Replaces text field with params.prompt

#### ⬆️ Output Markers

Add markers to SaveImage node titles:
- Format: `$output.name` (e.g., `$output.background`)
- Without markers, node ID is used as the variable name

## 🔍 Examples

### 📝 Text-to-Image Example

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

### 🖼️ Image-to-Image Example

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

## ⚠️ Notes

- 🔄 This plugin uses HTTP polling to get results, does not provide WebSocket real-time progress
- ⏱️ Long-running workflows may cause request timeouts, consider setting appropriate timeout values
- 🏷️ Parameter mapping and output marking depend on special markers in node titles 