# ComfyUI-OneAPI

ComfyUI-OneAPI is a plugin that provides simple REST API interfaces for ComfyUI, allowing you to execute ComfyUI workflows through a single API request.

[中文文档](README_CN.md)

## Features

- **Simple Interface**: Execute complex ComfyUI workflows through a single API endpoint
- **Parameter Mapping**: Support for dynamically replacing parameters in workflows
- **Asynchronous Execution**: Support for both synchronous and asynchronous execution modes
- **No WebSocket Dependency**: Uses HTTP polling to get results, no need to handle WebSocket connections

## Installation

1. Download or clone this repository to the `custom_nodes` directory of ComfyUI
2. Restart ComfyUI

## API Usage

### Execute Workflow

```
POST /oneapi/v1/execute

Request Body:
{
    "workflow": {Workflow JSON},
    "params": {
        "paramName": "paramValue"
    }
}
```

## Workflow Parameter Mapping

To use dynamic parameters in your workflow, you need to use special markers in the node titles:

1. LoadImage node: Use `$image_param` format
2. Other nodes: Use `$param.field_name` format

Examples:

- A LoadImage node marked with `$input_image` will use the input_image parameter from params as the image param
- A CLIPTextEncode node marked with `$prompt.text` will replace the text field with the prompt parameter from params

## Examples

### curl Examples

#### Text-to-Image Example

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

#### Image-to-Image Example

```bash
# Execute image-to-image workflow
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

## Notes

- This plugin is designed to simplify API calls, and does not provide WebSocket real-time progress information
- Long-running workflows may cause request timeouts, consider setting appropriate timeout values
- Parameter mapping in workflows depends on special markers in node titles 