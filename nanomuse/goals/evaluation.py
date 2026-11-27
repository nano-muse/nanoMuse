"""Evidence-based goal evaluation core, opt-in by explicit library invocation.

This module does not change ``GoalStore`` status or run from the agent loop. Runtime
integration must define the trusted harness that supplies observations and applies any
later decision. Hashes detect changed snapshots; they do not authenticate a producer
or prove truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Scalar = bool | int | float | str
Verdict = Literal["verified", "partial", "unknown", "contradicted"]
Decision = Literal["continue", "replan", "escalate", "stop"]
EVALUATOR_VERSION = "goal-eval.v2"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _identity(value: Any) -> bool:
    return type(value) is str and bool(value.strip())


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


@dataclass(frozen=True)
class Criterion:
    id: str
    subject: str
    metric: str
    op: Literal["eq", "gte"]
    target: Scalar
    unit: str
    collectors: tuple[str, ...]
    max_age: int = 3600
    invariant: bool = False
    tier: int = 2


@dataclass(frozen=True)
class Contract:
    goal_id: str
    revision: int
    criteria: tuple[Criterion, ...]

    def validate(self) -> None:
        if not isinstance(self.criteria, tuple) or not all(
            isinstance(c, Criterion) for c in self.criteria
        ):
            raise ValueError("criteria must be a tuple of Criterion records")
        ids = [c.id for c in self.criteria]
        if not _identity(self.goal_id) or not _integer(self.revision, 1) or not ids:
            raise ValueError(
                "contract needs a goal, positive revision and unique nonempty criteria"
            )
        if not all(_identity(x) for x in ids) or len(ids) != len(set(ids)):
            raise ValueError("criterion ids must be unique nonempty strings")
        if all(c.invariant for c in self.criteria):
            raise ValueError("constraints alone cannot establish goal completion")
        for c in self.criteria:
            if (
                not all(_identity(x) for x in (c.id, c.subject, c.metric, c.unit))
                or not isinstance(c.collectors, tuple)
                or not c.collectors
                or not all(_identity(x) for x in c.collectors)
                or not _integer(c.max_age, 1)
                or type(c.invariant) is not bool
            ):
                raise ValueError("criterion needs identity, source and positive freshness")
            if type(c.tier) is not int or c.tier not in (1, 2):
                raise ValueError("criterion tier must be 1 or 2")
            if c.op not in ("eq", "gte") or not _scalar(c.target):
                raise ValueError("unsupported predicate or target")
            if c.op == "gte" and type(c.target) not in (int, float):
                raise ValueError("gte requires a finite numeric target")


def _contract_dict(contract: Contract) -> dict[str, Any]:
    raw = asdict(contract)
    criteria_list = []
    for c, c_dict in zip(contract.criteria, raw["criteria"], strict=True):
        cd = dict(c_dict)
        if type(c.tier) is int and c.tier == 2:
            cd.pop("tier", None)
        else:
            cd["tier"] = c.tier
        criteria_list.append(cd)
    raw["criteria"] = tuple(criteria_list)
    return raw


@dataclass(frozen=True)
class Run:
    id: str
    attempt: int = 1
    state: Literal["completed", "interrupted", "failed"] = "completed"


@dataclass(frozen=True)
class Evidence:
    id: str
    goal_id: str
    revision: int
    run_id: str
    call_id: str
    criterion_id: str
    collector: str
    observed_at: int
    collected_at: int
    subject: str
    metric: str
    value: Scalar
    unit: str
    payload_digest: str
    ok: bool = True
    allowed: bool = True
    attempt: int = 1

    def payload(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if k not in ("id", "payload_digest")}


def observation(**fields: Any) -> Evidence:
    """Trusted fixture builder; deliberately not an agent tool."""
    e = Evidence(payload_digest="", **fields)
    return Evidence(**{**asdict(e), "payload_digest": fingerprint(e.payload())})


def collect_file(
    contract: Contract, run: Run, criterion: Criterion, path: Path, now: int
) -> Evidence:
    """An actual independent, read-only observation of a preselected local artifact."""
    subject = path.resolve().as_uri()
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    event = fingerprint(
        [
            contract.goal_id,
            contract.revision,
            run.id,
            run.attempt,
            criterion.id,
            subject,
            now,
            value,
        ]
    )
    return observation(
        id=event,
        goal_id=contract.goal_id,
        revision=contract.revision,
        run_id=run.id,
        attempt=run.attempt,
        call_id=f"checker:{event}",
        criterion_id=criterion.id,
        collector="file.sha256.v1",
        observed_at=now,
        collected_at=now,
        subject=subject,
        metric="sha256",
        value=value,
        unit="digest",
    )


def _scalar(v: Any) -> bool:
    return type(v) in (bool, int, str) or (type(v) is float and math.isfinite(v))


def _matches(c: Criterion, value: Scalar) -> bool | None:
    numeric = type(value) in (int, float) and type(c.target) in (int, float)
    if not _scalar(value) or (not numeric and type(value) is not type(c.target)):
        return None
    if c.op == "gte":
        return value >= c.target if numeric else None  # type: ignore[operator]
    return value == c.target


def contract_from_dict(value: dict[str, Any]) -> Contract:
    """Strict JSON boundary, no coercion of booleans, numbers or source identities."""
    try:
        if (
            not isinstance(value, dict)
            or set(value) != {"goal_id", "revision", "criteria"}
            or type(value["criteria"]) is not list
        ):
            raise ValueError("invalid contract fields")
        criteria = []
        for item in value["criteria"]:
            if not isinstance(item, dict) or type(item.get("collectors")) is not list:
                raise ValueError("criterion must contain a collectors array")
            criteria.append(Criterion(**{**item, "collectors": tuple(item["collectors"])}))
        contract = Contract(value["goal_id"], value["revision"], tuple(criteria))
        contract.validate()
        return contract
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid contract schema") from exc


def validate_result(result: dict[str, Any]) -> None:
    """Validate snapshot integrity; this is not a producer signature or approval check."""
    try:
        fields = {k: v for k, v in result.items() if k != "id"}
        if result["id"] != fingerprint(fields):
            raise ValueError("evaluation digest mismatch")
        if type(result["schema_version"]) is not int or result["schema_version"] != 2:
            raise ValueError("unsupported evaluation schema")
        if result["evaluator_version"] != EVALUATOR_VERSION:
            raise ValueError("unsupported evaluator version")
        states = result["criteria"]
        if (
            not isinstance(states, dict)
            or not states
            or not all(
                _identity(k) and v in ("met", "not_met", "unknown", "conflict")
                for k, v in states.items()
            )
        ):
            raise ValueError("invalid criterion states")
        met = sorted(k for k, v in states.items() if v == "met")
        if result["met"] != met or result["required"] != len(states):
            raise ValueError("inconsistent criterion counts")
        if sorted(result["outcome_met"] + result["constraint_met"]) != met:
            raise ValueError("inconsistent outcome/constraint partition")
        if (
            not _integer(result["outcome_required"], 1)
            or not _integer(result["constraint_required"])
            or result["outcome_required"] + result["constraint_required"] != result["required"]
            or len(result["outcome_met"]) > result["outcome_required"]
            or len(result["constraint_met"]) > result["constraint_required"]
            or result["run_state"] not in ("completed", "failed", "interrupted")
        ):
            raise ValueError("invalid outcome/constraint counts or run state")
        refs = result["evidence"]
        if (
            not isinstance(refs, dict)
            or set(refs) != set(states)
            or any(
                type(ids) is not list or not all(_identity(x) for x in ids) for ids in refs.values()
            )
        ):
            raise ValueError("invalid evidence reference schema")
        if not all(
            _integer(result[k], 1) for k in ("attempt", "revision", "required")
        ) or not _integer(result["at"]):
            raise ValueError("invalid evaluation counters or time")
        if not all(_identity(result[k]) for k in ("goal_id", "run_id", "contract_hash")):
            raise ValueError("invalid evaluation binding")
        if any(states.get(k) != "not_met" for k in result["lost"] + result["violated"]):
            raise ValueError("invalid regression or violation")
        tier1_failed = result.get("tier1_failed", [])
        if "tier1_failed" in result:
            if (
                type(result["tier1_failed"]) is not list
                or not tier1_failed
                or tier1_failed != sorted(set(tier1_failed))
                or not all(_identity(k) for k in tier1_failed)
                or any(states.get(k) != "not_met" for k in tier1_failed)
                or bool(set(tier1_failed).intersection(result["violated"]))
                or bool(set(tier1_failed).intersection(result["lost"]))
            ):
                raise ValueError("invalid tier-1 failure references")
        contradicted = bool(
            result["lost"] or result["violated"] or tier1_failed or "conflict" in states.values()
        )
        expected = (
            "contradicted"
            if contradicted
            else "verified"
            if len(met) == len(states)
            else "unknown"
            if all(v == "unknown" for v in states.values())
            else "partial"
        )
        if result["status"] != expected:
            raise ValueError("inconsistent evaluation verdict")
        if result["delta"] is not None and type(result["delta"]) is not int:
            raise ValueError("invalid milestone delta")
        values = result["observed_values"]
        if (
            not isinstance(values, dict)
            or set(values) != {k for k, v in states.items() if v in ("met", "not_met")}
            or not all(_scalar(v) for v in values.values())
            or result["progress"] not in ("advanced", "stalled", "regressed", "unknown")
        ):
            raise ValueError("invalid observed values or progress")
        if any(not result["evidence"].get(k) for k, v in states.items() if v != "unknown"):
            raise ValueError("known criterion requires evidence references")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("invalid evaluation schema") from exc


def _validate_result_for_contract(
    contract: Contract,
    result: dict[str, Any],
) -> None:
    if set(result["criteria"]) != {c.id for c in contract.criteria}:
        raise ValueError("baseline criteria mismatch")
    if result["goal_id"] != contract.goal_id or result["revision"] != contract.revision:
        raise ValueError("baseline goal binding mismatch")
    for invariant, prefix in ((False, "outcome"), (True, "constraint")):
        partition = [c.id for c in contract.criteria if c.invariant == invariant]
        if result[f"{prefix}_required"] != len(partition) or result[f"{prefix}_met"] != sorted(
            cid for cid in partition if result["criteria"][cid] == "met"
        ):
            raise ValueError("baseline outcome/constraint partition mismatch")
    criteria_by_id = {c.id: c for c in contract.criteria}
    for criterion in contract.criteria:
        if criterion.id in result["observed_values"]:
            matched = _matches(criterion, result["observed_values"][criterion.id])
            if matched is None or matched != (result["criteria"][criterion.id] == "met"):
                raise ValueError("baseline observed value does not match its criterion state")
    if (
        any(not criteria_by_id[cid].invariant for cid in result["lost"])
        and result["progress"] != "regressed"
    ):
        raise ValueError("baseline lost outcome requires regressed progress")
    expected_violated = [
        c.id for c in contract.criteria if c.invariant and result["criteria"][c.id] == "not_met"
    ]
    if result["violated"] != expected_violated:
        raise ValueError("baseline constraint violation mismatch")
    expected_tier1 = sorted(
        c.id
        for c in contract.criteria
        if c.tier == 1
        and not c.invariant
        and c.id not in result["lost"]
        and result["criteria"][c.id] == "not_met"
    )
    if result.get("tier1_failed", []) != expected_tier1:
        raise ValueError("baseline tier-1 failure mismatch")


def evaluate(
    contract: Contract,
    run: Run,
    evidence: list[Evidence],
    *,
    now: int,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure snapshot evaluation. A successful task alone supplies no criterion evidence."""
    contract.validate()
    if (
        not _identity(run.id)
        or not _integer(run.attempt, 1)
        or run.state not in ("completed", "interrupted", "failed")
    ):
        raise ValueError("invalid run")
    if not _integer(now):
        raise ValueError("clock must be nonnegative integer seconds")
    contract_hash = fingerprint(_contract_dict(contract))
    if previous is not None:
        validate_result(previous)
        if previous["contract_hash"] != contract_hash or previous["at"] > now:
            raise ValueError("baseline must be earlier and from the identical contract")
        _validate_result_for_contract(contract, previous)
    # Reject unusable records before collision checks so a different scope/source
    # cannot suppress valid observations by copying their id.
    by_id: dict[str, Evidence] = {}
    collisions: set[str] = set()
    rejected: dict[str, str] = {}
    criteria_by_id = {c.id: c for c in contract.criteria}
    for index, e in enumerate(evidence):
        if not _identity(e.id):
            rejected[f"invalid:{index}"] = "invalid_evidence_id"
            continue
        c = criteria_by_id.get(e.criterion_id) if _identity(e.criterion_id) else None
        if c is None:
            rejected[e.id] = "unknown_criterion"
            continue
        try:
            intact = e.payload_digest == fingerprint(e.payload())
        except (ValueError, TypeError):
            intact = False
        valid = (
            all(_identity(v) for v in (e.id, e.call_id, e.goal_id, e.run_id, e.collector))
            and e.goal_id == contract.goal_id
            and _integer(e.revision, 1)
            and e.revision == contract.revision
            and e.run_id == run.id
            and _integer(e.attempt, 1)
            and e.attempt == run.attempt
            and e.collector in c.collectors
            and e.subject == c.subject
            and e.metric == c.metric
            and e.unit == c.unit
            and e.ok is True
            and e.allowed is True
            and _integer(e.observed_at)
            and _integer(e.collected_at)
            and 0 <= now - e.observed_at <= c.max_age
            and e.observed_at <= e.collected_at <= now
            and intact
            and _matches(c, e.value) is not None
        )
        if not valid:
            rejected[e.id] = "invalid_binding_source_time_type_or_integrity"
            continue
        if e.id in by_id and e != by_id[e.id]:
            collisions.add(e.id)
            rejected[e.id] = "conflicting_evidence_id"
        by_id[e.id] = e
    states: dict[str, str] = {}
    used: dict[str, list[str]] = {}
    values: dict[str, Scalar] = {}
    for c in contract.criteria:
        candidates = [
            e for e in by_id.values() if e.criterion_id == c.id and e.id not in collisions
        ]
        if not candidates:
            states[c.id], used[c.id] = "unknown", []
            continue
        latest = max(e.observed_at for e in candidates)
        current = sorted((e for e in candidates if e.observed_at == latest), key=lambda e: e.id)
        used[c.id] = sorted(e.id for e in current)
        if any(e.value != current[0].value for e in current[1:]):
            states[c.id] = "conflict"
        else:
            states[c.id] = "met" if _matches(c, current[0].value) else "not_met"
            values[c.id] = current[0].value
    met = sorted(k for k, v in states.items() if v == "met")
    outcome_met = sorted(
        c.id for c in contract.criteria if not c.invariant and states[c.id] == "met"
    )
    constraint_met = sorted(
        c.id for c in contract.criteria if c.invariant and states[c.id] == "met"
    )
    prior_met = set(previous["met"]) if previous else set()
    prior_outcomes = previous["outcome_met"] if previous else []
    lost = sorted(prior_met & {k for k, v in states.items() if v == "not_met"})
    violated = [c.id for c in contract.criteria if c.invariant and states[c.id] == "not_met"]
    tier1_failed = sorted(
        c.id
        for c in contract.criteria
        if c.tier == 1 and not c.invariant and c.id not in lost and states[c.id] == "not_met"
    )
    contradicted = bool(lost or violated or tier1_failed or "conflict" in states.values())
    status: Verdict
    if contradicted:
        status = "contradicted"
    elif all(v == "met" for v in states.values()):
        status = "verified"
    elif all(v == "unknown" for v in states.values()):
        status = "unknown"
    else:
        status = "partial"
    comparable = previous is not None and all(
        v in ("met", "not_met") for v in [*states.values(), *previous["criteria"].values()]
    )
    # Milestone coverage and raw numeric progress answer different questions.
    # Only gte has an explicit numeric direction; equality gains/losses use the
    # predicate state. Unknown outcomes never count as unchanged observations.
    gains, declines = False, False
    outcomes_comparable = previous is not None
    for c in contract.criteria:
        if c.invariant:
            continue
        if previous is None or c.id not in values or c.id not in previous["observed_values"]:
            outcomes_comparable = False
            continue
        old, new = previous["observed_values"][c.id], values[c.id]
        if c.op == "gte":
            old_effective = min(old, c.target)  # type: ignore[type-var]
            new_effective = min(new, c.target)  # type: ignore[type-var]
            gains = gains or new_effective > old_effective  # type: ignore[operator]
            declines = declines or new_effective < old_effective  # type: ignore[operator]
        else:
            gains = gains or (previous["criteria"][c.id] != "met" and states[c.id] == "met")
            declines = declines or (
                previous["criteria"][c.id] == "met" and states[c.id] == "not_met"
            )
    progress = (
        "regressed"
        if declines
        else "advanced"
        if gains
        else "stalled"
        if outcomes_comparable
        else "unknown"
    )
    result = {
        "schema_version": 2,
        "evaluator_version": EVALUATOR_VERSION,
        "contract_hash": contract_hash,
        "goal_id": contract.goal_id,
        "revision": contract.revision,
        "run_id": run.id,
        "attempt": run.attempt,
        "run_state": run.state,
        "at": now,
        "status": status,
        "criteria": states,
        "met": met,
        "outcome_met": outcome_met,
        "outcome_required": sum(not c.invariant for c in contract.criteria),
        "constraint_met": constraint_met,
        "constraint_required": sum(c.invariant for c in contract.criteria),
        "required": len(states),
        "delta": len(outcome_met) - len(prior_outcomes) if comparable else None,
        "observed_values": values,
        "progress": progress,
        "lost": lost,
        "violated": violated,
        "evidence": used,
        "rejected": rejected,
    }
    if tier1_failed:
        result["tier1_failed"] = tier1_failed
    result["id"] = fingerprint(result)
    return result


