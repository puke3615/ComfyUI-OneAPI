import os
import json
import traceback
import uuid
import time
import copy
import asyncio
import aiohttp
import tempfile
import mimetypes
from urllib.parse import urlparse
from aiohttp import web
from server import PromptServer
import execution
from workflow_ui_2_api import convert_ui_to_api, adjust_workflow_format

# Get routes
routes = PromptServer.instance.routes

# Get workflow paths
path_custom_nodes = os.path.dirname(os.path.dirname(__file__))
path_comfyui_root = os.path.dirname(path_custom_nodes)
path_workflows = os.path.join(path_comfyui_root, 'user/default/workflows')

# Output node types for workflow result extraction
OUTPUT_NODE_TYPES = ["SaveImage", "SaveVideo", "VHS_VideoCombine"]

@routes.post('/oneapi/v1/execute')
async def execute_workflow(request):
    """
    Execute workflow API
    
    Parameters:
    - workflow: Workflow JSON, filename (under user/default/workflows/), or URL
    - params: Parameter mapping dictionary
    - wait_for_result: Whether to wait for results (default True)
    - timeout: Timeout in seconds (default 300)
    
    Returns:
    - Return values:
        - status: Status (queued, processing, completed, timeout)
        - prompt_id: Prompt ID
        - images: List of image URLs [string, ...], only present if there are image results
        - images_by_var: Mapped image URLs by variable name {var_name: [string, ...], ...}, only present if there are image results
        - videos: List of video URLs [string, ...], only present if there are video results
        - videos_by_var: Mapped video URLs by variable name {var_name: [string, ...], ...}, only present if there are video results
    
    Node title markers:
    - Input: Use "$param.field" in node title to map parameter values
    - Output: Use "$output" or "$output.name" in output node title (see OUTPUT_NODE_TYPES) to specify outputs
      - "$output.name" - Marks an output node with a custom output name (added to "images_by_var[name]" or "videos_by_var[name]")
      - If no explicit output marker is set, the node_id is used as the variable name
      - Only nodes in OUTPUT_NODE_TYPES are considered for output
      - images/images_by_var/videos/videos_by_var fields are only included if there are corresponding results
    """
    try:
        # Get request data
        data = await request.json()
        
        # Extract parameters
        workflow = data.get('workflow')
        params = data.get('params', {})
        wait_for_result = data.get('wait_for_result', True)
        timeout = data.get('timeout', None)

        # Support workflow as local path or URL
        if isinstance(workflow, dict):
            pass  # Use directly
        elif isinstance(workflow, str):
            if workflow.startswith('http://') or workflow.startswith('https://'):
                workflow = await _load_workflow_from_url(workflow)
            else:
                workflow = _load_workflow_from_local(workflow)
        else:
            return web.json_response({"error": "Invalid workflow parameter"}, status=400)
        
        if not workflow:
            return web.json_response({"error": "Workflow data is missing"}, status=400)
        
        # Convert UI format to API format if needed
        fmt = adjust_workflow_format(workflow)
        if fmt == 'invalid':
            return web.json_response({"error": "Invalid workflow format"}, status=400)
        if fmt == 'ui':
            workflow = await convert_ui_to_api(workflow)
        
        # Process workflow parameters
        if params:
            workflow = await _apply_params_to_workflow(workflow, params)
        
        # Extract and save output node information
        output_id_2_var = await _extract_output_nodes(workflow)
        
        # Generate client ID
        client_id = str(uuid.uuid4())
        
        # Submit workflow to ComfyUI queue
        try:
            prompt_id = await _queue_prompt(workflow, client_id)
        except Exception as e:
            error_message = f"Failed to submit workflow: [{type(e)}] {str(e)}"
            print(error_message)
            return web.json_response({"error": error_message}, status=500)
        
        result = {
            "status": "queued",
            "prompt_id": prompt_id,
            "message": "Workflow submitted"
        }
        
        # If not waiting for results, return immediately
        if not wait_for_result:
            return web.json_response(result)
        
        # Poll for results
        result = await _wait_for_results(prompt_id, timeout, request, output_id_2_var)
        return web.json_response(result)
        
    except Exception as e:
        print(f"Error executing workflow: {str(e)}, {traceback.format_exc()}")
        return web.json_response({"error": str(e)}, status=500)

async def _apply_params_to_workflow(workflow, params):
    """
    Apply parameters to the workflow
    
    Handles two types of parameter mappings:
    1. LoadImage node: $image_param
    2. Regular node: $param.field
    """
    workflow = copy.deepcopy(workflow)
    
    for node_id, node_data in workflow.items():
        # Skip nodes that don't meet criteria
        if not _is_valid_node(node_data):
            continue
            
        # Process parameter markers in the node
        await _process_node_params(node_data, params)
    
    return workflow

