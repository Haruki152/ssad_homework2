"""DeepSeek官方Chat API：环境变量认证、单次请求、无自动重试。"""
import json
import os
import urllib.request
import urllib.error

def chat(model, system, task, max_tokens, json_output=False):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("请在本机配置 DEEPSEEK_API_KEY")
    if not 1 <= max_tokens <= 16000:
        raise ValueError("max_tokens必须为1至16000")
    payload = {
        "model": model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ],
        "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # 不保存或打印认证头及厂商错误正文。
        raise RuntimeError(f"DeepSeek HTTP {exc.code}；未重试") from None
    return payload, result
