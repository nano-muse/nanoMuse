# 目标评测任务

十条中文任务在隔离的合成环境中测试费用汇总、车票筛选、会议简报、日历和文件归档。
任务使用运行时的目标评估器，独立观察最终状态和回答。

## 离线回放

CI 运行 `pytest -q -m "not live"`。任务测试在禁止联网的条件下回放录制的模型回答。
当前回放数据是 2026 年 11 月 1 日用 `deepseek-flash` 录制的，只包含回答和已报告的用量，
不含模型输入或推理内容。Agent 循环变化后可能需要更新回放数据，回答次数必须完全匹配。

## 使用自己的模型

按照[配置说明](configuration.md)设置服务商、模型和密钥，然后运行：

```sh
NANOMUSE_LIVE=1 NANOMUSE_GOAL_EVAL_OUTPUT=./goal-eval-output \
  python -m pytest -q -m live tests/test_goal_eval_tasks.py
```

测试使用配置的模型，关闭重试，每例限制为 50000 token 和 120 秒，服务商可能收费。
不设置输出变量时，文件写入 pytest 临时目录。`report.json` 包含判定和可用的用量，
`recording.json` 包含回答。用新回放数据替换 `tests/fixtures/goal_eval/tasks_v1_recording.json`
前，检查其中是否有个人数据和密钥；替换后重跑离线测试，检查变化的判据结果。

verified 表示该案例的固定判据与观察值匹配。partial、unknown 和 contradicted 只描述
这些判据，不能代表模型的整体能力。规则可能漏掉同义改写或误读文本，十条任务也不能
衡量其他任务的表现。live 测试只检查运行器完成，不要求模型任务成功。

`tasks_v1.json` 中的预期结论对应当前提交的模型回答。更新回放数据后，须人工逐条
核对变化的结论，再更新预期值。
