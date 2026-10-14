"""Conservative staged-content gate; never prints matching secrets or values.

This is an offline allowlist/pattern check, not a complete secret/DLP/CVE scanner.
"""

from pathlib import Path
import argparse
import ast
import json
import re
import subprocess
import sys


def findings(path: str, content: bytes, private_values: set[str] | None = None) -> list[str]:
    allowed_exact = {"README.md", ".gitignore", ".env.example", "pyproject.toml", "requirements.lock"}
    allowed_tree = ((path.startswith(("src/", "tests/", "tools/")) and path.endswith(".py"))
                    or (path.startswith("docs/") and path.endswith(".md")))
    issues = []
    if path not in allowed_exact and not allowed_tree:
        issues.append("path_not_in_public_source_allowlist")
    if len(content) > 500_000 or b"\x00" in content:
        return issues + ["large_or_binary_file"]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return issues + ["non_utf8_file"]
    patterns = [r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                r"\bgh[pousr]_[A-Za-z0-9]{30,}\b", r"\bsk-[A-Za-z0-9]{32,}\b",
                r"\bAKIA[0-9A-Z]{16}\b", r"/" + r"Users/[^/\s]+/", r"[A-Za-z]:\\Users\\"]
    if any(re.search(pattern, text) for pattern in patterns):
        issues.append("potential_secret_or_private_user_path")
    normalized = text.replace(",", "")
    if private_values and any(v in normalized for v in private_values):
        issues.append("private_financial_value_present")
    if path.startswith("src/") and path.endswith(".py"):
        tree = ast.parse(text, filename=path)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):imports.append(node.module or "")
        banned = ("requests", "http.client", "urllib.request", "socket", "subprocess", "openai", "keyring")
        if any(name == prefix or name.startswith(prefix + ".") for name in imports for prefix in banned):
            issues.append("network_credential_or_process_client_in_runtime")
    return issues


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-baseline-root", type=Path)
    args = parser.parse_args(argv)
    private = set()
    if args.private_baseline_root:
        data = json.loads((args.private_baseline_root / "final-evidence/verified-numeric-trace.json").read_text())
        private.update(str(c["raw_value"]) for c in data["checks"])
        private.update(str(v) for c in data["calculations"] for k, v in c.items()
                       if k not in ("period", "scope", "derivation"))
    changed = subprocess.check_output(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"])
    paths = [x.decode("utf-8") for x in changed.split(b"\x00") if x]
    if not paths:
        print("No staged source files; nothing audited.")
        return 1
    bad = {}
    for path in paths:
        content = subprocess.check_output(["git", "show", ":" + path])
        issues = findings(path, content, private)
        if issues:bad[path] = issues
    print(json.dumps({"staged_files": len(paths), "findings": bad, "matching_content_printed": False}, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
