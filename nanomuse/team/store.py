"""The squad task ledger: assignments on disk, with guards and a lifecycle.

Phase 4's squad kept its work in memory: frames on a bus, nothing
written down, so a restart lost every trace of what had been handed
out.  This store is the ledger the squad writes to instead, one
SQLite file under the data directory (``squad.db``), with the same
posture as the goals store: one connection, tables created on open,
an append-only event log beside the records it explains.

An *assignment* is one piece of handed-out work: a root task (depth
0) or a child under it, with who it came from (``origin``), what kind
of ask it is (``mode``: ``work`` does something, ``consult`` only
answers, ``notify`` only reports), which role it went to, and the
brief it was given.  This step keeps the book only: assignments are
recorded, guarded, settled and reconciled.  Nothing here runs them;
the specialists still exchange frames exactly as before, and a squad
formed without a store behaves exactly as it did in Phase 4.

Four guards run at enqueue time, and a refusal names its reason:

- the parent must exist and still be open (not settled);
- the new assignment may not be one of its own ancestors, and the
  parent chain may not already loop;
- an open child with the same brief under the same parent is a
  duplicate and is refused;
- depth is capped (2 by default: a root, its children, one level of
  grandchildren is already more than a single-user squad needs).

A root tree may also carry a size cap (``max_per_root``, off by
default).  That cap counts assignments, nothing else: real spend is
counted by the cost ledger and refused by the monthly budget gate,
and the two levels stay separate, the ledger here never guesses at
tokens or money.

The lifecycle is seven states: ``queued``, ``running``, ``waiting``,
``needs_input`` and the three terminal states ``completed``,
``failed``, ``cancelled``.  A terminal state is written once, by
``settle``; a second settle is refused, so a result can never be
rewritten after the fact.  ``result`` is a summary, capped at
``RESULT_LIMIT`` characters with the cut marked; the full text of a
piece of work lives wherever the work itself put it, not in this
ledger.
"""

from __future__ import annotations

import builtins  # ``list`` is a method name below; the class body needs the type
import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

