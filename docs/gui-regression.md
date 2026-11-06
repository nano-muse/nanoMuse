# Fixed GUI regression cases

The versioned task set is `tests/fixtures/gui_regression/cases.v1.json`. Its 20 cases
cover note entry and editing, Unicode input, search, settings, a cart, permission and
update dialogs, loading, Back, similar labels, recovery after an ineffective click,
accepted and refused approvals, and password handoff.

## Run without a model

From an installed development checkout:

```bash
python scripts/gui_regression.py
python scripts/gui_regression.py --case notifications-enable
python -m pytest -q tests/test_gui_regression.py
```

The command creates a unique directory under `.gui-regression/` with `report.json`,
per-case audit files, screenshots and operator traces. A failure returns exit code 1.
CI runs the cases through pytest and writes a reference report on Ubuntu / Python 3.12.

Reference mode uses `MockLLM` and makes no model requests. Its score measures the
operator, coordinate conversion, device requests, loop detection, approvals and the
verifier. It is **not a measured success rate for a real GUI model**, an Android device,
or a desktop app. The device is a deterministic stateful simulator with rendered PNG
screens and an accessibility tree; it does not control an application on the host.

## Run a configured model

```bash
python scripts/gui_regression.py --live --config config/config.toml
```

This opt-in command makes real, potentially paid calls with the configured `[llm]`
model. The same simulated scenes and result checks are used. Use a model that takes
images and emits the operator's `mobile_use` response format. Each case is capped at
16 operator steps and uses the model client's configured timeout and retry settings.
The runner uses the model client only; it does not attach your real devices. Its fixture
UI supplies the approval decisions declared by each case. It does not load skills or
run arbitrary shell commands.

## What passes

A case declares its initial scene, visible controls, transitions, expected final scene,
expected field values, terminal operator status and minimum approval count. The simulator
changes only when a valid action reaches the real `PhoneAct` through the real Sentinel.
Typing requires a focused field; tapping empty space does not advance the scene.
The evaluator compares the simulator's state with the expected result. A model claiming
success without acting, saving incorrect text, or selecting the wrong control fails.
For a refused approval, the expected result is an unchanged scene and a blocked operator.
For a password, the expected result is a handoff with no password entered.

The report labels `reference` and `live` runs separately, names the model and case file,
and includes pass rate, nearest-rank P95 duration, model calls, reported input/output
tokens, model latency, approval counts, individual checks and trace ids. Missing usage
is counted separately as `calls_without_usage`, never treated as zero-cost use or filled
with a token guess. Requests retried inside a provider client are outside the call count.
Compare the same fixture version and model settings between revisions. The reference
scripts live separately from the expected state and are never supplied to a live model.

The evaluator records usage itself and does not depend on task-budget or memory-recall
changes. It can be installed, tested and reverted independently of those features.

## Add a case

Add a unique id and a state graph to the JSON file. Each scene has a title and at most
six visible controls. A control can focus a field or move to another scene; scenes can
also react to Wait or Back. Add a reference action sequence for offline CI and declare
the result independently. All control ids in one case must be unique. Keep fixtures
synthetic and free of personal data. pytest parametrizes every case automatically.

These cases are a starting set for reproducible runtime regression. Further real-device
traces and richer simulated apps can extend coverage without treating reference replay
as evidence of model intelligence.