def decide(
    result: dict[str, Any],
    *,
    stalled_runs: int = 0,
    unknown_runs: int = 0,
    approved_result_id: str | None = None,
) -> tuple[Decision, str]:
    """Recommendation only. Approval is a trusted test input, not an authorization API."""
    validate_result(result)
    if not _integer(stalled_runs) or not _integer(unknown_runs):
        raise ValueError("continuity counters must be nonnegative integers")
    if approved_result_id == result["id"] and result["status"] == "verified":
        return "stop", "completion_approved"
    if result["status"] == "verified":
        return "escalate", "review_completion"
    if "unknown" in result["criteria"].values() and unknown_runs >= 3:
        return "escalate", "verification_budget_exhausted"
    if (
        result["status"] == "contradicted"
        or result["progress"] == "regressed"
        or (result["status"] == "partial" and stalled_runs >= 3 and result["progress"] == "stalled")
    ):
        return "replan", "review_plan"
    if result["run_state"] != "completed":
        return "continue", "reconcile_before_retry"
    return "continue", "collect_evidence" if result["status"] == "unknown" else "next_step"


class Ledger:
    """Atomic append of input and result; a crash before commit is safe to retry.

    Counts, scheduling, side effects, leases and process-death detection are out of scope.
    """

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS evaluations ("
            "contract_hash TEXT, run_id TEXT, attempt INTEGER, input TEXT, result TEXT, "
            "PRIMARY KEY (contract_hash, run_id, attempt))"
        )
        self.conn.commit()

    def record(
        self,
        contract: Contract,
        run: Run,
        evidence: list[Evidence],
        *,
        now: int,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        contract.validate()
        contract_dict = _contract_dict(contract)
        inputs = canonical(
            {
                "contract": contract_dict,
                "run": asdict(run),
                "evidence": [asdict(e) for e in evidence],
                "now": now,
                "previous": previous,
            }
        )
        contract_hash = fingerprint(contract_dict)
        key = (contract_hash, run.id, run.attempt)
        with self.conn:
            row = self.conn.execute(
                "SELECT input, result FROM evaluations WHERE contract_hash=? AND run_id=? AND attempt=?",
                key,
            ).fetchone()
            if row:
                if row[0] != inputs:
                    raise ValueError("attempt already recorded with different inputs")
                if previous is not None:
                    validate_result(previous)
                saved = json.loads(row[1])
                validate_result(saved)
                if (
                    saved["contract_hash"] != contract_hash
                    or saved["run_id"] != run.id
                    or saved["attempt"] != run.attempt
                    or saved["at"] != now
                    or saved["run_state"] != run.state
                ):
                    raise ValueError("recorded result binding mismatch")
                _validate_result_for_contract(contract, saved)
                expected_lost = (
                    sorted(
                        set(previous["met"])
                        & {k for k, v in saved["criteria"].items() if v == "not_met"}
                    )
                    if previous is not None
                    else []
                )
                if saved["lost"] != expected_lost:
                    raise ValueError("recorded regression mismatch")
                return saved
            result = evaluate(contract, run, evidence, now=now, previous=previous)
            self.conn.execute(
                "INSERT INTO evaluations VALUES (?,?,?,?,?)", (*key, inputs, canonical(result))
            )
        return result

    def close(self) -> None:
        self.conn.close()
