"""Run: python tests/test_goal_evaluation.py.

These evaluator tests require the standard library only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from nanomuse.goals.evaluation import (
    Contract,
    Criterion,
    Evidence,
    Ledger,
    Run,
    Scalar,
    canonical,
    collect_file,
    contract_from_dict,
    decide,
    evaluate,
    fingerprint,
    observation,
    validate_result,
)

NOW = 10000


class GoalEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.criterion = Criterion(
            "accepted",
            "fixture://submission/1",
            "accepted",
            "eq",
            True,
            "boolean",
            ("fixture.external.v1",),
            max_age=60,
        )
        self.contract = Contract("g_1", 1, (self.criterion,))
        self.goal_run = Run("r_1")

    def evidence(self, value: Scalar = True, **overrides: Any) -> Evidence:
        fields: dict[str, Any] = dict(
            id="e_1",
            goal_id="g_1",
            revision=1,
            run_id="r_1",
            call_id="call_1",
            criterion_id="accepted",
            collector="fixture.external.v1",
            observed_at=NOW,
            collected_at=NOW,
            subject="fixture://submission/1",
            metric="accepted",
            value=value,
            unit="boolean",
        )
        fields.update(overrides)
        return observation(**fields)

    def test_task_completed_with_real_progress(self) -> None:
        before = evaluate(self.contract, self.goal_run, [self.evidence(False)], now=NOW)
        after = evaluate(self.contract, self.goal_run, [self.evidence()], now=NOW, previous=before)
        self.assertEqual((after["status"], after["delta"]), ("verified", 1))
        self.assertEqual(after["evidence"], {"accepted": ["e_1"]})
        self.assertEqual(decide(after), ("escalate", "review_completion"))
        self.assertEqual(decide(after, approved_result_id=after["id"])[0], "stop")
        self.assertNotEqual(decide(after, approved_result_id="another-result")[0], "stop")

    def test_task_succeeded_without_goal_progress(self) -> None:
        before = evaluate(self.contract, self.goal_run, [self.evidence(False)], now=NOW)
        after = evaluate(
            self.contract,
            Run("r_2"),
            [self.evidence(False, run_id="r_2")],
            now=NOW,
            previous=before,
        )
        self.assertEqual((after["status"], after["delta"]), ("partial", 0))
        self.assertEqual(after["met"], [])
        self.assertEqual(decide(after, stalled_runs=3)[0], "replan")

    def test_model_claim_without_evidence(self) -> None:
        claim = self.evidence(collector="llm.self_report")
        result = evaluate(self.contract, self.goal_run, [claim], now=NOW)
        self.assertEqual((result["status"], result["delta"]), ("unknown", None))
        self.assertEqual(decide(result), ("continue", "collect_evidence"))
        self.assertEqual(decide(result, unknown_runs=3)[0], "escalate")

    def test_external_condition_invalidates_plan(self) -> None:
        contract = replace(
            self.contract,
            criteria=(self.criterion, replace(self.criterion, id="window", invariant=True)),
        )
        result = evaluate(
            contract, self.goal_run, [self.evidence(False, criterion_id="window")], now=NOW
        )
        self.assertEqual(result["status"], "contradicted")
        self.assertEqual(result["violated"], ["window"])
        self.assertEqual(decide(result)[0], "replan")

    def test_interrupted_retry_and_reopen_do_not_double_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.db"
            ledger = Ledger(path)
            before = ledger.record(
                self.contract, replace(self.goal_run, state="interrupted"), [], now=NOW
            )
            self.assertEqual(before["status"], "unknown")
            self.assertEqual(decide(before)[1], "reconcile_before_retry")
            ledger.close()
            ledger = Ledger(path)
            recovered = ledger.record(
                self.contract,
                replace(self.goal_run, attempt=2),
                [self.evidence(attempt=2)],
                now=NOW,
                previous=before,
            )
            self.assertEqual(recovered["status"], "verified")
            replay = ledger.record(
                self.contract,
                replace(self.goal_run, attempt=2),
                [self.evidence(attempt=2)],
                now=NOW,
                previous=before,
            )
            self.assertEqual(recovered, replay)
            self.assertEqual(
                ledger.conn.execute("SELECT count(*) FROM evaluations").fetchone()[0], 2
            )
            with self.assertRaises(ValueError):
                ledger.record(self.contract, replace(self.goal_run, attempt=2), [], now=NOW)
            ledger.close()

    def test_real_artifact_recheck_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("accepted report\n")
            criterion = Criterion(
                "file",
                path.resolve().as_uri(),
                "sha256",
                "eq",
                hashlib.sha256(path.read_bytes()).hexdigest(),
                "digest",
                ("file.sha256.v1",),
            )
            contract = Contract("g_1", 1, (criterion,))
            before = evaluate(
                contract,
                self.goal_run,
                [collect_file(contract, self.goal_run, criterion, path, NOW)],
                now=NOW,
            )
            self.assertEqual(before["status"], "verified")
            path.write_text("different report\n")
            after = evaluate(
                contract,
                self.goal_run,
                [collect_file(contract, self.goal_run, criterion, path, NOW + 1)],
                now=NOW + 1,
                previous=before,
            )
            self.assertEqual(after["status"], "contradicted")

    def test_unusable_evidence_never_verifies(self) -> None:
        for fields in (
            {"goal_id": "g_other"},
            {"revision": 2},
            {"run_id": "r_other"},
            {"subject": "fixture://other"},
            {"call_id": ""},
            {"unit": "percent"},
            {"metric": "tool_ok"},
            {"observed_at": NOW - 61},
            {"collected_at": NOW + 1},
            {"observed_at": NOW + 1},
            {"ok": False},
            {"allowed": False},
            {"value": 1},
            {"value": "true"},
        ):
            with self.subTest(fields=fields):
                result = evaluate(self.contract, self.goal_run, [self.evidence(**fields)], now=NOW)
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["met"], [])

    def test_digest_mismatch_is_unknown(self) -> None:
        e = replace(self.evidence(), value=False)
        self.assertEqual(evaluate(self.contract, self.goal_run, [e], now=NOW)["status"], "unknown")

    def test_duplicate_and_conflicting_ids(self) -> None:
        e = self.evidence()
        self.assertEqual(
            evaluate(self.contract, self.goal_run, [e, e], now=NOW)["met"], ["accepted"]
        )
        result = evaluate(self.contract, self.goal_run, [e, self.evidence(False)], now=NOW)
        self.assertEqual(result["status"], "unknown")

    def test_conflicting_independent_observations_require_review(self) -> None:
        result = evaluate(
            self.contract, self.goal_run, [self.evidence(), self.evidence(False, id="e_2")], now=NOW
        )
        self.assertEqual(result["status"], "contradicted")
        self.assertEqual(result["criteria"]["accepted"], "conflict")

    def test_latest_valid_observation_wins(self) -> None:
        old = self.evidence(False, id="old", observed_at=NOW - 1)
        result = evaluate(self.contract, self.goal_run, [old, self.evidence()], now=NOW)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(
            result, evaluate(self.contract, self.goal_run, [self.evidence(), old], now=NOW)
        )

    def test_partial_coverage_and_no_vacuous_success(self) -> None:
        contract = replace(
            self.contract, criteria=(self.criterion, replace(self.criterion, id="second"))
        )
        result = evaluate(contract, self.goal_run, [self.evidence()], now=NOW)
        self.assertEqual((result["status"], result["required"]), ("partial", 2))
        self.assertIsNone(result["delta"])
        with self.assertRaises(ValueError):
            evaluate(replace(contract, criteria=()), self.goal_run, [], now=NOW)
        with self.assertRaises(ValueError):
            evaluate(
                replace(contract, criteria=(replace(self.criterion, invariant=True),)),
                self.goal_run,
                [],
                now=NOW,
            )

    def test_revision_baseline_and_nan_are_rejected(self) -> None:
        before = evaluate(self.contract, self.goal_run, [], now=NOW)
        with self.assertRaises(ValueError):
            evaluate(
                replace(self.contract, revision=2), self.goal_run, [], now=NOW, previous=before
            )
        with self.assertRaises(ValueError):
            evaluate(self.contract, self.goal_run, [], now=NOW - 1, previous=before)
        with self.assertRaises(ValueError):
            evaluate(
                replace(self.contract, criteria=(replace(self.criterion, target=float("nan")),)),
                self.goal_run,
                [],
                now=NOW,
            )

    def test_sqlite_transaction_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "eval.db")
            with self.assertRaises(sqlite3.OperationalError), ledger.conn:
                ledger.conn.execute("INSERT INTO evaluations VALUES ('x','r',1,'{}','{}')")
                ledger.conn.execute("INSERT INTO missing_table VALUES (1)")
            self.assertEqual(
                ledger.conn.execute("SELECT count(*) FROM evaluations").fetchone()[0], 0
            )
            ledger.close()

    def test_numeric_predicate_and_units(self) -> None:
        criterion = replace(self.criterion, metric="count", op="gte", target=3, unit="items")
        contract = replace(self.contract, criteria=(criterion,))
        for value, expected in ((2, "partial"), (3, "verified"), (True, "unknown")):
            e = self.evidence(value=value, metric="count", unit="items")
            self.assertEqual(evaluate(contract, self.goal_run, [e], now=NOW)["status"], expected)

    def test_retry_requires_evidence_from_the_current_attempt(self) -> None:
        run = replace(self.goal_run, attempt=2)
        old = evaluate(self.contract, run, [self.evidence()], now=NOW)
        fresh = evaluate(self.contract, run, [self.evidence(attempt=2)], now=NOW)
        self.assertEqual((old["status"], fresh["status"]), ("unknown", "verified"))

    def test_json_flags_and_integer_fields_are_strict(self) -> None:
        invalid_overrides: tuple[dict[str, Any], ...] = (
            {"ok": "false"},
            {"allowed": "false"},
            {"revision": True},
            {"attempt": True},
            {"observed_at": True},
            {"id": []},
        )
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    evaluate(self.contract, self.goal_run, [self.evidence(**overrides)], now=NOW)[
                        "status"
                    ],
                    "unknown",
                )

    def test_modified_result_cannot_reuse_completion_approval(self) -> None:
        result = evaluate(self.contract, self.goal_run, [], now=NOW)
        altered = {**result, "status": "verified"}
        with self.assertRaises(ValueError):
            decide(altered, approved_result_id=result["id"])

    def test_baseline_integrity_and_evaluator_version_are_checked(self) -> None:
        result = evaluate(self.contract, self.goal_run, [self.evidence()], now=NOW)
        for field, value in (("met", []), ("evaluator_version", "other.v1")):
            altered = {**result, field: value}
            with self.assertRaises(ValueError):
                evaluate(self.contract, self.goal_run, [], now=NOW, previous=altered)
        altered = {**result, "evaluator_version": "other.v1"}
        altered["id"] = fingerprint({k: v for k, v in altered.items() if k != "id"})
        with self.assertRaises(ValueError):
            evaluate(self.contract, self.goal_run, [], now=NOW, previous=altered)

    def test_equivalent_numeric_observations_do_not_conflict(self) -> None:
        criterion = replace(self.criterion, metric="count", op="gte", target=1, unit="items")
        contract = replace(self.contract, criteria=(criterion,))
        observations = [
            self.evidence(value=v, metric="count", unit="items", id=str(v)) for v in (1, 1.0)
        ]
        result = evaluate(contract, self.goal_run, observations, now=NOW)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result, evaluate(contract, self.goal_run, observations[::-1], now=NOW))

    def test_constraint_recovery_is_not_outcome_progress(self) -> None:
        contract = replace(
            self.contract,
            criteria=(self.criterion, replace(self.criterion, id="window", invariant=True)),
        )
        before = evaluate(
            contract,
            self.goal_run,
            [self.evidence(False), self.evidence(False, id="w", criterion_id="window")],
            now=NOW,
        )
        after = evaluate(
            contract,
            self.goal_run,
            [self.evidence(False), self.evidence(True, id="w", criterion_id="window")],
            now=NOW,
            previous=before,
        )
        self.assertEqual(after["outcome_met"], [])
        self.assertEqual(after["constraint_met"], ["window"])
        self.assertEqual(after["delta"], 0)

    def test_subthreshold_growth_does_not_trigger_stagnation(self) -> None:
        criterion = replace(self.criterion, metric="count", op="gte", target=10, unit="items")
        contract = replace(self.contract, criteria=(criterion,))
        previous = None
        for count in (0, 3, 6, 9):
            evidence = self.evidence(value=count, metric="count", unit="items")
            result = evaluate(contract, self.goal_run, [evidence], now=NOW, previous=previous)
            if previous is not None:
                self.assertEqual(result["delta"], 0)  # Milestone coverage is unchanged.
                self.assertEqual(result["progress"], "advanced")
                self.assertEqual(decide(result, stalled_runs=3)[0], "continue")
            self.assertEqual(result["observed_values"], {"accepted": count})
            previous = result

    def test_partial_unknown_exhausts_verification_budget(self) -> None:
        contract = replace(
            self.contract,
            criteria=(self.criterion, replace(self.criterion, id="guard", invariant=True)),
        )
        previous = None
        for round_number in range(1, 6):
            result = evaluate(
                contract, self.goal_run, [self.evidence(False)], now=NOW, previous=previous
            )
            self.assertEqual(result["status"], "partial")
            self.assertIsNone(result["delta"])
            if previous is not None:
                self.assertEqual(result["progress"], "stalled")
            decision = decide(result, unknown_runs=round_number)
            self.assertEqual(decision[0], "escalate" if round_number >= 3 else "continue")
            previous = result

    def test_known_growth_is_visible_with_another_unknown_outcome(self) -> None:
        counter = replace(self.criterion, metric="count", op="gte", target=10, unit="items")
        contract = replace(
            self.contract, criteria=(counter, replace(self.criterion, id="unavailable"))
        )
        before = evaluate(
            contract, self.goal_run, [self.evidence(value=2, metric="count", unit="items")], now=NOW
        )
        result = evaluate(
            contract,
            self.goal_run,
            [self.evidence(value=5, metric="count", unit="items")],
            now=NOW,
            previous=before,
        )
        self.assertEqual((result["progress"], result["delta"]), ("advanced", None))
        self.assertEqual(result["status"], "partial")

    def test_numeric_regression_is_not_milestone_stagnation(self) -> None:
        counter = replace(self.criterion, metric="count", op="gte", target=10, unit="items")
        contract = replace(self.contract, criteria=(counter,))
        before = evaluate(
            contract, self.goal_run, [self.evidence(value=9, metric="count", unit="items")], now=NOW
        )
        result = evaluate(
            contract,
            self.goal_run,
            [self.evidence(value=6, metric="count", unit="items")],
            now=NOW,
            previous=before,
        )
        self.assertEqual((result["progress"], result["delta"]), ("regressed", 0))
        self.assertEqual(decide(result)[0], "replan")

    def test_changes_above_a_satisfied_threshold_are_not_goal_progress(self) -> None:
        counter = replace(
            self.criterion, id="count", metric="count", op="gte", target=10, unit="items"
        )
        contract = replace(self.contract, criteria=(self.criterion, counter))
        previous = None
        for count in (10, 20, 11):
            result = evaluate(
                contract,
                self.goal_run,
                [
                    self.evidence(False),
                    self.evidence(
                        value=count, id="count", criterion_id="count", metric="count", unit="items"
                    ),
                ],
                now=NOW,
                previous=previous,
            )
            if previous is not None:
                self.assertEqual(result["progress"], "stalled")
                self.assertEqual(decide(result, stalled_runs=3)[0], "replan")
            previous = result

    def test_out_of_scope_collision_cannot_suppress_valid_evidence(self) -> None:
        valid = self.evidence()
        for invalid in (
            self.evidence(False, goal_id="another_goal"),
            self.evidence(False, attempt=2),
            self.evidence(False, collector="untrusted"),
        ):
            for records in ([valid, invalid], [invalid, valid]):
                self.assertEqual(
                    evaluate(self.contract, self.goal_run, records, now=NOW)["status"], "verified"
                )

    def test_file_collection_ids_identify_observation_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("x")
            criterion = replace(
                self.criterion,
                subject=path.resolve().as_uri(),
                metric="sha256",
                target=hashlib.sha256(b"x").hexdigest(),
                unit="digest",
                collectors=("file.sha256.v1",),
            )
            contract = replace(self.contract, criteria=(criterion,))
            old = collect_file(contract, self.goal_run, criterion, path, NOW)
            run = replace(self.goal_run, attempt=2)
            current = collect_file(contract, run, criterion, path, NOW + 1)
            newer = collect_file(contract, run, criterion, path, NOW + 2)
            self.assertEqual(len({old.id, current.id, newer.id}), 3)
            result = evaluate(contract, run, [old, current, newer], now=NOW + 2)
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["evidence"][criterion.id], [newer.id])

    def test_freshness_boundary_is_inclusive(self) -> None:
        evidence = self.evidence(observed_at=NOW - 60)
        self.assertEqual(
            evaluate(self.contract, self.goal_run, [evidence], now=NOW)["status"], "verified"
        )
        self.assertEqual(
            evaluate(self.contract, self.goal_run, [evidence], now=NOW + 1)["status"], "unknown"
        )

    def test_contract_json_boundary_rejects_coercion_and_extra_fields(self) -> None:
        data = json.loads(json.dumps(asdict(self.contract)))
        self.assertEqual(contract_from_dict(data), self.contract)
        for altered in ({**data, "revision": True}, {**data, "ignored": "field"}):
            with self.assertRaises(ValueError):
                contract_from_dict(altered)

    def test_result_schema_is_checked_even_when_digest_is_recomputed(self) -> None:
        result = evaluate(self.contract, self.goal_run, [self.evidence()], now=NOW)
        invalid_result_fields: tuple[dict[str, Any], ...] = (
            {"run_state": "invalid"},
            {"outcome_required": False},
            {"constraint_required": 999},
            {"evidence": {"accepted": True}},
            {"progress": "complete"},
            {"observed_values": {"accepted": []}},
            {"observed_values": {}},
            {"delta": "zero"},
        )
        for fields in invalid_result_fields:
            altered = {**result, **fields}
            altered["id"] = fingerprint({k: v for k, v in altered.items() if k != "id"})
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                decide(altered, approved_result_id=altered["id"])

    def test_baseline_observed_values_must_match_the_contract(self) -> None:
        previous = evaluate(self.contract, self.goal_run, [self.evidence()], now=NOW)
        for value in (False, "true", 1):
            altered = {**previous, "observed_values": {"accepted": value}}
            altered["id"] = fingerprint({k: v for k, v in altered.items() if k != "id"})
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate(self.contract, self.goal_run, [], now=NOW, previous=altered)

    def test_baseline_partition_cannot_reclassify_constraints_as_outcomes(self) -> None:
        contract = replace(
            self.contract,
            criteria=(self.criterion, replace(self.criterion, id="guard", invariant=True)),
        )
        evidence = [self.evidence(), self.evidence(id="guard", criterion_id="guard")]
        previous = evaluate(contract, self.goal_run, evidence, now=NOW)
        previous.update(
            outcome_required=2,
            constraint_required=0,
            outcome_met=previous["met"],
            constraint_met=[],
        )
        previous["id"] = fingerprint({k: v for k, v in previous.items() if k != "id"})
        with self.assertRaises(ValueError):
            evaluate(contract, self.goal_run, evidence, now=NOW, previous=previous)

    def test_continuity_counters_reject_boolean_and_negative_inputs(self) -> None:
        result = evaluate(self.contract, self.goal_run, [], now=NOW)
        for counters in ({"stalled_runs": True}, {"unknown_runs": -1}):
            with self.subTest(counters=counters), self.assertRaises(ValueError):
                decide(result, **counters)

    def test_ledger_and_previous_v0_backward_compatibility(self) -> None:
        legacy_hash = "7325c04b5752ffe3b4d58fa7484dc3bea51fcfef8359e1d2cc6e4527080522ef"
        legacy_input = (
            '{"contract":{"criteria":[{"collectors":["collector.v1"],"id":"C1",'
            '"invariant":false,"max_age":3600,"metric":"status","op":"eq",'
            '"subject":"file:///report.txt","target":"ok","unit":"state"}],'
            '"goal_id":"goal-v0","revision":1},"evidence":[{"allowed":true,"attempt":1,'
            '"call_id":"call-1","collected_at":100,"collector":"collector.v1",'
            '"criterion_id":"C1","goal_id":"goal-v0","id":"ev-1","metric":"status",'
            '"observed_at":100,"ok":true,'
            '"payload_digest":"e2ea734a83b7eb3c6886301222e7fd1bfc00d6e4a836c1ed7f7d7fcd95f58c99",'
            '"revision":1,"run_id":"run-v0","subject":"file:///report.txt","unit":"state",'
            '"value":"ok"}],"now":100,"previous":null,'
            '"run":{"attempt":1,"id":"run-v0","state":"completed"}}'
        )
        legacy_result_raw = (
            '{"at":100,"attempt":1,"constraint_met":[],"constraint_required":0,'
            '"contract_hash":"7325c04b5752ffe3b4d58fa7484dc3bea51fcfef8359e1d2cc6e4527080522ef",'
            '"criteria":{"C1":"met"},"delta":null,"evaluator_version":"goal-eval.v2",'
            '"evidence":{"C1":["ev-1"]},"goal_id":"goal-v0",'
            '"id":"ad5e4a7184c2e1706744594c87bf15abcfbff0f83f87dacf03fe032f52536abd",'
            '"lost":[],"met":["C1"],"observed_values":{"C1":"ok"},"outcome_met":["C1"],'
            '"outcome_required":1,"progress":"unknown","rejected":{},"required":1,'
            '"revision":1,"run_id":"run-v0","run_state":"completed","schema_version":2,'
            '"status":"verified","violated":[]}'
        )
        legacy_result = json.loads(legacy_result_raw)

        c1 = Criterion(
            id="C1",
            subject="file:///report.txt",
            metric="status",
            op="eq",
            target="ok",
            unit="state",
            collectors=("collector.v1",),
        )
        c1_explicit = replace(c1, tier=2)
        contract = Contract("goal-v0", 1, (c1,))
        contract_explicit = Contract("goal-v0", 1, (c1_explicit,))
        contract_tier1 = Contract("goal-v0", 1, (replace(c1, tier=1),))
        run = Run("run-v0", 1, "completed")
        ev1 = observation(
            id="ev-1",
            goal_id=contract.goal_id,
            revision=contract.revision,
            run_id=run.id,
            attempt=run.attempt,
            call_id="call-1",
            criterion_id=c1.id,
            collector="collector.v1",
            observed_at=100,
            collected_at=100,
            subject=c1.subject,
            metric=c1.metric,
            value="ok",
            unit=c1.unit,
        )

        # Fresh evaluation of default tier=2 and explicit tier=2 is byte-for-byte identical.
        fresh = evaluate(contract, run, [ev1], now=100)
        fresh_explicit = evaluate(contract_explicit, run, [ev1], now=100)
        self.assertEqual(fresh["contract_hash"], legacy_hash)
        self.assertEqual(canonical(fresh), legacy_result_raw)
        self.assertEqual(canonical(fresh_explicit), legacy_result_raw)

        # Tier 1 changes contract identity.
        tier1_res = evaluate(contract_tier1, run, [ev1], now=100)
        self.assertNotEqual(tier1_res["contract_hash"], legacy_hash)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db = Path(tmp_dir) / "ledger_legacy.db"
            ledger = Ledger(tmp_db)
            with ledger.conn:
                ledger.conn.execute(
                    "INSERT INTO evaluations VALUES (?,?,?,?,?)",
                    (legacy_hash, run.id, run.attempt, legacy_input, legacy_result_raw),
                )

            recorded = ledger.record(contract, run, [ev1], now=100)
            self.assertEqual(canonical(recorded), legacy_result_raw)
            recorded_explicit = ledger.record(contract_explicit, run, [ev1], now=100)
            self.assertEqual(canonical(recorded_explicit), legacy_result_raw)
            row_count = ledger.conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
            self.assertEqual(row_count, 1)

            # Float tier=2.0 must not bypass validation via legacy cache lookup.
            invalid_float_contract = Contract("goal-v0", 1, (replace(c1, tier=2.0),))  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                ledger.record(invalid_float_contract, run, [ev1], now=100)

            next_eval = evaluate(contract, run, [ev1], now=200, previous=legacy_result)
            self.assertEqual(next_eval["status"], "verified")
            ledger.close()

    def test_invalid_criterion_tier_rejected(self) -> None:
        for bad_tier in (0, 3, True, False, "1", None):
            with self.subTest(bad_tier=bad_tier):
                c = replace(self.criterion, tier=bad_tier)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    Contract("g_1", 1, (c,)).validate()
                payload = {
                    "goal_id": "g_1",
                    "revision": 1,
                    "criteria": [
                        {
                            "id": "c1",
                            "subject": "s",
                            "metric": "m",
                            "op": "eq",
                            "target": "ok",
                            "unit": "u",
                            "collectors": ["collector.v1"],
                            "tier": bad_tier,
                        }
                    ],
                }
                with self.assertRaises(ValueError):
                    contract_from_dict(payload)

    def test_truth_table_tier1_vs_tier2(self) -> None:
        # Construct base criteria: outcome c_t1 (tier 1), outcome c_t2 (tier 2), invariant c_inv
        c_t1 = Criterion(
            id="amount",
            subject="report://total",
            metric="total",
            op="eq",
            target=300,
            unit="yuan",
            collectors=("fixture.v1",),
            tier=1,
        )
        c_t2 = Criterion(
            id="format",
            subject="report://format",
            metric="valid",
            op="eq",
            target=True,
            unit="boolean",
            collectors=("fixture.v1",),
            tier=2,
        )
        c_inv = Criterion(
            id="guard",
            subject="report://guard",
            metric="clean",
            op="eq",
            target=True,
            unit="boolean",
            collectors=("fixture.v1",),
            invariant=True,
            tier=2,
        )
        contract = Contract("g_truth", 1, (c_t1, c_t2, c_inv))
        run = Run("r_truth")

        def ev(
            cid: str, val: Any, eid: str | None = None, observed_at: int = NOW, **kw: Any
        ) -> Evidence:
            c = next(x for x in (c_t1, c_t2, c_inv) if x.id == cid)
            actual_eid = eid if eid is not None else f"e_{cid}"
            return observation(
                id=actual_eid,
                goal_id=contract.goal_id,
                revision=contract.revision,
                run_id=run.id,
                attempt=run.attempt,
                call_id=f"call_{actual_eid}",
                criterion_id=cid,
                collector=c.collectors[0],
                observed_at=observed_at,
                collected_at=observed_at,
                subject=c.subject,
                metric=c.metric,
                value=val,
                unit=c.unit,
                **kw,
            )

        # 1. tier=1 + 有效证据 not_met (总额写错) -> 单项 not_met，整例 contradicted，含 tier1_failed，decide() 返回 ("replan", "review_plan")
        res1 = evaluate(
            contract,
            run,
            [ev("amount", 200), ev("format", True), ev("guard", True)],
            now=NOW,
        )
        self.assertEqual(res1["criteria"]["amount"], "not_met")
        self.assertEqual(res1["status"], "contradicted")
        self.assertEqual(res1.get("tier1_failed"), ["amount"])
        self.assertEqual(decide(res1), ("replan", "review_plan"))

        # 2. tier=1 + 缺失证据 (没写总额) -> 单项 unknown，tier1_failed 不存在，整例保持 partial (不升级为 contradicted)
        res2_missing = evaluate(contract, run, [ev("format", True), ev("guard", True)], now=NOW)
        self.assertEqual(res2_missing["criteria"]["amount"], "unknown")
        self.assertNotIn("tier1_failed", res2_missing)
        self.assertEqual(res2_missing["status"], "partial")

        # 2b. tier=1 + 过期证据 (没有效总额) -> 单项 unknown，tier1_failed 不存在，整例保持 partial
        res2_expired = evaluate(
            contract,
            run,
            [
                ev("amount", 300, observed_at=NOW - 5000),
                ev("format", True),
                ev("guard", True),
            ],
            now=NOW,
        )
        self.assertEqual(res2_expired["criteria"]["amount"], "unknown")
        self.assertNotIn("tier1_failed", res2_expired)
        self.assertEqual(res2_expired["status"], "partial")

        # 2c. tier=1 + 被拒证据 -> 单项 unknown，tier1_failed 不存在，整例保持 partial
        res2_rejected = evaluate(
            contract,
            run,
            [ev("amount", 200, ok=False), ev("format", True), ev("guard", True)],
            now=NOW,
        )
        self.assertEqual(res2_rejected["criteria"]["amount"], "unknown")
        self.assertNotIn("tier1_failed", res2_rejected)
        self.assertEqual(res2_rejected["status"], "partial")

        # 3. tier=1 + 互相冲突证据 (给出两个不同总额) -> 单项 conflict，整例 contradicted，不含 tier1_failed
        res3 = evaluate(
            contract,
            run,
            [
                ev("amount", 300, eid="e1"),
                ev("amount", 400, eid="e2"),
                ev("format", True),
                ev("guard", True),
            ],
            now=NOW,
        )
        self.assertEqual(res3["criteria"]["amount"], "conflict")
        self.assertEqual(res3["status"], "contradicted")
        self.assertNotIn("tier1_failed", res3)

        # 4. tier=2 + 有效证据 not_met -> 单项 not_met，整例保持 partial
        res4 = evaluate(
            contract,
            run,
            [ev("amount", 300), ev("format", False), ev("guard", True)],
            now=NOW,
        )
        self.assertEqual(res4["criteria"]["format"], "not_met")
        self.assertEqual(res4["status"], "partial")
        self.assertNotIn("tier1_failed", res4)

        # 5. invariant=True 失败走 violated、之前 met 本次 not_met 走 lost，均不混入 tier1_failed
        # 5a. invariant failure -> violated, not tier1_failed
        res5a = evaluate(
            contract,
            run,
            [ev("amount", 300), ev("format", True), ev("guard", False)],
            now=NOW,
        )
        self.assertEqual(res5a["violated"], ["guard"])
        self.assertNotIn("tier1_failed", res5a)
        self.assertEqual(res5a["status"], "contradicted")

        # 5b. prior met -> now not_met -> lost, not tier1_failed (even for tier 1 criterion)
        prior_res = evaluate(
            contract,
            run,
            [ev("amount", 300), ev("format", True), ev("guard", True)],
            now=NOW,
        )
        self.assertEqual(prior_res["status"], "verified")
        res5b = evaluate(
            contract,
            run,
            [ev("amount", 200), ev("format", True), ev("guard", True)],
            now=NOW + 1,
            previous=prior_res,
        )
        self.assertEqual(res5b["lost"], ["amount"])
        self.assertNotIn("tier1_failed", res5b)
        self.assertEqual(res5b["status"], "contradicted")

    def test_tier1_failed_validation_and_invariant_routing(self) -> None:
        c_t1 = Criterion(
            id="amount",
            subject="report://total",
            metric="total",
            op="eq",
            target=300,
            unit="yuan",
            collectors=("fixture.v1",),
            tier=1,
        )
        c_t2 = Criterion(
            id="format",
            subject="report://format",
            metric="valid",
            op="eq",
            target=True,
            unit="boolean",
            collectors=("fixture.v1",),
            tier=2,
        )
        c_inv = Criterion(
            id="guard",
            subject="report://guard",
            metric="clean",
            op="eq",
            target=True,
            unit="boolean",
            collectors=("fixture.v1",),
            invariant=True,
            tier=1,
        )
        contract = Contract("g_val", 1, (c_t1, c_t2, c_inv))
        run = Run("r_val")

        def ev(cid: str, val: Any, observed_at: int = NOW) -> Evidence:
            c = next(x for x in contract.criteria if x.id == cid)
            return observation(
                id=f"ev_{cid}_{observed_at}",
                goal_id=contract.goal_id,
                revision=contract.revision,
                run_id=run.id,
                attempt=run.attempt,
                call_id=f"call_{cid}_{observed_at}",
                criterion_id=cid,
                collector=c.collectors[0],
                observed_at=observed_at,
                collected_at=observed_at,
                subject=c.subject,
                metric=c.metric,
                value=val,
                unit=c.unit,
            )

        # Invariant with tier=1 routes to violated, not tier1_failed.
        inv_fail = evaluate(
            contract,
            run,
            [ev("amount", 300), ev("format", True), ev("guard", False)],
            now=NOW,
        )
        self.assertEqual(inv_fail["violated"], ["guard"])
        self.assertNotIn("tier1_failed", inv_fail)
        self.assertEqual(inv_fail["status"], "contradicted")

        # Tampering lost snapshot by duplicating lost id into tier1_failed must fail validation.
        prior_met = evaluate(
            contract,
            run,
            [ev("amount", 300), ev("format", True), ev("guard", True)],
            now=NOW,
        )
        regressed = evaluate(
            contract,
            run,
            [ev("amount", 200, observed_at=NOW + 1), ev("format", True, observed_at=NOW + 1)],
            now=NOW + 1,
            previous=prior_met,
        )
        tampered_lost = {**regressed, "tier1_failed": ["amount"]}
        tampered_lost["id"] = fingerprint({k: v for k, v in tampered_lost.items() if k != "id"})
        with self.assertRaises(ValueError):
            validate_result(tampered_lost)
        with self.assertRaises(ValueError):
            decide(tampered_lost)

        # Stripping tier1_failed from a tier-1 baseline snapshot must fail evaluate(previous=...).
        t1_fail = evaluate(
            contract,
            run,
            [ev("amount", 200), ev("format", True), ev("guard", True)],
            now=NOW,
        )
        tampered_stripped = {k: v for k, v in t1_fail.items() if k != "tier1_failed"}
        tampered_stripped["status"] = "partial"
        tampered_stripped["id"] = fingerprint(
            {k: v for k, v in tampered_stripped.items() if k != "id"}
        )
        with self.assertRaises(ValueError):
            evaluate(
                contract,
                run,
                [ev("amount", 300, observed_at=NOW + 1)],
                now=NOW + 1,
                previous=tampered_stripped,
            )

        # Moving a first-run tier-1 failure (progress="unknown") into lost must fail previous check.
        tampered_moved_lost = {
            **{k: v for k, v in t1_fail.items() if k != "tier1_failed"},
            "lost": ["amount"],
        }
        tampered_moved_lost["id"] = fingerprint(
            {k: v for k, v in tampered_moved_lost.items() if k != "id"}
        )
        with self.assertRaises(ValueError):
            evaluate(
                contract,
                run,
                [ev("amount", 300, observed_at=NOW + 1)],
                now=NOW + 1,
                previous=tampered_moved_lost,
            )

        # Ledger readback must enforce the same contract/tier/lost checks as fresh/baseline eval.
        ev_fail = [ev("amount", 200), ev("format", True), ev("guard", True)]
        ev_t2_fail = [ev("amount", 300), ev("format", False), ev("guard", True)]
        contract_hash = t1_fail["contract_hash"]

        for idx, (evs, tampered_patch) in enumerate(
            [
                # (a) strip tier1_failed -> partial on tier-1 failure
                (
                    ev_fail,
                    {
                        **{k: v for k, v in t1_fail.items() if k != "tier1_failed"},
                        "status": "partial",
                    },
                ),
                # (b) inject tier-2 criterion into tier1_failed
                (
                    ev_t2_fail,
                    {
                        **evaluate(contract, run, ev_t2_fail, now=NOW),
                        "status": "contradicted",
                        "tier1_failed": ["format"],
                    },
                ),
                # (c) move tier-1 failure into lost on first run (previous=None)
                (ev_fail, tampered_moved_lost),
            ]
        ):
            with self.subTest(ledger_tamper=idx), tempfile.TemporaryDirectory() as tmp_dir:
                sub_run = Run(f"r_tamper_{idx}")
                db_path = Path(tmp_dir) / "ledger.db"
                ledger = Ledger(db_path)
                sub_evs = [
                    observation(
                        id=x.id,
                        goal_id=x.goal_id,
                        revision=x.revision,
                        run_id=sub_run.id,
                        attempt=sub_run.attempt,
                        call_id=x.call_id,
                        criterion_id=x.criterion_id,
                        collector=x.collector,
                        observed_at=x.observed_at,
                        collected_at=x.collected_at,
                        subject=x.subject,
                        metric=x.metric,
                        value=x.value,
                        unit=x.unit,
                    )
                    for x in evs
                ]
                real_saved = ledger.record(contract, sub_run, sub_evs, now=NOW)
                bad_payload = {
                    **tampered_patch,
                    "run_id": sub_run.id,
                    "evidence": real_saved["evidence"],
                    "contract_hash": contract_hash,
                }
                bad_payload["id"] = fingerprint({k: v for k, v in bad_payload.items() if k != "id"})
                with ledger.conn:
                    ledger.conn.execute(
                        "UPDATE evaluations SET result=? "
                        "WHERE contract_hash=? AND run_id=? AND attempt=?",
                        (canonical(bad_payload), contract_hash, sub_run.id, sub_run.attempt),
                    )
                with self.assertRaises(ValueError):
                    ledger.record(contract, sub_run, sub_evs, now=NOW)
                ledger.close()

        # Ledger readback with non-list evidence type in previous must reject just like evaluate().
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger = Ledger(Path(tmp_dir) / "ledger_prev_type.db")
            run_two = Run("r_prev_type", 2)
            ev_two = [
                observation(
                    id="e2_amount",
                    goal_id=contract.goal_id,
                    revision=contract.revision,
                    run_id=run_two.id,
                    attempt=run_two.attempt,
                    call_id="call2_amount",
                    criterion_id="amount",
                    collector=c_t1.collectors[0],
                    observed_at=NOW + 2,
                    collected_at=NOW + 2,
                    subject=c_t1.subject,
                    metric=c_t1.metric,
                    value=300,
                    unit=c_t1.unit,
                )
            ]
            ledger.record(contract, run_two, ev_two, now=NOW + 2, previous=prior_met)
            bad_prev = {
                **prior_met,
                "evidence": {k: tuple(v) for k, v in prior_met["evidence"].items()},
            }
            with self.assertRaises(ValueError):
                ledger.record(contract, run_two, ev_two, now=NOW + 2, previous=bad_prev)
            ledger.close()


class UpstreamCharacterizationTests(unittest.TestCase):
    """Load the actual stdlib-only upstream store, with no application initialization."""

    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[1] / "nanomuse/goals/store.py"
        spec = importlib.util.spec_from_file_location("goal_eval_upstream_store", path)
        assert spec and spec.loader
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)

    def test_skipping_all_steps_completes_upstream_goal_without_evidence(self) -> None:
        store = self.module.GoalStore(":memory:")
        try:
            goal = store.create("Deliver an accepted report", steps=["Write", "Submit"])
            store.update_step(goal.id, 1, status="skipped")
            goal = store.update_step(goal.id, 2, status="skipped")
            self.assertEqual((goal.progress, goal.status), ("2/2", "done"))
            self.assertEqual(goal.notes, "")
        finally:
            store.close()

    def test_explicit_done_needs_no_finished_steps(self) -> None:
        store = self.module.GoalStore(":memory:")
        try:
            goal = store.create("Deliver an accepted report", steps=["Write"])
            goal = store.set_status(goal.id, "done")
            self.assertEqual((goal.progress, goal.status), ("0/1", "done"))
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
