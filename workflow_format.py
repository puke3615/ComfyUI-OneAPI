from typing import Literal

def adjust_workflow_format(workflow: dict) -> Literal['ui', 'api', 'invalid']:
    """
    Determine if workflow is UI or API format.
    Args:
        workflow (dict): workflow object
    Returns:
        Literal['ui', 'api', 'invalid']: 'ui' if UI format, 'api' if API format, 'invalid' if neither
    """
    if isinstance(workflow, dict):
        if 'nodes' in workflow and isinstance(workflow['nodes'], list):
            return 'ui'
        # Heuristic: API format top-level keys are all digit strings
        if all(isinstance(k, str) and k.isdigit() for k in workflow.keys()) and len(workflow) > 0:
            return 'api'
    return 'invalid' 