def _is_valid_node(node_data):
    """Check if node is valid and contains a title"""
    return (isinstance(node_data, dict) and 
            "_meta" in node_data and 
            "title" in node_data["_meta"])

async def _process_node_params(node_data, params):
    """Process parameter markers in the node"""
    title = node_data["_meta"]["title"]
    
    # Split title and look for parameter markers
    parts = title.split(',')
    for part in parts:
        part = part.strip()
        if not part.startswith('$'):
            continue
            
        # Process parameter marker
        await _process_param_marker(node_data, part[1:], params)

async def _extract_output_nodes(workflow):
    """
    Extract output nodes and their output variable names from workflow
    (output node types are defined in OUTPUT_NODE_TYPES)
    
    Args:
        workflow: Workflow JSON object
        
    Returns:
        Dictionary mapping node_id to output variable name
    
    Note:
        Only nodes in OUTPUT_NODE_TYPES are considered as output nodes.
        Output fields (images, videos, *_by_var) are only included in the response if there are corresponding results.
    """
    output_id_2_var = {}
    
    for node_id, node_data in workflow.items():
        # Skip nodes that don't meet criteria
        if not _is_valid_node(node_data):
            continue
        
        # Only process output nodes (see OUTPUT_NODE_TYPES)
        if node_data.get('class_type') not in OUTPUT_NODE_TYPES:
            continue
            
        # Get node title
        title = node_data["_meta"]["title"]
        
        # Check for $output marker in the title
        output_var = None
        parts = title.split(',')
        for part in parts:
            part = part.strip()
            if part.startswith('$output'):
                # Parse output marker
                if '.' in part:
                    # Format: $output.name - Specify output name
                    output_var = part.split('.', 1)[1]
                    if not output_var:
                        raise Exception(f"Invalid output marker format (empty name): {part}")
                else:
                    # Simple $output without variable name is not valid
                    raise Exception(f"Invalid output marker format (missing name): {part}. Use $output.name format.")
        
        # For output nodes, always register in output_id_2_var
        # If no explicit marker, use node_id as the variable name
        output_id_2_var[node_id] = output_var if output_var else str(node_id)
    
    return output_id_2_var

async def _process_param_marker(node_data, var_spec, params):
    """
    Process individual parameter marker
    
    Format: param_name.field_name
    - param_name: Parameter name, corresponding to key in params
    - field_name: Node input field name
    
    Special handling for LoadImage node's image field
    """
    # Must have field separator
    if '.' not in var_spec:
        print(f"Parameter marker format error, should be '$param.field': {var_spec}")
        return
        
    # Parse parameter name and field name
    var_name, input_field = var_spec.split('.', 1)
    
    # Check if parameter exists
    if var_name not in params:
        return
        
    # Get parameter value
    param_value = params[var_name]
    
    # Special handling for LoadImage node's image field
    if node_data.get('class_type') == 'LoadImage':
        await _handle_load_image(node_data, param_value)
    else:
        # Regular parameter setting
        await _set_node_param(node_data, input_field, param_value)

async def _handle_load_image(node_data, image_path_or_url):
    """
    Handle LoadImage node's image parameter
    
    Args:
        node_data: Node data
        image_path_or_url: Image path or URL
    """
    # Ensure inputs exists
    if "inputs" not in node_data:
        node_data["inputs"] = {}
    
    # If parameter value is a URL starting with http, upload the image first
    if isinstance(image_path_or_url, str) and image_path_or_url.startswith(('http://', 'https://')):
        try:
            # Upload image and get uploaded image name
            image_value = await _upload_image_from_source(image_path_or_url)
            # Use uploaded image name as LoadImage node's image value
            await _set_node_param(node_data, "image", image_value)
            print(f"Image uploaded: {image_value}")
        except Exception as e:
            print(f"Failed to upload image: {str(e)}")
            # Throw exception on upload failure
            raise Exception(f"Image upload failed: {str(e)}")
    else:
        # Use parameter value directly as image name
        await _set_node_param(node_data, "image", image_path_or_url)

async def _set_node_param(node_data, input_field, param_value):
    """
    Set node parameter
    
    Args:
        node_data: Node data
        input_field: Input field name
        param_value: Parameter value
    """
    # Ensure inputs exists
    if "inputs" not in node_data:
        node_data["inputs"] = {}
    # Set parameter value
    node_data["inputs"][input_field] = param_value

