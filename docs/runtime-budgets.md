# Runtime task budgets

These settings apply to the Python runtime used by the web app and the Python hands
operator. Android's native agent and the desktop's DeepSeek Harness chat loop have
their own execution engines; these settings do not change those engines.

## Configure a task

Add this to `config/config.toml`. Limits default to zero, which leaves them disabled.
The numbers here are example limits, not model pricing.

```toml
[agent]
max_context_tokens = 32768

[agent.budget]
max_total_tokens = 200000
max_seconds = 600
max_cost_usd = 0
input_usd_per_million = 0
output_usd_per_million = 0
```

`max_context_tokens` caps an approximate token count of the main Agent's input request, including the
system prompt, tool schemas, reasoning history and pictures. It is separate from the
model's output limit, `llm.max_tokens`. Text uses one estimated token per four UTF-8
bytes, rounded up, including JSON overhead; each image adds 4,096 estimated tokens.
The settings are in tokens, not bytes. This portable heuristic is not an exact
tokenizer, can differ by model and language, and does not guarantee a vision model's
context window. Provider-reported usage replaces the estimate after a completed call.
Choose a context limit that leaves room for the configured output.

When a request is too large, copies of tool results keep a labelled head and tail,
then old exchanges are removed as complete groups. Current-task user requests and
system instructions are retained intact, as are tool-call arguments. A request that
still cannot fit stops with a context-budget explanation before contacting the model.
The stored conversation keeps the original text. Each tool-result shortening writes
an INFO log line with the call id and before/after character counts, without any of
the tool output, so a missing detail can be traced in the runtime log.

`max_total_tokens` accumulates input and output across model calls in one `run()`.
Requests reserve estimated input and reduce `max_tokens` to the remaining allowance.
Provider-reported usage replaces the estimate when available. With neither a token nor
a cost limit set, a request is not estimated before it goes and its `max_tokens` is left
as the call set it; what the provider reports is still counted. Missing usage, failed
requests and cancelled streams reserve the estimated input and full output allowance.
Retries made by the Agent and the operator share the same task budget. A new turn
starts a new budget; nested phone and computer operators inherit the parent's budget.

`max_seconds` also includes tools and approval waits. Reaching it cancels work
cooperatively. A tool that ignores cancellation or performs blocking work cannot be
forcibly undone. Once a token or cost limit is reached, no further tool is started and
no paid wrap-up request is sent. A plain model answer that completed within an in-flight
request can still be returned.

For a cost limit, supply your own **USD per million tokens** rates. Use upper rates
covering every model the task may call, including the hands model. Cached input is
charged at the full configured input rate in this estimate. A nonzero cost limit with
both rates zero is rejected. Charges for provider-side retries hidden inside a client,
embedding calls, images, clips, and other paid tools are outside this accounting.
The budget limits application requests, not the provider's invoice.

Standalone operators use the same fields under `[gui.budget]`; inside a runtime Agent
turn, `[agent.budget]` takes precedence. Limits are configured in TOML, not exposed as
new controls in each app. A turn that ran under a limit, or was stopped by one, writes a
`task_budget` entry to the audit log; a task with no limit set leaves the log as it was.
`MuseAgent.last_budget` exposes the counters and the stop reason either way. Operator outcomes carry
the same counters for evaluation reports.
