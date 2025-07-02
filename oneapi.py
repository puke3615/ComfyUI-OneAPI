import os
import json
import traceback
from typing import Sequence
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
import folder_paths
import execution
from workflow_format import adjust_workflow_format

# Constants
API_WORKFLOWS_DIR = 'api_workflows'

# Node types that require special media upload handling
MEDIA_UPLOAD_NODE_TYPES = {
    'LoadImage',
    'VHS_LoadAudioUpload',
    'VHS_LoadVideo',
}

# Get routes
prompt_server = PromptServer.instance
routes = prompt_server.routes

# Get workflow paths
path_custom_nodes = os.path.dirname(os.path.dirname(__file__))
path_comfyui_root = os.path.dirname(path_custom_nodes)
path_workflows = os.path.join(path_comfyui_root, 'user/default/workflows')

@routes.post('/oneapi/v1/save-api-workflow')
async def save_api_workflow(request):
    """
    Save API workflow to user's workflow directory.
    """
    data = await request.json()
    name = data.get('name')
    workflow = data.get('workflow')
    overwrite = data.get('overwrite', False)
    
    if not name:
        return web.json_response({"error": "Name is required"}, status=400)
    if not workflow:
        return web.json_response({"error": "Workflow is required"}, status=400)
    
    fmt = adjust_workflow_format(workflow)
    if fmt == 'invalid':
        return web.json_response({"error": "Invalid workflow format"}, status=400)
    if fmt == 'ui':
        return web.json_response({"error": "UI format workflow is not supported. Please convert to API format and try again."}, status=400)

    name_with_json = name if name.endswith('.json') else f'{name}.json'
    relative_path = f'{API_WORKFLOWS_DIR}/{name_with_json}'
    save_path = prompt_server.user_manager.get_request_user_filepath(request, relative_path, create_dir=True)
    if not save_path:
        return web.json_response({"error": "Failed to get save path"}, status=500)
    if os.path.exists(save_path) and not overwrite:
        return web.json_response({"error": "File already exists. Use overwrite=true to overwrite."}, status=400)
    
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(workflow, f, indent=2, ensure_ascii=False)

    return web.json_response({"message": "Workflow saved successfully", "filename": name_with_json})