async def _upload_image_from_source(image_url) -> str:
    """
    Upload image from URL
    
    Args:
        image_url: Image URL
            
    Returns:
        Upload image file name
    """
    # Download image from URL
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download image: HTTP {response.status}")
            
            # Extract filename from URL
            parsed_url = urlparse(image_url)
            filename = os.path.basename(parsed_url.path)
            if not filename:
                filename = f"temp_image_{hash(image_url)}.jpg"
            
            # Get image data
            image_data = await response.read()
            
            # Save to temporary file
            suffix = os.path.splitext(filename)[1] or ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(image_data)
                temp_path = tmp.name
    
    try:
        # Upload temporary file to ComfyUI
        return await _upload_image(temp_path)
    finally:
        # Delete temporary file
        os.unlink(temp_path)

async def _upload_image(image_path) -> str:
    """
    Upload image to ComfyUI
    
    Args:
        image_path: Image path
            
    Returns:
        Upload image file name
    """
    # Read image data
    with open(image_path, 'rb') as f:
        image_data = f.read()
    
    # Extract filename
    filename = os.path.basename(image_path)
    
    # Auto-detect file MIME type
    mime_type = mimetypes.guess_type(filename)[0]
    if mime_type is None:
        # Default to generic image type
        mime_type = 'application/octet-stream'
    
    # Prepare form data
    data = aiohttp.FormData()
    data.add_field('image', image_data, 
                   filename=filename, 
                   content_type=mime_type)
    
    # Upload image (internal ComfyUI API call still uses 127.0.0.1)
    async with aiohttp.ClientSession() as session:
        async with session.post("http://127.0.0.1:8188/upload/image", data=data) as response:
            if response.status != 200:
                raise Exception(f"Failed to upload image: HTTP {response.status}")
            
            # Get upload result
            result = await response.json()
            return result.get('name', '')

async def _queue_prompt(workflow, client_id):
    """Submit workflow to queue using HTTP API"""
    prompt_data = {
        "prompt": workflow,
        "client_id": client_id
    }
    
    json_data = json.dumps(prompt_data)
    
    # Use aiohttp to send request
    async with aiohttp.ClientSession() as session:
        async with session.post(
                "http://127.0.0.1:8188/prompt", 
                data=json_data,
                headers={"Content-Type": "application/json"}
            ) as response:
            if response.status != 200:
                response_text = await response.text()
                raise Exception(f"Failed to submit workflow: [{response.status}] {response_text}")
            
            result = await response.json()
            prompt_id = result.get("prompt_id")
            if not prompt_id:
                raise Exception(f"Failed to get prompt_id: {result}")
            return prompt_id

async def _get_base_url(request):
    """
    Get base URL for building image URLs
    
    Args:
        request: HTTP request object
        
    Returns:
        Base URL string
    """
    # Default base URL for local access
    base_url = "http://127.0.0.1:8188"
    
    if request:
        host = request.headers.get('Host')
        if host:
            # Try multiple methods to get request protocol
            scheme = request.headers.get('X-Forwarded-Proto') or \
                     request.headers.get('X-Scheme') or \
                     request.headers.get('X-Forwarded-Scheme') or \
                     (request.headers.get('X-Forwarded-Ssl') == 'on' and 'https') or \
                     (request.headers.get('X-Forwarded-Protocol') == 'https' and 'https') or \
                     ('https' if request.url.scheme == 'https' else 'http')
            
            # Build base URL
            base_url = f"{scheme}://{host}"
    
    return base_url

# Helper: extract URLs for a specific media type from a node output
def _extract_node_media_urls(node_output, base_url, media_key):
    """
    Extract URLs for a specific media type (e.g., 'images', 'gifs') from a node output.
    Args:
        node_output: Output dict for a node
        base_url: Base URL for constructing file URLs
        media_key: Key in node_output ('images' or 'gifs')
    Returns:
        List of URLs for the specified media type
    """
    urls = []
    for media_data in node_output.get(media_key, []):
        filename = media_data.get("filename")
        subfolder = media_data.get("subfolder", "")
        media_type = media_data.get("type", "output")
        url = f"{base_url}/view?filename={filename}"
        if subfolder:
            url += f"&subfolder={subfolder}"
        if media_type:
            url += f"&type={media_type}"
        urls.append(url)
    return urls

# Helper: collect all outputs of a given media type from all nodes
def _collect_outputs_by_type(outputs, base_url, media_key):
    """
    Collect all outputs of a given media type from all nodes.
    Args:
        outputs: All outputs dict
        base_url: Base URL for constructing file URLs
        media_key: Key in node_output ('images' or 'gifs')
    Returns:
        Dict mapping node_id to list of URLs
    """
    result = {}
    for node_id, node_output in outputs.items():
        urls = _extract_node_media_urls(node_output, base_url, media_key)
        if urls:
            result[node_id] = urls
    return result

# Helper: map outputs by variable name
def _map_outputs_by_var(output_id_2_var, output_id_2_media):
    """
    Map outputs by variable name using output_id_2_var mapping.
    Args:
        output_id_2_var: Dict mapping node_id to variable name
        output_id_2_media: Dict mapping node_id to list of URLs
    Returns:
        Dict mapping variable name to list of URLs
    """
    result = {}
    for node_id, var_name in output_id_2_var.items():
        if node_id in output_id_2_media:
            result[var_name] = output_id_2_media[node_id]
    return result

