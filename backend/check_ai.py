"""One synthetic-only provider connectivity check; never prints credentials."""
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parent))
from app.agent_workflow import GeminiPlanner

if __name__=='__main__':
    source=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('.env')
    values=dotenv_values(source)
    for name in ('GEMINI_API_KEY','GEMINI_MODEL'):
        if values.get(name):os.environ[name]=values[name]
    try:
        planner=GeminiPlanner()
        action=planner.choose({'test':'Synthetic connectivity check; no user documents supplied.','questions':[], 'profile':{},'tool_results':[]})
        result={'status':'CONNECTED','model':planner.model,'tool_action':action.tool}
    except httpx.HTTPStatusError as exc:
        result={'status':'PROVIDER_REJECTED','http_status':exc.response.status_code,'model':os.getenv('GEMINI_MODEL','')}
    except Exception as exc:
        result={'status':'UNAVAILABLE','error_type':type(exc).__name__}
    print(json.dumps(result))
