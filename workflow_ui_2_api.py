import json
import sys
import asyncio
import aiohttp
from typing import Literal

async def get_object_info(base_url):
    """
    Fetch object_info from ComfyUI server.
    Args:
        base_url (str): ComfyUI server base url
    Returns:
        dict: object_info json
    """
    url = base_url.rstrip('/') + '/api/object_info'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch object_info: {resp.status}")
            return await resp.json()

def adjust_workflow_format(workflow: dict) -> Literal['ui', 'api', 'invalid']:
    """
    Determine if workflow is UI or API format.
    Args:
        workflow (dict): workflow object
    Returns:
        Literal['ui', 'api', 'invalid']: 'ui' if UI format, 'api' if API format, 'invalid' if neither
    """
    if not isinstance(workflow, dict):
        return 'invalid'
    if 'nodes' in workflow and isinstance(workflow['nodes'], list):
        return 'ui'
    # Heuristic: API format top-level keys are all digit strings
    if all(isinstance(k, str) and k.isdigit() for k in workflow.keys()) and len(workflow) > 0:
        return 'api'
    return 'invalid'

async def convert_ui_to_api(ui_json, base_url='http://127.0.0.1:8188'):
    """
    Convert ComfyUI UI workflow format to API workflow format using live object_info.
    Args:
        ui_json (dict): UI format workflow JSON
        base_url (str): ComfyUI server base url
    Returns:
        dict: API format workflow JSON
    """
    object_info = await get_object_info(base_url)
    api = {}
    node_id_map = {}
    for node in ui_json.get('nodes', []):
        node_id_map[node['id']] = str(node['id'])
    for node in ui_json.get('nodes', []):
        node_id = str(node['id'])
        node_type = node['type']
        title = node.get('title')
        if not title:
            title = node.get('properties', {}).get('Node name for S&R', node_type)
        meta = {"title": title}
        inputs = {}
        widgets = node.get('widgets_values', [])
        # 1. Process all links and write to inputs
        for inp in node.get('inputs', []):
            # Check if this input has an actual link (not null)
            if inp.get('link') is not None:
                link_id = inp['link']
                for link in ui_json.get('links', []):
                    if link[0] == link_id:
                        from_node = str(link[1])
                        from_slot = link[2]
                        inputs[inp['name']] = [from_node, from_slot]
                        break
        # 2. Find all fields covered by links (those with non-null link values)
        linked_fields = set(inp['name'] for inp in node.get('inputs', []) if inp.get('link') is not None)
        node_info = object_info.get(node_type, {})
        input_order = node_info.get('input_order', {}).get('required', [])
        input_required = node_info.get('input', {}).get('required', {})
        # 3. Assign widgets_values to fields not covered by links
        widget_idx = 0
        
        for field in input_order:
            if field in linked_fields:
                # Skip fields that have links
                continue
            
            # Check if we have more widget values to process
            if widget_idx >= len(widgets):
                break
                
            value = widgets[widget_idx]
            
            # Check if this field has control_after_generate property
            field_info = input_required.get(field)
            has_control_after_generate = False
            if isinstance(field_info, list) and len(field_info) > 1:
                meta_info = field_info[1]
                if isinstance(meta_info, dict) and meta_info.get('control_after_generate'):
                    has_control_after_generate = True
            
            # Assign the widget value to the current field
            inputs[field] = value
            widget_idx += 1
            
            # Special handling: if this field has control_after_generate, check if next value is a control value
            # Fields with control_after_generate (like seed) may have control values (like "randomize") 
            # following their actual value in widgets_values
            if has_control_after_generate and widget_idx < len(widgets):
                next_value = widgets[widget_idx]
                control_values = {"randomize", "increment", "decrement", "fixed"}
                if next_value in control_values:
                    widget_idx += 1
        # 4. Fill default values for missing required fields
        for field in input_order:
            if field not in inputs:
                field_info = input_required.get(field)
                if isinstance(field_info, list) and len(field_info) > 1:
                    meta_info = field_info[1]
                    if isinstance(meta_info, dict) and 'default' in meta_info:
                        inputs[field] = meta_info['default']
        api[node_id] = {
            'inputs': inputs,
            'class_type': node_type,
            '_meta': meta
        }
    return api

async def main():
    """
    Main entry for CLI usage. Usage: python workflow_ui_2_api.py [base_url]
    Converts test/ui.json to test/ui_to_api.json using live object_info.
    """
    base_url = 'http://127.0.0.1:8188'
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    ui_path = 'test/ui.json'
    api_path = 'test/ui_to_api.json'
    with open(ui_path, 'r', encoding='utf-8') as f:
        ui_json = json.load(f)
    api_json = await convert_ui_to_api(ui_json, base_url)
    with open(api_path, 'w', encoding='utf-8') as f:
        json.dump(api_json, f, indent=2, ensure_ascii=False)
    print(f"Converted {ui_path} to {api_path} using {base_url}/api/object_info")

if __name__ == '__main__':
    asyncio.run(main()) 