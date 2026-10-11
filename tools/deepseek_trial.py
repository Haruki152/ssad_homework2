"""最多两次模型请求、总输出上限1000 token的真实小规模协同实验。"""
from pathlib import Path
from types import SimpleNamespace
import ast
import hashlib
import json
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orchestrator import call_agent, checked_run, parse_files, write_files

CONTRACT = '''Implement can_transition(src: str, dst: str) -> bool for the RMS.
Known states: draft, reviewing, approved, implemented, verified, deprecated.
Allow same-state updates, forward draft->reviewing->approved->implemented->verified,
and any known state->deprecated. Reject all other or unknown states.
Pure Python, no imports, no I/O, no classes. Module only constants and functions.
Return JSON {"files":{"state_policy.py":"complete Python source"}}.'''

def validate_source(source):
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.Expr)):
            raise ValueError('不允许的模块结构')
        if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            raise ValueError('模块顶层不允许执行调用')
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Global, ast.Nonlocal)):
            raise ValueError('不允许导入或外部状态')
        if isinstance(node, ast.Attribute) and node.attr != 'get':
            raise ValueError('只允许字典get属性访问')
        if isinstance(node, ast.Name) and node.id.startswith('__'):
            raise ValueError('不允许特殊名称')
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id not in {'set', 'dict', 'isinstance', 'str', 'can_transition'}:
                raise ValueError('不允许的函数调用')
    if not any(isinstance(n, ast.FunctionDef) and n.name == 'can_transition' for n in tree.body):
        raise ValueError('缺少can_transition')
    namespace = {'__builtins__': {'set': set, 'dict': dict, 'isinstance': isinstance, 'str': str, 'bool': bool}}
    exec(compile(tree, 'state_policy.py', 'exec'), namespace)
    return namespace['can_transition']

def main():
    if not os.environ.get('DEEPSEEK_API_KEY'):
        raise ValueError('请在本机设置DEEPSEEK_API_KEY')
    os.environ['RMS_PROVIDER'] = 'deepseek'
    model = os.environ.get('RMS_MODEL', 'deepseek-flash')
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', type=Path, help='复用未完成运行中已保存的生成响应，不重复调用')
    args = parser.parse_args()
    run = checked_run(args.resume)
    (run/'artifacts').mkdir(exist_ok=True)
    (run/'agents').mkdir(exist_ok=True)
    prior_calls=[]
    for path in sorted((run/'logs').glob('*.json')) if (run/'logs').exists() else []:
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('kind')=='model_call': prior_calls.append(data)
    if len(prior_calls)>1:
        raise ValueError('本运行已有两次请求，禁止继续付费调用')
    if args.resume and (run/'artifacts/summary.json').exists():
        (run/'artifacts/first-attempt-summary.json').write_text((run/'artifacts/summary.json').read_text(encoding='utf-8'),encoding='utf-8')
    (run/'artifacts/contract.md').write_text(CONTRACT, encoding='utf-8')
    generators = {
        'backend': 'You implement a small pure-Python module strictly following the frozen contract. Output only the requested JSON; keep code concise.',
        'critic': 'You independently review code and actual test evidence against the contract. Do not invent defects. Return only JSON with keys verdict (pass/fail), findings (array of objects with location, issue, cause), limitation (string). Be concise.',
    }
    for name, prompt in generators.items():
        (run/'agents'/f'{name}.md').write_text(prompt, encoding='utf-8')
    old_cap = os.environ.get('RMS_MAX_TOKENS')
    summary = {'date': datetime.now(timezone(timedelta(hours=8))).isoformat(),
               'provider': 'deepseek', 'requested_family': 'v4-flash', 'api_model': model,
               'scope': '真实Backend→本地检查→Critic小模块实验；未运行完整v1/v2/v3生成流水线',
               'thinking': 'disabled', 'output_caps': {'backend': 700, 'critic': 300},
               'automatic_retries': 0}
    try:
        os.environ['RMS_MAX_TOKENS'] = '700'
        agent = SimpleNamespace(name='backend', model=model, system_prompt=generators['backend'])
        if prior_calls:
            if prior_calls[0]['agent']!='backend': raise ValueError('恢复来源不是backend')
            output=prior_calls[0]['output']
            summary['resumed_from_saved_response']=True
        else:
            output = call_agent(agent, 'Implement the contract as JSON. No tests in the file.', CONTRACT, run)
        files = parse_files(output, {'state_policy.py'})
        function = validate_source(files['state_policy.py'])
        write_files(run/'generated', files)
        states = ['draft','reviewing','approved','implemented','verified','deprecated']
        next_state = dict(zip(states[:4], states[1:5]))
        failures=[]
        cases=[]
        for src in states+['unknown']:
            for dst in states+['unknown']:
                expected = src in states and dst in states and (src==dst or dst=='deprecated' or next_state.get(src)==dst)
                actual = function(src,dst)
                case={'src':src,'dst':dst,'expected':expected,'actual':actual}
                cases.append(case)
                if type(actual) is not bool or actual != expected: failures.append(case)
        tests={'total':len(cases),'passed':len(cases)-len(failures),'failures':failures,'cases':cases}
        (run/'artifacts/test-results.json').write_text(json.dumps(tests,ensure_ascii=False,indent=2),encoding='utf-8')
        os.environ['RMS_MAX_TOKENS'] = '300'
        critic = SimpleNamespace(name='critic',model=model,system_prompt=generators['critic'])
        task='Review the actual generated code and local exhaustive tests.\nCODE:\n'+files['state_policy.py']+'\nTEST EVIDENCE:\n'+json.dumps({'total':tests['total'],'passed':tests['passed'],'failures':failures})
        review=call_agent(critic,task,CONTRACT,run)
        (run/'artifacts/critic-response.txt').write_text(review,encoding='utf-8')
        clean=review.strip()
        if clean.startswith('```'): clean=clean.split('\n',1)[1].rsplit('```',1)[0].strip()
        parsed=json.loads(clean)
        if not isinstance(parsed,dict) or parsed.get('verdict') not in {'pass','fail'} or not isinstance(parsed.get('findings'),list):
            raise ValueError('评审输出格式错误；保留真实响应，不重试')
        (run/'artifacts/critic-review.json').write_text(json.dumps(parsed,ensure_ascii=False,indent=2),encoding='utf-8')
        summary.update({'test_total':tests['total'],'test_passed':tests['passed'],'critic_verdict':parsed['verdict'],
                        'source_sha256':hashlib.sha256(files['state_policy.py'].encode()).hexdigest(),
                        'completed':True})
    except Exception as exc:
        summary.update({'completed':False,'error_type':type(exc).__name__})
        raise
    finally:
        if old_cap is None: os.environ.pop('RMS_MAX_TOKENS',None)
        else: os.environ['RMS_MAX_TOKENS']=old_cap
        calls=[]
        for path in sorted((run/'logs').glob('*.json')):
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('kind')=='model_call':
                calls.append({'agent':data['agent'],'actual_model':data['actual_model'],'usage':data['usage'],'elapsed_seconds':data['elapsed_seconds']})
        summary['calls']=calls
        summary['total_tokens']=sum(c['usage'].get('total_tokens',0) for c in calls)
        summary['prompt_tokens']=sum(c['usage'].get('prompt_tokens',0) for c in calls)
        summary['completion_tokens']=sum(c['usage'].get('completion_tokens',0) for c in calls)
        (run/'artifacts/summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'run_dir':str(run),**summary},ensure_ascii=False),flush=True)

if __name__ == '__main__':
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    main()
