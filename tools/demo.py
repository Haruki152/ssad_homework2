from pathlib import Path
import json, subprocess, os, time, urllib.request, urllib.error, socket
from datetime import datetime
import sys
ROOT = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
record={'scope':'真实本地HTTP演示；不调用LLM API'}
scratch=ROOT/'test-work'/'live-demo'
scratch.mkdir(parents=True,exist_ok=True)
db=scratch/('demo-'+datetime.now().strftime('%H%M%S')+'.db')
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'
env={**os.environ,'RMS_DATABASE_URL':'sqlite:///'+db.as_posix(),'PYTHONIOENCODING':'utf-8'}
steps=[]
def request(method,path,body=None,expected=200):
    data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    req=urllib.request.Request(base+path,data=data,method=method,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=5) as response: code=response.status; text=response.read().decode()
    except urllib.error.HTTPError as error: code=error.code; text=error.read().decode()
    assert code==expected,(method,path,code,text)
    content=json.loads(text) if text else None
    steps.append({'method':method,'path':path,'body':body,'status':code,'response':content})
    return content
def start():
    process=subprocess.Popen([str(PY),'-m','uvicorn','v3.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(100):
        if process.poll() is not None: raise RuntimeError('uvicorn启动失败')
        try:
            with urllib.request.urlopen(base+'/openapi.json',timeout=1) as response:
                if response.status==200: return process
        except (OSError,urllib.error.URLError): time.sleep(.1)
    process.terminate(); process.wait(); raise RuntimeError('启动超时')
server=None
try:
    server=start()
    with urllib.request.urlopen(base+'/docs') as response: assert response.status==200
    project=request('POST','/projects',{'name':'课程演示'})['project_id']
    requirement_type=request('POST','/item-types',{'project_id':project,'name':'系统需求'})['item_type_id']
    test_type=request('POST','/item-types',{'project_id':project,'name':'测试用例'})['item_type_id']
    request('POST',f'/item-types/{requirement_type}/attributes',{'name':'验收度量','data_type':'text','required':True})
    request('POST',f'/item-types/{test_type}/attributes',{'name':'测试步骤','data_type':'text','required':True})
    request('POST','/items',{'project_id':project,'item_type_id':requirement_type,'title':'错误需求','custom_attrs':{}},400)
    first=request('POST','/items',{'project_id':project,'item_type_id':requirement_type,'title':'订单查询','custom_attrs':{'验收度量':'响应时间小于3秒'}})['item_id']
    second=request('POST','/items',{'project_id':project,'item_type_id':test_type,'title':'订单查询性能测试','custom_attrs':{'测试步骤':'发起查询并记录响应时间'}})['item_id']
    link=request('POST','/relationships',{'from_item_id':first,'to_item_id':second,'link_type':'verifies'})['rel_id']
    request('PUT',f'/items/{first}',{'status':'verified'},400)
    request('PUT',f'/items/{first}',{'status':'reviewing'})
    request('PUT',f'/items/{first}',{'title':'订单查询修订'})
    assert request('GET',f'/items/{second}/trace')['upstream'][0]['suspect']
    request('POST',f'/relationships/{link}/clear-suspect')
    assert not request('GET',f'/items/{second}/trace')['upstream'][0]['suspect']
    server.terminate(); server.wait(timeout=10); server=None
    server=start()
    assert request('GET',f'/items/{first}')['title']=='订单查询修订'
    assert request('GET',f'/items/{second}/trace')['upstream'][0]['rel_id']==link
    record['live_http']={'passed':True,'server':'uvicorn','database':'独立演示数据库，不改用户数据','swagger':True,'restart_persistence':True,'steps':steps}
finally:
    if server: server.terminate(); server.wait(timeout=10)
(ROOT/'artifacts/demo-verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('真实HTTP、不同条目类型、错误拒绝、可疑复核、重启持久化通过。',flush=True)