@routes.post('/oneapi/v1/execute')
async def execute_workflow(request):
    """
    Execute workflow API
    
    Parameters:
    - workflow: Workflow JSON, filename (under user/default/api_workflows/), or URL
    - params: Parameter mapping dictionary
    - wait_for_result: Whether to wait for results (default True)
    - timeout: Timeout in seconds (default None)
    - prompt_ext_params: Extra parameters for prompt request (optional)
    
    Returns:
    - Return values:
        - status: Status (queued, processing, completed, timeout)
        - prompt_id: Prompt ID
        - images: List of image URLs [string, ...], only present if there are image results
        - images_by_var: Mapped image URLs by variable name {var_name: [string, ...], ...}, only present if there are image results
        - videos: List of video URLs [string, ...], only present if there are video results
        - videos_by_var: Mapped video URLs by variable name {var_name: [string, ...], ...}, only present if there are video results
        - audios: List of audio URLs [string, ...], only present if there are audio results
        - audios_by_var: Mapped audio URLs by variable name {var_name: [string, ...], ...}, only present if there are audio results
        - texts: List of text outputs [string, ...], only present if there are text results
        - texts_by_var: Mapped text outputs by variable name {var_name: [string, ...], ...}, only present if there are text results
    
    Node title markers:
    - Input: Use "$param.field" in node title to map parameter values
    - Output: Use "$output.name" in output node title to specify outputs
      - "$output.name" - Marks an output node with a custom output name (added to "images_by_var[name]" or "videos_by_var[name]" or "texts_by_var[name]")
      - If no explicit output marker is set, the node_id is used as the variable name
      - Any node that produces outputs (images, videos, audios, texts) will be included in results
      - images/images_by_var/videos/videos_by_var/audios/audios_by_var/texts/texts_by_var fields are only included if there are corresponding results
    """
    try:
        # Get request data
        data = await request.json()
        
        # Extract parameters
        workflow = data.get('workflow')
        params = data.get('params', {})
        wait_for_result = data.get('wait_for_result', True)
        timeout = data.get('timeout', None)
        prompt_ext_params = data.get('prompt_ext_params', {})

        # Support workflow as local path or URL
        if isinstance(workflow, dict):
            pass  # Use directly
        elif isinstance(workflow, str):
            if workflow.startswith('http://') or workflow.startswith('https://'):
                workflow = await _load_workflow_from_url(workflow)
            else:
                workflow = _load_workflow_from_local(workflow, request)
        else:
            return web.json_response({"error": "Invalid workflow parameter"}, status=400)
        
        if not workflow:
            return web.json_response({"error": "Workflow data is missing"}, status=400)
        
        # Convert UI format to API format if needed
        fmt = adjust_workflow_format(workflow)
        if fmt == 'invalid':
            return web.json_response({"error": "Invalid workflow format"}, status=400)
        if fmt == 'ui':
            return web.json_response({"error": "UI format workflow is not supported. Please convert to API format and try again."}, status=400)
        
        # Process workflow parameters
        if params:
            workflow = await _apply_params_to_workflow(workflow, params)
        
        # Extract and save output node information
        output_id_2_var = await _extract_output_nodes(workflow)
        
        # Generate client ID
        client_id = str(uuid.uuid4())
        
        # Submit workflow to ComfyUI queue
        try:
            prompt_id = await _queue_prompt(workflow, client_id, prompt_ext_params)
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
    
    Args:
        workflow: Workflow JSON object
        
    Returns:
        Dictionary mapping node_id to output variable name (only for nodes with explicit $output.name markers)
    
    Note:
        Any node that produces outputs will be included in results.
        Output fields (images, videos, texts, *_by_var) are only included in the response if there are corresponding results.
    """
    output_id_2_var = {}
    
    for node_id, node_data in workflow.items():
        # Skip nodes that don't meet criteria
        if not _is_valid_node(node_data):
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
        
        # Only register in output_id_2_var if there's an explicit output marker
        if output_var:
            output_id_2_var[node_id] = output_var
    
    return output_id_2_var

async def _process_param_marker(node_data, var_spec, params):
    """
    Process individual parameter marker
    
    Format: param_name.field_name
    - param_name: Parameter name, corresponding to key in params
    - field_name: Node input field name
    
    Special handling for media upload node types defined in MEDIA_UPLOAD_NODE_TYPES
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
    
    # Check if this node type requires special media upload handling
    node_class_type = node_data.get('class_type')
    if node_class_type in MEDIA_UPLOAD_NODE_TYPES:
        await _handle_media_upload(node_data, input_field, param_value)
    else:
        # Regular parameter setting
        await _set_node_param(node_data, input_field, param_value)

async def _handle_media_upload(node_data, input_field, param_value):
    """
    Handle media upload for nodes in MEDIA_UPLOAD_NODE_TYPES
    
    Args:
        node_data: Node data
        input_field: Input field name
        param_value: Parameter value
    """
    # Ensure inputs exists
    if "inputs" not in node_data:
        node_data["inputs"] = {}
    
    # If parameter value is a URL starting with http, upload the media first
    if isinstance(param_value, str) and param_value.startswith(('http://', 'https://')):
        try:
            # Upload media and get uploaded media name
            media_value = await _upload_media_from_source(param_value)
            # Use uploaded media name as node's input value
            await _set_node_param(node_data, input_field, media_value)
            print(f"Media uploaded: {media_value}")
        except Exception as e:
            print(f"Failed to upload media: {str(e)}")
            # Throw exception on upload failure
            raise Exception(f"Media upload failed: {str(e)}")
    else:
        # Use parameter value directly as media name
        await _set_node_param(node_data, input_field, param_value)

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

