import os
import sys
import importlib.util

# Make sure oneapi.py can be properly loaded
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import oneapi module, register routes
def init_oneapi():
    try:
        spec = importlib.util.spec_from_file_location("oneapi", os.path.join(current_dir, "oneapi.py"))
        oneapi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(oneapi)
        print("ComfyUI-OneAPI loaded")
    except Exception as e:
        print(f"ComfyUI-OneAPI failed to load: {str(e)}")

# This function will be automatically called when ComfyUI loads the plugin
WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# Initialize API
init_oneapi() 