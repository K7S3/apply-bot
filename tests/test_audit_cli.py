"""Tests for the audit/undo CLI commands (candid batch 75).

Run: CANDID_DATA_DIR=/tmp/candid-test-audit-cli python3 -m pytest tests/test_audit_cli.py -q

candid/audit.py and candid/undo.py are built by sibling workers and are not
in this worktree yet, so this file installs faithful in-memory stubs for
``candid.audit`` and ``candid.undo`` implementing the documented API:

  audit: record, read, search, stats, export_csv, export_markdown,
         prune, verify, get
  undo:  undo(entry_id) -> dict, UndoError

The stubs honor the real integration contract: tracker.add/update/remove
call ``audit.record(actor, command, entity, entity_id, action, before, after)``
best-effort, so driving the real ``track`` CLI commands produces audit
entries, and ``undo`` restores against the real tracker file end-to-end.
"""
import contextlib
import csv
import io
import json
import os
import re
import secrets
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-audit-cli"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import candid  # noqa: E402
from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402

REQUIRED_KEYS = {"id", "ts", "actor", "command", "entity",
                 "entity_id", "action", "changes", "note"}


# ---------------------------------------------------------------------------
# stub modules (stand-ins for the sibling-built candid/audit.py, candid/undo.py)
# ---------------------------------------------------------------------------

_MISSING = object()


def _build_audit_stub():
    mod = types.ModuleType("candid.audit")
    mod.entries = []

    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _diff(before, after):
        # field-level diff like the real module: [{field, old, new}]
        before = before or {}
        after = after or {}
        changes = []
        for k in sorted(set(before) | set(after)):
            b = before.get(k, None) if k in before else _MISSING
            a_ = after.get(k, None) if k in after else _MISSING
            if b is _MISSING or a_ is _MISSING or b != a_:
                changes.append({
                    "field": k,
                    "old": None if b is _MISSING else b,
                    "new": None if a_ is _MISSING else a_,
                })
        return changes

    def record(*, actor, command, entity, entity_id, action,
               before=None, after=None, note="", ts=None):
        entry = {
            "id": secrets.token_hex(4),  # 8 hex chars, like the real module
            "ts": ts or _now(),
            "actor": actor,
            "command": command,
            "entity": entity,
            "entity_id": str(entity_id),
            "action": action,
            "before": dict(before) if before else None,
            "after": dict(after) if after else None,
            "changes": _diff(before, after),
            "note": note,
        }
        mod.entries.append(entry)
        return entry

    def read(limit=50, since=None, until=None, entity=None,
             action=None, entity_id=None):
        rows = list(mod.entries)
        if entity is not None:
            rows = [e for e in rows if e.get("entity") == entity]
        if action is not None:
            rows = [e for e in rows if e.get("action") == action]
        if entity_id is not None:
            rows = [e for e in rows if str(e.get("entity_id")) == str(entity_id)]
        if since is not None:
            rows = [e for e in rows if str(e.get("ts", ""))[:10] >= since]
        if until is not None:
            rows = [e for e in rows if str(e.get("ts", ""))[:10] <= until]
        if limit is not None and limit >= 0:
            rows = rows[-limit:]
        return rows

    def search(query):
        q = query.lower()
        return [e for e in mod.entries if q in json.dumps(e, default=str).lower()]

    def stats():
        by_day, by_action, by_entity = {}, {}, {}
        for e in mod.entries:
            day = str(e.get("ts", ""))[:10]
            by_day[day] = by_day.get(day, 0) + 1
            by_action[e.get("action")] = by_action.get(e.get("action"), 0) + 1
            by_entity[e.get("entity")] = by_entity.get(e.get("entity"), 0) + 1
        return {"total": len(mod.entries), "by_day": by_day,
                "by_action": by_action, "by_entity": by_entity}

    def export_csv(path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "ts", "actor", "command", "entity",
                        "entity_id", "action", "changes", "note"])
            for e in mod.entries:
                w.writerow([e["id"], e["ts"], e["actor"], e["command"],
                            e["entity"], e["entity_id"], e["action"],
                            json.dumps(e["changes"], default=str), e["note"]])
        return str(p)

    def export_markdown(path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Audit log", "",
                 "| id | ts | actor | command | entity | entity_id | action | note |",
                 "|---|---|---|---|---|---|---|---|"]
        for e in mod.entries:
            lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                e["id"], e["ts"], e["actor"], e["command"], e["entity"],
                e["entity_id"], e["action"], (e["note"] or "").replace("|", "\\|")))
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(p)

    def prune(older_than_days, dry_run=True):
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=older_than_days)).isoformat()
        kept = [e for e in mod.entries if str(e.get("ts", "")) >= cutoff]
        pruned = [e for e in mod.entries if str(e.get("ts", "")) < cutoff]
        result = {"total": len(mod.entries), "kept": len(kept),
                  "pruned": len(pruned), "dry_run": dry_run}
        if not dry_run:
            mod.entries = kept
        return result

    def verify():
        problems = []
        seen = set()
        for e in mod.entries:
            missing = REQUIRED_KEYS - set(e.keys())
            if missing:
                problems.append(
                    f"entry #{e.get('id', '?')}: missing keys: "
                    f"{', '.join(sorted(missing))}")
            eid = e.get("id")
            if eid in seen:
                problems.append(f"entry #{eid}: duplicate id")
            seen.add(eid)
            ts = str(e.get("ts", ""))
            try:
                datetime.fromisoformat(ts)
            except ValueError:
                problems.append(f"entry #{eid}: bad timestamp {ts!r}")
        return problems

    def get(entry_id):
        for e in mod.entries:
            if e.get("id") == entry_id:
                return e
        return None

    def reset():
        mod.entries = []

    for name, fn in (("record", record), ("read", read), ("search", search),
                     ("stats", stats), ("export_csv", export_csv),
                     ("export_markdown", export_markdown), ("prune", prune),
                     ("verify", verify), ("get", get), ("reset", reset)):
        setattr(mod, name, fn)
    return mod


