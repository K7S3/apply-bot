"""Coordinator-level guarantee: the drafting package can never send email.

AST-scans every module in candid/drafting/ and candid/drafts.py for
send-capable imports/calls (docstrings stripped). Fails closed.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BANNED_MODULES = {"smtplib", "socket", "requests", "urllib", "http", "email"}
BANNED_ATTRS = {"sendmail", "send_message", "send_bytes", "SMTP", "SMTP_SSL"}


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return tree


def _violations(path):
    tree = _strip_docstrings(ast.parse(path.read_text()))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in BANNED_MODULES:
                    found.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in BANNED_MODULES:
                found.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS:
                found.append(f".{node.attr}")
    return found


class NoSendTest(unittest.TestCase):
    def test_no_send_capability(self):
        targets = list((ROOT / "candid" / "drafting").glob("*.py"))
        targets.append(ROOT / "candid" / "drafts.py")
        self.assertTrue(targets, "no drafting modules found")
        bad = {}
        for t in targets:
            v = _violations(t)
            if v:
                bad[t.name] = v
        self.assertEqual(bad, {}, f"send-capable code found: {bad}")


if __name__ == "__main__":
    unittest.main()