# Helper: flatten all lists in a dict into a single list
def _extend_flat_list_from_dict(media_dict):
    """
    Flatten all lists in a dict into a single list.
    Args:
        media_dict: Dict of lists
    Returns:
        Flat list of all items
    """
    flat = []
    for items in media_dict.values():
        flat.extend(items)
    return flat

def _split_media_by_suffix(node_output, base_url):
    """
    Split all media entries in node_output into images/videos by file extension.
    Args:
        node_output: Output dict for a node
        base_url: Base URL for constructing file URLs
    Returns:
        (images: list, videos: list) - lists of URLs
    """
    image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'}
    video_exts = {'.mp4', '.mov', '.avi', '.webm', '.gif'}
    images = []
    videos = []
    for media_key in ("images", "gifs"):
        for media_data in node_output.get(media_key, []):
            filename = media_data.get("filename")
            subfolder = media_data.get("subfolder", "")
            media_type = media_data.get("type", "output")
            url = f"{base_url}/view?filename={filename}"
            if subfolder:
                url += f"&subfolder={subfolder}"
            if media_type:
                url += f"&type={media_type}"
            ext = os.path.splitext(filename)[1].lower()
            if ext in image_exts:
                images.append(url)
            elif ext in video_exts:
                videos.append(url)
    return images, videos

async def _wait_for_results(prompt_id, timeout=None, request=None, output_id_2_var=None):
    """Wait for workflow execution results, get history using HTTP API"""
    start_time = time.time()
    result = {
        "status": "processing",
        "prompt_id": prompt_id,
        "images": [],
        "images_by_var": {},
        "videos": [],
        "videos_by_var": {}
    }

    # Get base URL for image/video URLs
    base_url = await _get_base_url(request)

    while True:
        # Check timeout
        if timeout is not None and timeout > 0 and (time.time() - start_time) > timeout:
            result["status"] = "timeout"
            return result

        # Get history using HTTP API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:8188/history") as response:
                    if response.status != 200:
                        await asyncio.sleep(1.0)
                        continue
                    history_data = await response.json()
                    if prompt_id not in history_data:
                        await asyncio.sleep(1.0)
                        continue
                    prompt_history = history_data[prompt_id]
                    if "outputs" in prompt_history:
                        result["outputs"] = prompt_history["outputs"]
                        result["status"] = "completed"

                        # Collect all image and video outputs by file extension
                        output_id_2_images = {}
                        output_id_2_videos = {}
                        for node_id, node_output in prompt_history["outputs"].items():
                            images, videos = _split_media_by_suffix(node_output, base_url)
                            if images:
                                output_id_2_images[node_id] = images
                            if videos:
                                output_id_2_videos[node_id] = videos

                        # Map by variable name if mapping is available
                        if output_id_2_var and output_id_2_images:
                            result["images_by_var"] = _map_outputs_by_var(output_id_2_var, output_id_2_images)
                            result["images"] = _extend_flat_list_from_dict(result["images_by_var"])
                        elif output_id_2_images:
                            result["images"] = _extend_flat_list_from_dict(output_id_2_images)

                        if output_id_2_var and output_id_2_videos:
                            result["videos_by_var"] = _map_outputs_by_var(output_id_2_var, output_id_2_videos)
                            result["videos"] = _extend_flat_list_from_dict(result["videos_by_var"])
                        elif output_id_2_videos:
                            result["videos"] = _extend_flat_list_from_dict(output_id_2_videos)

                        # Remove empty fields for images/videos
                        if not result["images"]:
                            result.pop("images")
                        if not result["images_by_var"]:
                            result.pop("images_by_var")
                        if "videos" in result and not result["videos"]:
                            result.pop("videos")
                        if "videos_by_var" in result and not result["videos_by_var"]:
                            result.pop("videos_by_var")

                        return result
        except Exception as e:
            print(f"Error getting history: {str(e)}")
        await asyncio.sleep(1.0)

# New: Load workflow from local file
def _load_workflow_from_local(filename):
    """
    Load workflow JSON from user/default/workflows directory
    """
    file_path = os.path.join(path_workflows, filename)
    if not os.path.isfile(file_path):
        raise Exception(f"Workflow file not found: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# New: Load workflow from URL
async def _load_workflow_from_url(url):
    """
    Download workflow JSON from URL
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download workflow: HTTP {response.status}")
            text = await response.text()
            try:
                return json.loads(text)
            except Exception as e:
                raise Exception(f"Invalid workflow JSON from url: {e}")

print("ComfyUI-OneAPI routes registered") 