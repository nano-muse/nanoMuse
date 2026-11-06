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

Expense totals keep their sign and fractional part. Conflicting totals or numbers that
cannot be represented without losing precision remain unknown rather than passing.

The expected outcomes in `tasks_v1.json` describe the currently committed responses. After
refreshing them, review each changed outcome manually before updating the expectations.

## Criterion cases

`criteria_cases_v1.json` measures the evaluator itself. Each case builds a final state and an
answer, runs one criterion to its verdict and compares the result with the expected one. Cases
from `spec` were written by a different model from the rules alone, in an empty directory;
cases from `code` were written against the evaluator to find inputs it judges wrongly. Every
criterion has at least one case that should pass and one that should fail.

`expected` follows the criterion as defined. `current` pins a result the evaluator still gets
wrong, a known miss. `truth` records the user's goal where a criterion, applied correctly,
still misses it: a calendar event can be right while the answer reports the wrong time. Closing
such a gap needs a new criterion, so it waits for the next version of the tasks. A change that
alters a case's result updates the case in the same commit.

A criterion that reads the answer does not guess at negation. When 不, 未, 没 or 无 sits in the
same clause as a reported result or a ticket exclusion, outside every status or exclusion word,
the criterion records unknown. The cases also record what this costs: an honest explanation such
as 因无权限被拒 goes to review.