def _build_undo_stub():
    mod = types.ModuleType("candid.undo")

    class UndoError(Exception):
        """Raised when an undo cannot be performed."""

    def undo(entry_id):
        # Mirrors the real module: restores the tracker record from the
        # entry's before/after snapshots and returns the new "undo" entry.
        from candid import audit as A
        e = A.get(entry_id)
        if not isinstance(e, dict):
            raise UndoError(
                f"Unknown audit entry id {entry_id!r}. "
                "Run `python -m candid audit log` to see valid ids.")
        if e.get("entity") != "tracker":
            raise UndoError(
                f"Cannot undo audit entry {e.get('id')!r}: "
                f"entity {e.get('entity')!r} is not undoable.")
        action, eid = e.get("action"), str(e.get("entity_id"))
        p = Path(C.TRACKER_PATH)
        apps = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        before_now = next((dict(a) for a in apps
                           if str(a.get("id")) == eid), None)
        if action == "update":
            target = e.get("before")
            if target is None:
                raise UndoError("No 'before' snapshot to restore.")
            apps = [target if str(a.get("id")) == eid else a for a in apps]
            restored = target
        elif action == "create":
            apps = [a for a in apps if str(a.get("id")) != eid]
            restored = None
        elif action == "delete":
            target = e.get("before")
            if target is None:
                raise UndoError("No 'before' snapshot to restore.")
            apps.append(target)
            restored = target
        else:
            raise UndoError(f"Cannot undo action {action!r}.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(apps, indent=2), encoding="utf-8")
        return A.record(actor="cli", command="undo", entity="tracker",
                        entity_id=eid, action="undo",
                        before=before_now, after=restored,
                        note=f"undo of audit entry {e.get('id')}")

    mod.UndoError = UndoError
    mod.undo = undo
    return mod


# ---------------------------------------------------------------------------
# test base
# ---------------------------------------------------------------------------

class AuditCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-audit-cli-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()

        self._audit_stub = _build_audit_stub()
        self._undo_stub = _build_undo_stub()
        self._saved_mods = {}
        for dotted, stub in (("candid.audit", self._audit_stub),
                             ("candid.undo", self._undo_stub)):
            self._saved_mods[dotted] = sys.modules.get(dotted)
            sys.modules[dotted] = stub
            setattr(candid, dotted.split(".")[1], stub)

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)
        for dotted, prev in self._saved_mods.items():
            short = dotted.split(".")[1]
            if prev is None:
                sys.modules.pop(dotted, None)
                if getattr(candid, short, None) is not None and \
                        sys.modules.get(dotted) is None:
                    try:
                        delattr(candid, short)
                    except AttributeError:
                        pass
            else:
                sys.modules[dotted] = prev
                setattr(candid, short, prev)

    def run_cli(self, argv):
        """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def add_app(self, company="Acme", role="Data Scientist", status="applied"):
        code, out, _ = self.run_cli(
            ["track", "add", "--company", company, "--role", role,
             "--status", status])
        self.assertEqual(code, 0, out)
        return out

    def last_entry_id(self):
        return self._audit_stub.entries[-1]["id"]


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

class RegistrationTest(AuditCLIBase):
    def test_commands_registered(self):
        self.assertIn("audit", CLI.COMMANDS)
        self.assertIn("undo", CLI.COMMANDS)
        self.assertEqual(CLI.SUBCOMMANDS["audit"],
                         ["log", "search", "stats", "export", "prune", "verify"])

    def test_undo_error_wiring(self):
        self.assertIn("UndoError", CLI._EXPECTED_ERRORS)
        self.assertEqual(CLI._NEXT_COMMAND["UndoError"],
                         "python -m candid audit log")


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------

class AuditLogTest(AuditCLIBase):
    def test_log_empty(self):
        code, out, _ = self.run_cli(["audit", "log"])
        self.assertEqual(code, 0)
        self.assertIn("No audit entries", out)

    def test_track_add_shows_in_log(self):
        self.add_app()
        code, out, _ = self.run_cli(["audit", "log"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"#[0-9a-f]{8}")  # real-style hex entry id
        self.assertIn("create", out)
        self.assertIn("tracker/1", out)

    def test_track_update_shows_changes(self):
        self.add_app(status="applied")
        code, out, _ = self.run_cli(
            ["track", "update", "1", "--status", "selected_for_interview"])
        self.assertEqual(code, 0, out)
        code, out, _ = self.run_cli(["audit", "log", "--action", "update"])
        self.assertEqual(code, 0)
        self.assertIn("update", out)
        self.assertIn("status: applied -> selected_for_interview", out)

    def test_log_filters_narrow_results(self):
        self.add_app(company="Acme")
        self.add_app(company="Globex")
        self.run_cli(["track", "update", "1", "--status", "rejected"])
        code, out, _ = self.run_cli(["audit", "log", "--action", "create"])
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("create", line)
            self.assertNotIn("  update ", line)
        # entity filter that matches nothing
        code, out, _ = self.run_cli(["audit", "log", "--entity", "offer"])
        self.assertEqual(code, 0)
        self.assertIn("No audit entries", out)
        # entity-id filter
        code, out, _ = self.run_cli(["audit", "log", "--entity-id", "2"])
        self.assertEqual(code, 0)
        self.assertIn("tracker/2", out)
        self.assertNotIn("tracker/1", out)

    def test_log_since_until_filters(self):
        self._audit_stub.record(actor="cli", command="track add",
                                entity="tracker", entity_id="9",
                                action="create", before=None,
                                after={"id": 9}, ts="2020-05-01T10:00:00+00:00")
        self.add_app()
        code, out, _ = self.run_cli(["audit", "log", "--since", "2026-01-01"])
        self.assertEqual(code, 0)
        self.assertNotIn("tracker/9", out)
        self.assertIn("tracker/1", out)
        code, out, _ = self.run_cli(["audit", "log", "--until", "2020-12-31"])
        self.assertEqual(code, 0)
        self.assertIn("tracker/9", out)
        self.assertNotIn("tracker/1", out)

    def test_log_limit(self):
        for i in range(5):
            self.add_app(company=f"Co{i}", role=f"Role{i}")
        code, out, _ = self.run_cli(["audit", "log", "--limit", "2"])
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[-1], r"#[0-9a-f]{8}")

    def test_log_json_parses(self):
        self.add_app()
        code, out, _ = self.run_cli(["audit", "log", "--json"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 1)
        for key in REQUIRED_KEYS:
            self.assertIn(key, rows[0])


# ---------------------------------------------------------------------------
# search / stats
# ---------------------------------------------------------------------------

class AuditSearchStatsTest(AuditCLIBase):
    def test_search_finds(self):
        self.add_app(company="Acme")
        self.run_cli(["track", "update", "1", "--status", "selected_for_interview"])
        code, out, _ = self.run_cli(["audit", "search", "acme"])
        self.assertEqual(code, 0)
        self.assertIn("create", out)
        code, out, _ = self.run_cli(["audit", "search", "selected_for_interview"])
        self.assertEqual(code, 0)
        self.assertIn("update", out)
        code, out, _ = self.run_cli(["audit", "search", "no-such-thing-xyz"])
        self.assertEqual(code, 0)
        self.assertIn("No audit entries match", out)

    def test_search_json(self):
        self.add_app(company="Acme")
        code, out, _ = self.run_cli(["audit", "search", "acme", "--json"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "create")

    def test_stats_counts(self):
        self.add_app(company="Acme")
        self.add_app(company="Globex")
        self.run_cli(["track", "update", "1", "--status", "rejected"])
        code, out, _ = self.run_cli(["audit", "stats"])
        self.assertEqual(code, 0)
        self.assertIn("Audit log: 3 entries", out)
        self.assertIn("By day (last 14):", out)
        self.assertIn("By action:", out)
        self.assertIn("create: 2", out)
        self.assertIn("update: 1", out)
        self.assertIn("By entity:", out)
        self.assertIn("tracker: 3", out)

    def test_stats_json(self):
        self.add_app()
        code, out, _ = self.run_cli(["audit", "stats", "--json"])
        self.assertEqual(code, 0)
        s = json.loads(out)
        self.assertEqual(s["total"], 1)
        self.assertEqual(s["by_action"]["create"], 1)
        self.assertEqual(s["by_entity"]["tracker"], 1)
        today = datetime.now(timezone.utc).date().isoformat()
        self.assertEqual(s["by_day"].get(today), 1)


# ---------------------------------------------------------------------------
# export / prune / verify
# ---------------------------------------------------------------------------

class AuditExportPruneVerifyTest(AuditCLIBase):
    def test_export_csv(self):
        self.add_app(company="Acme")
        dest = str(self.tmp / "audit.csv")
        code, out, _ = self.run_cli(["audit", "export", "--csv", dest])
        self.assertEqual(code, 0)
        self.assertIn(dest, out)
        with open(dest, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][:3], ["id", "ts", "actor"])
        self.assertEqual(len(rows), 2)  # header + 1 entry

    def test_export_md(self):
        self.add_app(company="Acme")
        dest = str(self.tmp / "audit.md")
        code, out, _ = self.run_cli(["audit", "export", "--md", dest])
        self.assertEqual(code, 0)
        self.assertIn(dest, out)
        text = Path(dest).read_text(encoding="utf-8")
        self.assertIn("# Audit log", text)
        self.assertIn("| id | ts |", text)
        self.assertIn("create", text)

    def test_prune_dry_run_keeps_entries(self):
        self._audit_stub.record(actor="cli", command="track add",
                                entity="tracker", entity_id="9",
                                action="create", before=None, after={"id": 9},
                                ts="2020-05-01T10:00:00+00:00")
        code, out, _ = self.run_cli(["audit", "prune", "--older-than", "30"])
        self.assertEqual(code, 0)
        self.assertIn("Would prune 1", out)
        self.assertIn("--yes", out)
        # dry run: entry still there
        code, out, _ = self.run_cli(["audit", "log"])
        self.assertIn("tracker/9", out)

    def test_prune_yes_removes(self):
        self._audit_stub.record(actor="cli", command="track add",
                                entity="tracker", entity_id="9",
                                action="create", before=None, after={"id": 9},
                                ts="2020-05-01T10:00:00+00:00")
        self.add_app()
        code, out, _ = self.run_cli(
            ["audit", "prune", "--older-than", "30", "--yes"])
        self.assertEqual(code, 0)
        self.assertIn("Pruned 1", out)
        code, out, _ = self.run_cli(["audit", "log"])
        self.assertNotIn("tracker/9", out)
        self.assertIn("tracker/1", out)

    def test_verify_ok(self):
        self.add_app()
        code, out, _ = self.run_cli(["audit", "verify"])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_verify_problems_exit_nonzero(self):
        self.add_app()
        self._audit_stub.entries.append({"id": 999, "ts": "not-a-date"})
        code, out, _ = self.run_cli(["audit", "verify"])
        self.assertNotEqual(code, 0)
        self.assertIn("problem", out)
        self.assertIn("missing keys", out)


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------

class UndoTest(AuditCLIBase):
    def test_undo_restores_tracker_update(self):
        self.add_app(status="applied")
        self.run_cli(["track", "update", "1",
                      "--status", "selected_for_interview"])
        update_id = self.last_entry_id()
        code, out, _ = self.run_cli(["undo", update_id])
        self.assertEqual(code, 0, out)
        self.assertIn(f"undo of audit entry {update_id}", out)
        self.assertIn("audit log", out)  # next-step hint
        from candid import tracker as T
        rec = next(a for a in T.list_apps() if a["id"] == 1)
        self.assertEqual(rec["status"], "applied")

    def test_undo_create_removes_application(self):
        self.add_app()
        create_id = self.last_entry_id()
        code, out, _ = self.run_cli(["undo", create_id])
        self.assertEqual(code, 0, out)
        self.assertIn("undo of audit entry", out)
        from candid import tracker as T
        self.assertEqual(T.list_apps(), [])

    def test_undo_unknown_id_exits_nonzero(self):
        code, out, err = self.run_cli(["undo", "424242"])
        self.assertNotEqual(code, 0)
        self.assertIn("Error", err)
        self.assertIn("python -m candid audit log", err)


# ---------------------------------------------------------------------------
# help epilogs (repo UX convention: every command/subcommand shows examples)
# ---------------------------------------------------------------------------

class AuditHelpTest(AuditCLIBase):
    def test_help_epilogs(self):
        for argv in (["audit", "--help"], ["undo", "--help"]):
            code, out, _ = self.run_cli(argv)
            self.assertEqual(code, 0, argv)
            self.assertIn("examples:", out, argv)
        for sub in CLI.SUBCOMMANDS["audit"]:
            code, out, _ = self.run_cli(["audit", sub, "--help"])
            self.assertEqual(code, 0, sub)
            self.assertIn("examples:", out, sub)


if __name__ == "__main__":
    unittest.main()
