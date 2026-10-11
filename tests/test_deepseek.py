import json
import urllib.error
from types import SimpleNamespace
import pytest
import deepseek_client
import orchestrator

def test_deepseek_request_is_nonthinking_and_capped(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','fake-secret')
    captured={}
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self): return b'{"choices": [], "usage": {}}'
    def open_request(req,timeout):
        captured['request']=req
        return Response()
    monkeypatch.setattr(deepseek_client.urllib.request,'urlopen',open_request)
    payload,result=deepseek_client.chat('deepseek-flash','system','task',700)
    assert payload['thinking']=={'type':'disabled'} and payload['max_tokens']==700
    assert 'fake-secret' not in json.dumps(payload)
    assert captured['request'].full_url=='https://api.deepseek.com/chat/completions'

def test_deepseek_http_failure_not_retried(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','fake-secret')
    attempts=[]
    def fail(req,timeout):
        attempts.append(req)
        raise urllib.error.HTTPError(req.full_url,401,'failure',{},None)
    monkeypatch.setattr(deepseek_client.urllib.request,'urlopen',fail)
    with pytest.raises(RuntimeError,match='HTTP 401'):
        deepseek_client.chat('deepseek-flash','system','task',300)
    assert len(attempts)==1

def test_orchestrator_deepseek_logs_real_usage(monkeypatch,tmp_path):
    monkeypatch.setenv('RMS_PROVIDER','deepseek')
    monkeypatch.setenv('RMS_MAX_TOKENS','300')
    def fake_chat(model,system,task,cap):
        assert cap==300
        return {'model':model,'messages':[]}, {'model':'actual-flash','choices':[{'finish_reason':'stop','message':{'content':'done'}}], 'usage':{'total_tokens':15}}
    monkeypatch.setattr(deepseek_client,'chat',fake_chat)
    agent=SimpleNamespace(name='critic',model='deepseek-flash',system_prompt='review')
    assert orchestrator.call_agent(agent,'task','contract',tmp_path)=='done'
    data=json.loads(next((tmp_path/'logs').glob('*.json')).read_text(encoding='utf-8'))
    assert data['provider']=='deepseek' and data['actual_model']=='actual-flash'
    assert data['usage']['total_tokens']==15