async def _upload_media_from_source(media_url) -> str:
    """
    Upload media from URL
    
    Args:
        media_url: Media URL
            
    Returns:
        Upload media file name
    """
    # Download media from URL
    async with aiohttp.ClientSession() as session:
        async with session.get(media_url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download media: HTTP {response.status}")
            
            # Extract filename from URL
            parsed_url = urlparse(media_url)
            filename = os.path.basename(parsed_url.path)
            if not filename:
                filename = f"temp_media_{hash(media_url)}.jpg"
            
            # Get media data
            media_data = await response.read()
            
            # Save to temporary file
            suffix = os.path.splitext(filename)[1] or ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(media_data)
                temp_path = tmp.name
    
    try:
        # Upload temporary file to ComfyUI
        return await _upload_media(temp_path)
    finally:
        # Delete temporary file
        os.unlink(temp_path)

async def _upload_media(media_path) -> str:
    """
    Upload media to ComfyUI
    
    Args:
        media_path: Media path
            
    Returns:
        Upload media file name
    """
    # Read media data
    with open(media_path, 'rb') as f:
        media_data = f.read()
    
    # Extract filename
    filename = os.path.basename(media_path)
    
    # Auto-detect file MIME type
    mime_type = mimetypes.guess_type(filename)[0]
    if mime_type is None:
        # Default to generic image type
        mime_type = 'application/octet-stream'
    
    # Prepare form data
    data = aiohttp.FormData()
    data.add_field('image', media_data, 
                   filename=filename, 
                   content_type=mime_type)
    
    # Upload media (internal ComfyUI API call still uses 127.0.0.1)
    async with aiohttp.ClientSession() as session:
        async with session.post("http://127.0.0.1:8188/upload/image", data=data) as response:
            if response.status != 200:
                raise Exception(f"Failed to upload media: HTTP {response.status}")
            
            # Get upload result
            result = await response.json()
            return result.get('name', '')

async def _queue_prompt(workflow, client_id, prompt_ext_params=None):
    """Submit workflow to queue using HTTP API"""
    prompt_data = {
        "prompt": workflow,
        "client_id": client_id
    }
    
    # Update prompt_data with all parameters from prompt_ext_params
    if prompt_ext_params:
        prompt_data.update(prompt_ext_params)
    
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
            print(f"Task submitted: {prompt_id}")
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

# Helper: map outputs by variable name
def _map_outputs_by_var(output_id_2_var, output_id_2_media):
    """
    Map outputs by variable name using output_id_2_var mapping.
    Args:
        output_id_2_var: Dict mapping node_id to variable name (for nodes with explicit markers)
        output_id_2_media: Dict mapping node_id to list of URLs/data
    Returns:
        Dict mapping variable name to list of URLs/data
    """
    result = {}
    for node_id, media_data in output_id_2_media.items():
        # Use explicit variable name if available, otherwise use node_id
        var_name = output_id_2_var.get(node_id, str(node_id))
        result[var_name] = media_data
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
    Split all media entries in node_output into images/videos/audios by file extension.
    Args:
        node_output: Output dict for a node
        base_url: Base URL for constructing file URLs
    Returns:
        (images: list, videos: list, audios: list) - lists of URLs
    """
    image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'}
    video_exts = {'.mp4', '.mov', '.avi', '.webm', '.gif'}
    audio_exts = {'.mp3', '.wav', '.flac', '.ogg', '.aac', '.m4a', '.wma', '.opus'}
    images = []
    videos = []
    audios = []
    for media_key in ("images", "gifs", "audio"):
        for media_data in node_output.get(media_key, []):
            if (isinstance(media_data, list) or isinstance(media_data, tuple)) and len(media_data) == 2:
                subfolder = ""
                filename, media_type = media_data
            elif isinstance(media_data, dict):
                filename = media_data.get("filename")
                subfolder = media_data.get("subfolder", "")
                media_type = media_data.get("type", "output")
            else:
                print(f"Invalid media data: {media_key} | {media_data}")
                continue
            
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
            elif ext in audio_exts:
                audios.append(url)
    return images, videos, audios

async def _wait_for_results(prompt_id, timeout=None, request=None, output_id_2_var=None):
    """Wait for workflow execution results, get history using HTTP API"""
    start_time = time.time()
    result = {
        "status": "processing",
        "prompt_id": prompt_id,
        "images": [],
        "images_by_var": {},
        "videos": [],
        "videos_by_var": {},
        "audios": [],
        "audios_by_var": {},
        "texts": [],
        "texts_by_var": {}
    }

    # Get base URL for image/video URLs
    base_url = await _get_base_url(request)

    while True:
        # Check timeout
        if timeout is not None and timeout > 0:
            duration = time.time() - start_time
            if duration > timeout:
                print(f"Timeout: {duration} seconds")
                result["duration"] = duration
                result["status"] = "timeout"
                return result

        # Get history using HTTP API
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:8188/history/{prompt_id}") as response:
                if response.status != 200:
                    await asyncio.sleep(1.0)
                    continue
                history_data = await response.json()
                if prompt_id not in history_data:
                    await asyncio.sleep(1.0)
                    continue
                
                prompt_history = history_data[prompt_id]
                status = prompt_history.get("status")
                if status and status.get("status_str") == "error":
                    result["status"] = "error"
                    messages = status.get("messages")
                    if messages:
                        errors = [
                            body.get("exception_message")
                            for type, body in messages
                            if type == "execution_error"
                        ]
                        error_message = "\n".join(errors)
                    else:
                        error_message = "Unknown error"
                    result["error"] = error_message
                    return result
                
                if "outputs" in prompt_history:
                    result["outputs"] = prompt_history["outputs"]
                    result["status"] = "completed"

                    # Collect all image, video, audio and text outputs by file extension
                    output_id_2_images = {}
                    output_id_2_videos = {}
                    output_id_2_audios = {}
                    output_id_2_texts = {}
                    for node_id, node_output in prompt_history["outputs"].items():
                        images, videos, audios = _split_media_by_suffix(node_output, base_url)
                        if images:
                            output_id_2_images[node_id] = images
                        if videos:
                            output_id_2_videos[node_id] = videos
                        if audios:
                            output_id_2_audios[node_id] = audios
                        # Collect text outputs
                        if "text" in node_output:
                            # Handle text field as string or list
                            texts = node_output["text"]
                            if isinstance(texts, str):
                                texts = [texts]
                            elif not isinstance(texts, list):
                                texts = [str(texts)]
                            output_id_2_texts[node_id] = texts

                    # Map by variable name if mapping is available
                    if output_id_2_images:
                        result["images_by_var"] = _map_outputs_by_var(output_id_2_var, output_id_2_images)
                        result["images"] = _extend_flat_list_from_dict(result["images_by_var"])

                    if output_id_2_videos:
                        result["videos_by_var"] = _map_outputs_by_var(output_id_2_var, output_id_2_videos)
                        result["videos"] = _extend_flat_list_from_dict(result["videos_by_var"])

                    if output_id_2_audios:
                        result["audios_by_var"] = _map_outputs_by_var(output_id_2_var, output_id_2_audios)
                        result["audios"] = _extend_flat_list_from_dict(result["audios_by_var"])

                    # Handle texts/texts_by_var
                    if output_id_2_texts:
                        result["texts_by_var"] = _map_outputs_by_var(output_id_2_var, output_id_2_texts)
                        result["texts"] = _extend_flat_list_from_dict(result["texts_by_var"])

                    # Remove empty fields for images/videos/audios/texts
                    if not result.get("images"):
                        result.pop("images", None)
                    if not result.get("images_by_var"):
                        result.pop("images_by_var", None)
                    if not result.get("videos"):
                        result.pop("videos", None)
                    if not result.get("videos_by_var"):
                        result.pop("videos_by_var", None)
                    if not result.get("audios"):
                        result.pop("audios", None)
                    if not result.get("audios_by_var"):
                        result.pop("audios_by_var", None)
                    if not result.get("texts"):
                        result.pop("texts", None)
                    if not result.get("texts_by_var"):
                        result.pop("texts_by_var", None)

                    return result
        await asyncio.sleep(1.0)

# New: Load workflow from local file
def _load_workflow_from_local(filename, request=None):
    """
    Load workflow JSON from user's workflow directory
    """
    if not request or not prompt_server.user_manager:
        raise Exception("User context is required to load workflow from user directory")
    
    name_with_json = filename if filename.endswith('.json') else f'{filename}.json'
    relative_path = f'{API_WORKFLOWS_DIR}/{name_with_json}'
    api_workflow_path = prompt_server.user_manager.get_request_user_filepath(request, relative_path, create_dir=False)
    
    if not api_workflow_path or not os.path.isfile(api_workflow_path):
        raise Exception(f"Workflow file not found in user directory: {filename}")
    
    with open(api_workflow_path, 'r', encoding='utf-8') as f:
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