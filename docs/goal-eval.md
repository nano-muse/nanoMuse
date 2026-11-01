# Goal evaluation tasks

Ten Chinese tasks exercise expense reports, ticket filtering, meeting briefs, calendars and
file archives in isolated synthetic worlds. The tasks use the runtime goal evaluator and
independent observations of the resulting state and answer.

## Offline replay

CI runs `pytest -q -m "not live"`. The task tests replay recorded model responses with
network connections denied. The recording came from `deepseek-flash` on 2026-11-01.
It contains responses and reported usage, not model inputs or reasoning. A changed agent
loop can require a new recording, since the number of responses must match exactly.

## Run with your model

Configure your provider, model and key as described in [configuration](configuration.md),
then run:

```sh
NANOMUSE_LIVE=1 NANOMUSE_GOAL_EVAL_OUTPUT=./goal-eval-output \
  python -m pytest -q -m live tests/test_goal_eval_tasks.py
```

The test uses the configured model, disables retries and limits each case to 50,000 tokens
and 120 seconds. Provider charges can apply. Without the output variable, files go to
pytest's temporary directory. `report.json` contains the outcomes and available usage;
`recording.json` contains the responses. Review the recording for personal data and secrets
before replacing `tests/fixtures/goal_eval/tasks_v1_recording.json` with it. Then rerun the
offline tests and review any changed criterion outcomes.

A verified result means the fixed criteria matched the observations for that case. Partial,
unknown and contradicted results describe those criteria, not general model capability.
The rules can miss paraphrases or misunderstand text, and these ten tasks do not measure
performance on other tasks. The live test checks that the runner completes, not that the
model succeeds.

The expected outcomes in `tasks_v1.json` describe the currently committed responses. After
refreshing them, review each changed outcome manually before updating the expectations.
