# 编排角色说明（修复版）

此角色由 orchestrator.py 的确定性 Python 流程承担，不额外调用 LLM。

流程：Architect 冻结契约 → Data 输出 ORM → Backend 消费实际 ORM → 启动/接口门禁 → 行为诊断 → Critic → 约束 → Refactor(v2) → 完整门禁 → Refactor(v3) → 完整门禁。

首轮行为失败是诊断输入，不宣称通过。v2/v3 门禁失败反馈给 Refactor，达到重试上限仍失败就停止。

产物按文件名 JSON 解析，运行写入 runs/独立目录；原修复版代码不被覆盖。每次厂商请求与真实检查输出写入该次运行的 logs/，失败轮代码保存在 attempts/。

本次只完成离线编排逻辑测试，没有真实 API 调度运行。角色数量不能作为多智能体更优的证据，比较必须基于真实实验。
