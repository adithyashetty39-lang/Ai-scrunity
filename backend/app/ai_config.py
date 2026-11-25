"""Server-only provider configuration and destination-scoped sharing permission."""
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
from urllib.parse import urlsplit


class ModelUnavailable(Exception):
    pass


class ConsentRequired(ModelUnavailable):
    pass


LABELS={'gemini':'Google Gemini','openai':'OpenAI','anthropic':'Anthropic Claude',
        'openai_compatible':'OpenAI-compatible service','local':'Local Ollama'}
BASES={'gemini':'https://generativelanguage.googleapis.com/v1beta','openai':'https://api.openai.com/v1',
       'anthropic':'https://api.anthropic.com/v1'}


def configured_provider():
    value=os.getenv('SCRUTINY_AI_PROVIDER','none').strip().lower()
    return 'gemini' if value=='google' else value


@dataclass(frozen=True)
class ProviderConfig:
    provider:str
    model:str
    base_url:str
    key:str=field(default='',repr=False)
    vision:bool=False
    json_mode:str='json'
    max_images:int=10

    @property
    def id(self):
        # Rotating a key preserves consent; changing destination/model does not.
        identity=[self.provider,self.model,self.base_url,self.vision,self.json_mode,self.max_images]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]

    def public(self):
        return {'provider':self.provider,'label':LABELS[self.provider],'model':self.model,
                'destination':urlsplit(self.base_url).netloc,'id':self.id,'vision':self.vision,
                'max_images':self.max_images,'configured':bool(self.model and (self.key or self.provider=='local'))}


def get_config(mode='cloud'):
    selected=configured_provider()
    provider='local' if mode=='local' else selected
    if mode=='google' and selected!='gemini':
        raise ConsentRequired('The cloud provider changed. Select the configured cloud service and confirm sharing with that destination.')
    if provider not in LABELS:
        raise ModelUnavailable('AI is disabled or its provider is unsupported. Configure SCRUTINY_AI_PROVIDER in backend/.env.')
    if provider=='local':
        model=os.getenv('SCRUTINY_LOCAL_MODEL','qwen3.5:4b').strip()
        base=os.getenv('SCRUTINY_LOCAL_MODEL_URL','http://127.0.0.1:11434').strip().rstrip('/')
        key='';vision=True
    else:
        legacy={'gemini':'GEMINI','openai':'OPENAI','anthropic':'ANTHROPIC'}.get(provider,'')
        model=os.getenv('SCRUTINY_AI_MODEL','').strip() or os.getenv(legacy+'_MODEL','').strip()
        key=os.getenv('SCRUTINY_AI_KEY','').strip() or os.getenv(legacy+'_API_KEY','').strip()
        base=(os.getenv('SCRUTINY_AI_BASE_URL','').strip() if provider=='openai_compatible' else BASES[provider]).rstrip('/')
        flag=os.getenv('SCRUTINY_AI_VISION','false' if provider=='openai_compatible' else 'true').strip().lower()
        if flag not in ('true','false'):raise ModelUnavailable('SCRUTINY_AI_VISION must be true or false.')
        vision=flag=='true'
    try:url=urlsplit(base);host=url.hostname;url.port
    except ValueError:raise ModelUnavailable('The configured API base URL is invalid.') from None
    if not host or url.username or url.password or url.query or url.fragment:
        raise ModelUnavailable('Configure a base API URL without credentials, query strings, or fragments.')
    if provider=='local':
        if url.scheme!='http' or host not in ('localhost','127.0.0.1','::1'):
            raise ModelUnavailable('The local Ollama endpoint must use HTTP on this computer (loopback).')
    elif url.scheme!='https':raise ModelUnavailable('Cloud API endpoints must use HTTPS.')
    if model and not re.fullmatch(r'[A-Za-z0-9._:/-]+',model):raise ModelUnavailable('The AI model ID contains unsupported characters.')
    if '\n' in key or '\r' in key:raise ModelUnavailable('The API key contains an invalid line break.')
    json_mode=os.getenv('SCRUTINY_AI_JSON_MODE','schema' if provider=='openai' else 'json').strip().lower()
    if json_mode not in ('schema','json','prompt'):raise ModelUnavailable('SCRUTINY_AI_JSON_MODE must be schema, json, or prompt.')
    try:max_images=int(os.getenv('SCRUTINY_AI_MAX_IMAGES','10'))
    except ValueError:raise ModelUnavailable('SCRUTINY_AI_MAX_IMAGES must be an integer from 1 to 10.') from None
    if not 1<=max_images<=10:raise ModelUnavailable('SCRUTINY_AI_MAX_IMAGES must be an integer from 1 to 10.')
    return ProviderConfig(provider,model,base,key,vision,json_mode,max_images)


def public_config():
    try:
        config=get_config()
        if config.provider=='local':return {'cloud':None,'error':'Configure a cloud provider in backend/.env to enable cloud processing.'}
        return {'cloud':config.public(),'error':None}
    except ModelUnavailable as exc:return {'cloud':None,'error':str(exc)}


def authorize(mode,consent=False,provider_id=None):
    if mode not in ('local','google','cloud'):raise ModelUnavailable('Choose local or configured cloud processing.')
    if mode!='local' and not consent:
        raise ConsentRequired('Confirm permission to send this paper and syllabus/notes to the selected cloud service, or select local processing.')
    config=get_config(mode)
    if mode=='cloud' and config.provider=='local':raise ModelUnavailable('No cloud provider is configured.')
    if mode=='cloud' and provider_id!=config.id:
        raise ConsentRequired('The provider or model changed. Refresh the page and confirm sharing with the currently configured destination.')
    return config
