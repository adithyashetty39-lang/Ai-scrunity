"""Synthetic-only local connectivity check, without user examination content."""
import json
import os
from app.agent_workflow import LocalPlanner

os.environ['SCRUTINY_LOCAL_MODEL']='qwen3.5:4b'
try:
    planner=LocalPlanner()
    action=planner.choose({'test':'No syllabus or questions have been supplied. Request professor review; do not infer a pass.','profile':{},'questions':[],'tool_results':[]})
    print(json.dumps({'status':'CONNECTED','model':planner.model,'tool_action':action.tool}))
except Exception as exc:
    print(json.dumps({'status':'UNAVAILABLE','error_type':type(exc).__name__}))
