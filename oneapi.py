import os
import json
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

# Get routes
routes = PromptServer.instance.routes

@routes.post('/oneapi/v1/execute')
async def execute_workflow(request):
    """
    Execute workflow API
    
    Parameters:
    - workflow: Workflow JSON
    - params: Parameter mapping dictionary
    - wait_for_result: Whether to wait for results (default True)
    - timeout: Timeout in seconds (default 300)
    
    Returns:
    - Return values:
        - status: Status (queued, processing, completed, timeout)
        - prompt_id: Prompt ID
        - images: List of image URLs [string, ...]
        - images_by_var: Mapped image URLs by variable name {var_name: [string, ...], ...}
    
    Node title markers:
    - Input: Use "$param.field" in node title to map parameter values
    - Output: Use "$output" or "$output.name" in SaveImage node title to specify outputs
      - "$output.name" - Marks a SaveImage node with a custom output name (added to "images_by_var[name]")
      - If no explicit output marker is set, the node_id is used as the variable name
      - Only SaveImage nodes are considered for output
      - Both images and images_by_var fields are always included in the response
    """
    try:
        # Get request data
        data = await request.json()
        
        # Extract parameters
        workflow = data.get('workflow')
        params = data.get('params', {})
        wait_for_result = data.get('wait_for_result', True)
        timeout = data.get('timeout', None)
        
        if not workflow:
            return web.json_response({"error": "Workflow data is missing"}, status=400)
        
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
        print(f"Error executing workflow: {str(e)}")
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
    Extract SaveImage nodes and their output variable names from workflow
    
    Args:
        workflow: Workflow JSON object
        
    Returns:
        Dictionary mapping node_id to output variable name
    """
    output_id_2_var = {}
    
    for node_id, node_data in workflow.items():
        # Skip nodes that don't meet criteria
        if not _is_valid_node(node_data):
            continue
        
        # Only process SaveImage nodes
        if node_data.get('class_type') != 'SaveImage':
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
        
        # For SaveImage nodes, always register in output_id_2_var
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

async def _wait_for_results(prompt_id, timeout=None, request=None, output_id_2_var=None):
    """Wait for workflow execution results, get history using HTTP API"""
    start_time = time.time()
    result = {
        "status": "processing",
        "prompt_id": prompt_id,
        "images": [],
        "images_by_var": {}
    }
    
    # Get base URL for image URLs
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
                        # API call failed, retry after waiting
                        await asyncio.sleep(1.0)
                        continue
                    
                    # Get entire history
                    history_data = await response.json()
                    
                    # Check if specified prompt_id is in history
                    if prompt_id not in history_data:
                        # Workflow might not be completed yet, retry after waiting
                        await asyncio.sleep(1.0)
                        continue
                    
                    # Get history for specific prompt_id
                    prompt_history = history_data[prompt_id]
                    
                    # Check if completed
                    if "outputs" in prompt_history:
                        result["status"] = "completed"
                        
                        # Store all SaveImage node outputs
                        output_id_2_images = {}
                        
                        # Process outputs, focusing on nodes with images
                        for node_id, node_output in prompt_history["outputs"].items():
                            if "images" in node_output:
                                # Store image URLs for this node
                                node_images = []
                                for img_data in node_output["images"]:
                                    filename = img_data.get("filename")
                                    subfolder = img_data.get("subfolder", "")
                                    img_type = img_data.get("type", "output")
                                    
                                    # Build image URL
                                    img_url = f"{base_url}/view?filename={filename}"
                                    if subfolder:
                                        img_url += f"&subfolder={subfolder}"
                                    if img_type:
                                        img_url += f"&type={img_type}"
                                    
                                    node_images.append(img_url)
                                
                                output_id_2_images[node_id] = node_images
                        
                        # Process according to output mapping
                        if output_id_2_var and output_id_2_images:
                            # First pass: handle nodes with explicit mapping
                            for node_id, output_var in output_id_2_var.items():
                                if node_id in output_id_2_images:
                                    # Add to images_by_var using the variable name
                                    result["images_by_var"][output_var] = output_id_2_images[node_id]
                            
                            # For backward compatibility: add all output images to the images array as well
                            for images in output_id_2_images.values():
                                result["images"].extend(images)
                        else:
                            # No mapping or no image outputs, fallback to including all images in the images array
                            for node_images in output_id_2_images.values():
                                result["images"].extend(node_images)
                        
                        # Return complete results
                        return result
        except Exception as e:
            print(f"Error getting history: {str(e)}")
            # Continue trying after error
            
        # Wait before checking again
        await asyncio.sleep(1.0)

print("ComfyUI-OneAPI routes registered") 