STATUSES = (
    "queued",
    "running",
    "waiting",
    "needs_input",
    "completed",
    "failed",
    "cancelled",
)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
ORIGINS = ("user", "companion", "telegram", "routine")
MODES = ("work", "consult", "notify")
# Where a non-terminal assignment may move next.  Terminal states are
# reached only through settle(), never through transition().
TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"waiting", "needs_input", "cancelled"}),
    "waiting": frozenset({"running", "needs_input", "cancelled"}),
    "needs_input": frozenset({"running", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
RESULT_LIMIT = 2000
_TRUNCATED = " [truncated]"
# The event kind reconcile_on_startup leaves when it spares an
# assignment one restart.  A second startup that still finds the
# assignment open counts these marks and spares it no further.
RETRY_EVENT = "reconcile_retry"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _truncate_result(result: str) -> str:
    if len(result) <= RESULT_LIMIT:
        return result
    return result[: RESULT_LIMIT - len(_TRUNCATED)] + _TRUNCATED


class GuardReason(Enum):
    """Why an enqueue was refused; the caller can branch on this."""

    PARENT_NOT_FOUND = "parent_not_found"
    PARENT_SETTLED = "parent_settled"
    ANCESTOR_CYCLE = "ancestor_cycle"
    DUPLICATE_BRIEF = "duplicate_brief"
    MAX_DEPTH = "max_depth"
    ROOT_BUDGET = "root_budget"


class EnqueueRefused(RuntimeError):
    """A guard refused an enqueue.  ``reason`` says which guard."""

    def __init__(self, reason: GuardReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason


class InvalidTransition(RuntimeError):
    """A status move the lifecycle does not allow."""


class AlreadySettled(RuntimeError):
    """A terminal state was offered for an assignment that has one."""


class AssignmentNotFound(KeyError):
    """No assignment with that id exists in the ledger."""


@dataclass(frozen=True)
class Assignment:
    """One piece of handed-out work, as the ledger keeps it."""

    id: str
    parent_id: str | None
    depth: int
    origin: str
    mode: str
    role: str
    brief: str
    status: str
    outcome: str = ""
    result: str = ""
    level: str = ""
    created_at: str = ""
    settled_at: str = ""

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass(frozen=True)
class AssignmentEvent:
    """One line of the append-only log: what happened, and when."""

    id: int
    assignment_id: str
    kind: str
    detail: str
    at: str


@dataclass(frozen=True)
class ReconcileReport:
    """What one startup reconciliation did, by assignment id."""

    interrupted: list[str]
    retry_marked: list[str]


# An evidence check: did this assignment already act on the outside
# world (sent a message, wrote somewhere, spent money)?  Reconcile
# trusts records, never a task's own account of itself, so the check
# is injected and reads a ledger or an audit file.
EvidenceFn = Callable[[Assignment], bool]


def _no_evidence(assignment: Assignment) -> bool:
    return False


class SquadStore:
    """The squad's task ledger: assignments and their events, on disk."""

    def __init__(
        self,
        path: Path | str,
        *,
        max_depth: int = 2,
        max_per_root: int = 0,
    ) -> None:
        if max_depth < 0:
            raise ValueError("max_depth must be 0 or more")
        if max_per_root < 0:
            raise ValueError("max_per_root must be 0 or more (0 means no cap)")
        self.path = str(path)
        self.max_depth = max_depth
        self.max_per_root = max_per_root
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                parent_id TEXT REFERENCES assignments(id),
                depth INTEGER NOT NULL,
                origin TEXT NOT NULL,
                mode TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                brief TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                outcome TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                level TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                settled_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id TEXT NOT NULL REFERENCES assignments(id),
                kind TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_by_assignment
                ON events (assignment_id, id);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ rows
    @staticmethod
    def _row_to_assignment(row: sqlite3.Row) -> Assignment:
        return Assignment(
            id=row["id"],
            parent_id=row["parent_id"],
            depth=int(row["depth"]),
            origin=row["origin"],
            mode=row["mode"],
            role=row["role"],
            brief=row["brief"],
            status=row["status"],
            outcome=row["outcome"],
            result=row["result"],
            level=row["level"],
            created_at=row["created_at"],
            settled_at=row["settled_at"],
        )

    def get(self, assignment_id: str) -> Assignment | None:
        row = self._conn.execute(
            "SELECT * FROM assignments WHERE id = ?", (assignment_id,)
        ).fetchone()
        return self._row_to_assignment(row) if row else None

    def _require(self, assignment_id: str) -> Assignment:
        found = self.get(assignment_id)
        if found is None:
            raise AssignmentNotFound(assignment_id)
        return found

    def list(self, *, status: str | None = None) -> list[Assignment]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        sql = "SELECT * FROM assignments"
        params: tuple[str, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        rows = self._conn.execute(sql + " ORDER BY created_at, id", params).fetchall()
        return [self._row_to_assignment(row) for row in rows]

    def open_assignments(self) -> builtins.list[Assignment]:
        """Every assignment with no terminal state yet, oldest first."""
        marks = ", ".join("?" for _ in TERMINAL_STATUSES)
        rows = self._conn.execute(
            f"SELECT * FROM assignments WHERE status NOT IN ({marks}) ORDER BY created_at, id",
            tuple(sorted(TERMINAL_STATUSES)),
        ).fetchall()
        return [self._row_to_assignment(row) for row in rows]

    def children(self, parent_id: str) -> builtins.list[Assignment]:
        rows = self._conn.execute(
            "SELECT * FROM assignments WHERE parent_id = ? ORDER BY created_at, id",
            (parent_id,),
        ).fetchall()
        return [self._row_to_assignment(row) for row in rows]

    def events(self, assignment_id: str) -> builtins.list[AssignmentEvent]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE assignment_id = ? ORDER BY id",
            (assignment_id,),
        ).fetchall()
        return [
            AssignmentEvent(
                id=int(row["id"]),
                assignment_id=row["assignment_id"],
                kind=row["kind"],
                detail=row["detail"],
                at=row["at"],
            )
            for row in rows
        ]

    def _append_event(self, assignment_id: str, kind: str, detail: str = "") -> None:
        self._conn.execute(
            "INSERT INTO events (assignment_id, kind, detail, at) VALUES (?, ?, ?, ?)",
            (assignment_id, kind, detail, _now()),
        )

    def append_event(self, assignment_id: str, kind: str, detail: str = "") -> None:
        """Add one line to an assignment's log, from outside the store
        (the startup reconcile writes its verdicts this way)."""
        self._require(assignment_id)
        self._append_event(assignment_id, kind, detail)
        self._conn.commit()

    # ------------------------------------------------------------------ tree
    def _ancestor_ids(self, assignment: Assignment) -> builtins.list[str]:
        """The ids above ``assignment``, parent first, root last.

        A chain that revisits an id is corrupt; the caller decides
        what to refuse, this only reports the loop by raising.
        """
        seen = {assignment.id}
        chain: builtins.list[str] = []
        current = assignment
        while current.parent_id is not None:
            if current.parent_id in seen:
                raise EnqueueRefused(
                    GuardReason.ANCESTOR_CYCLE,
                    f"the parent chain of {assignment.id} loops at {current.parent_id}",
                )
            seen.add(current.parent_id)
            chain.append(current.parent_id)
            parent = self.get(current.parent_id)
            if parent is None:  # a dangling parent: the chain just ends
                break
            current = parent
        return chain

    def root_of(self, assignment: Assignment) -> Assignment:
        chain = self._ancestor_ids(assignment)
        if not chain:
            return assignment
        root = self.get(chain[-1])
        return root if root is not None else assignment

    def tree_size(self, root_id: str) -> int:
        """How many assignments the tree under (and including) a root holds."""
        row = self._conn.execute(
            """
            WITH RECURSIVE tree(id) AS (
                SELECT id FROM assignments WHERE id = ?
                UNION ALL
                SELECT a.id FROM assignments a JOIN tree t ON a.parent_id = t.id
            )
            SELECT COUNT(*) AS n FROM tree
            """,
            (root_id,),
        ).fetchone()
        return int(row["n"])

    def descendant_count(self, root_id: str) -> int:
        return max(0, self.tree_size(root_id) - 1)

    # ------------------------------------------------------------------ enqueue
    @staticmethod
    def _check_fields(origin: str, mode: str, brief: str) -> str:
        if origin not in ORIGINS:
            raise ValueError(f"origin must be one of {ORIGINS}")
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        brief = brief.strip()
        if not brief:
            raise ValueError("an assignment needs a brief")
        return brief

    def _insert(
        self,
        *,
        assignment_id: str,
        parent_id: str | None,
        depth: int,
        origin: str,
        mode: str,
        role: str,
        brief: str,
        level: str,
    ) -> Assignment:
        self._conn.execute(
            "INSERT INTO assignments (id, parent_id, depth, origin, mode, role,"
            " brief, status, outcome, result, level, created_at, settled_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', '', '', ?, ?, '')",
            (assignment_id, parent_id, depth, origin, mode, role, brief, level, _now()),
        )
        self._append_event(assignment_id, "enqueued", f"depth {depth}, mode {mode}")
        self._conn.commit()
        return self._require(assignment_id)

    def create_root(
        self,
        *,
        origin: str,
        brief: str,
        mode: str = "work",
        role: str = "",
        level: str = "",
        assignment_id: str | None = None,
    ) -> Assignment:
        """Open a new task tree.  Roots have no parent, so the parent
        guards do not apply; the fields are still validated."""
        brief = self._check_fields(origin, mode, brief)
        return self._insert(
            assignment_id=assignment_id or "a_" + uuid.uuid4().hex[:12],
            parent_id=None,
            depth=0,
            origin=origin,
            mode=mode,
            role=role,
            brief=brief,
            level=level,
        )

    def enqueue(
        self,
        *,
        parent_id: str,
        origin: str,
        brief: str,
        mode: str = "work",
        role: str = "",
        level: str = "",
        assignment_id: str | None = None,
    ) -> Assignment:
        """Hand work out under an open parent, past the four guards."""
        brief = self._check_fields(origin, mode, brief)
        parent = self.get(parent_id)
        if parent is None:
            raise EnqueueRefused(
                GuardReason.PARENT_NOT_FOUND, f"no assignment {parent_id!r} in the ledger"
            )
        if parent.terminal:
            raise EnqueueRefused(
                GuardReason.PARENT_SETTLED,
                f"parent {parent_id} already settled as {parent.status}",
            )
        new_id = assignment_id or "a_" + uuid.uuid4().hex[:12]
        ancestors = self._ancestor_ids(parent)
        if new_id == parent_id or new_id in ancestors:
            raise EnqueueRefused(
                GuardReason.ANCESTOR_CYCLE,
                f"{new_id} is an ancestor of {parent_id}; work never flows back up",
            )
        if self.get(new_id) is not None:
            raise ValueError(f"assignment {new_id!r} already exists")
        depth = parent.depth + 1
        if depth > self.max_depth:
            raise EnqueueRefused(
                GuardReason.MAX_DEPTH,
                f"depth {depth} passes the cap of {self.max_depth}",
            )
        marks = ", ".join("?" for _ in TERMINAL_STATUSES)
        duplicate = self._conn.execute(
            f"SELECT 1 FROM assignments WHERE parent_id = ? AND brief = ?"
            f" AND status NOT IN ({marks})",
            (parent_id, brief, *sorted(TERMINAL_STATUSES)),
        ).fetchone()
        if duplicate is not None:
            raise EnqueueRefused(
                GuardReason.DUPLICATE_BRIEF,
                f"an open assignment under {parent_id} already carries this brief",
            )
        if self.max_per_root > 0:
            root = self.root_of(parent)
            if self.tree_size(root.id) + 1 > self.max_per_root:
                raise EnqueueRefused(
                    GuardReason.ROOT_BUDGET,
                    f"root {root.id} already holds {self.tree_size(root.id)} assignments"
                    f" of at most {self.max_per_root}",
                )
        return self._insert(
            assignment_id=new_id,
            parent_id=parent_id,
            depth=depth,
            origin=origin,
            mode=mode,
            role=role,
            brief=brief,
            level=level,
        )

    # ------------------------------------------------------------------ lifecycle
    def transition(self, assignment_id: str, new_status: str) -> Assignment:
        """Move an open assignment along the lifecycle graph.

        Terminal states are not reachable here: settle() writes them,
        once, with their outcome.
        """
        current = self._require(assignment_id)
        if new_status in TERMINAL_STATUSES:
            raise InvalidTransition(f"{new_status} is terminal; settle the assignment instead")
        if new_status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if new_status not in TRANSITIONS[current.status]:
            raise InvalidTransition(f"{current.status} may not become {new_status}")
        self._conn.execute(
            "UPDATE assignments SET status = ? WHERE id = ?", (new_status, assignment_id)
        )
        self._append_event(assignment_id, "status", f"{current.status} to {new_status}")
        self._conn.commit()
        return self._require(assignment_id)

    def settle(
        self,
        assignment_id: str,
        status: str,
        *,
        outcome: str = "",
        result: str = "",
    ) -> Assignment:
        """Write the terminal state, exactly once.

        A second settle raises :class:`AlreadySettled` rather than
        overwriting: what a piece of work ended as is a fact of the
        ledger, not a field callers may revise.
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"settle needs a terminal status, one of {sorted(TERMINAL_STATUSES)}")
        current = self._require(assignment_id)
        if current.terminal:
            raise AlreadySettled(
                f"{assignment_id} already settled as {current.status};"
                " a terminal state is written once"
            )
        self._conn.execute(
            "UPDATE assignments SET status = ?, outcome = ?, result = ?, settled_at = ?"
            " WHERE id = ?",
            (status, outcome, _truncate_result(result), _now(), assignment_id),
        )
        self._append_event(assignment_id, "settled", f"{status}: {outcome}" if outcome else status)
        self._conn.commit()
        return self._require(assignment_id)

    def retry_marks(self, assignment_id: str) -> int:
        """How many startups have already spared this assignment once."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE assignment_id = ? AND kind = ?",
            (assignment_id, RETRY_EVENT),
        ).fetchone()
        return int(row["n"])


def reconcile_on_startup(store: SquadStore, evidence: EvidenceFn | None = None) -> ReconcileReport:
    """Settle the ledger's open assignments after a restart, on the record.

    An assignment that already acted on the outside world (the
    injected evidence check says so, from a ledger or an audit file,
    never from the task's own account) is settled ``failed`` with the
    outcome ``interrupted`` and is never run again: repeating it could
    repeat the action.  An assignment with no such evidence is spared
    exactly once, by a retry mark in its events; a later startup that
    still finds it open settles it the same way.  Reconcile only
    writes verdicts in the ledger: it resumes nothing itself.

    With no evidence check supplied, every assignment counts as
    having no evidence.  That is the honest default until a caller
    wires a real one (see :func:`ledger_evidence`).
    """
    check = evidence if evidence is not None else _no_evidence
    interrupted: list[str] = []
    retry_marked: list[str] = []
    for assignment in store.open_assignments():
        if check(assignment):
            store.settle(assignment.id, "failed", outcome="interrupted")
            store.append_event(
                assignment.id,
                "reconcile",
                "interrupted: external action on record, never re-run",
            )
            interrupted.append(assignment.id)
        elif store.retry_marks(assignment.id) >= 1:
            store.settle(assignment.id, "failed", outcome="interrupted")
            store.append_event(
                assignment.id,
                "reconcile",
                "interrupted: already spared one restart, still open",
            )
            interrupted.append(assignment.id)
        else:
            store.append_event(
                assignment.id,
                RETRY_EVENT,
                "no external action on record; may be run once more",
            )
            retry_marked.append(assignment.id)
    return ReconcileReport(interrupted=interrupted, retry_marked=retry_marked)


def ledger_evidence(path: Path | str) -> EvidenceFn:
    """Evidence from the cost ledger: an assignment acted if a call
    was recorded under its own id.

    The persisted ledger (``cost_ledger.jsonl`` in the data
    directory) names the task each model call belonged to.  Paid
    model calls are the one outside action this step can check
    honestly; a message sent or a file written leaves no line there.
    Callers recording squad work must record it under the assignment
    id for this check to see it.  A missing file means no evidence,
    and a line that does not parse is skipped, the posture the cost
    store itself takes.
    """
    ledger_path = Path(path)
    acted: set[str] | None = None

    def check(assignment: Assignment) -> bool:
        nonlocal acted
        if acted is None:
            acted = set()
            if ledger_path.exists():
                for line in ledger_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        acted.add(str(row["task_id"]))
                    except (ValueError, KeyError, TypeError):
                        continue
        return assignment.id in acted

    return check


__all__ = [
    "MODES",
    "ORIGINS",
    "RESULT_LIMIT",
    "STATUSES",
    "TERMINAL_STATUSES",
    "AlreadySettled",
    "Assignment",
    "AssignmentEvent",
    "AssignmentNotFound",
    "EnqueueRefused",
    "EvidenceFn",
    "GuardReason",
    "InvalidTransition",
    "ReconcileReport",
    "SquadStore",
    "ledger_evidence",
    "reconcile_on_startup",
]
