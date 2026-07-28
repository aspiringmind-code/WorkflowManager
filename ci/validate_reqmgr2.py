#!/usr/bin/env python3
"""
validate_reqmgr2.py — sanity-check a ReqMgr2 request JSON before translation.

Not a full JSON-Schema of ReqMgr2 (WMCore doesn't publish one); this checks
the handful of fields the translator actually depends on, and fails fast
with a clear message instead of letting the translator produce a broken
or silently-empty CWL workflow.
"""
import json
import sys

REQUIRED_TOP_LEVEL = ["RequestType", "RequestName", "CMSSWVersion", "GlobalTag"]
REQUIRED_TASK_FIELDS = ["CMSSWVersion", "GlobalTag", "ConfigCacheID"]


def fail(msg):
    print(f"INVALID: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print("usage: validate_reqmgr2.py <input.json>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    try:
        with open(path) as f:
            spec = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"could not read/parse {path}: {exc}")

    for field in REQUIRED_TOP_LEVEL:
        if field not in spec:
            fail(f"missing top-level field '{field}'")

    if spec["RequestType"] not in ("TaskChain", "StepChain"):
        fail(f"unsupported RequestType '{spec['RequestType']}' "
             f"(translator handles TaskChain / StepChain)")

    n_key = "TaskChain" if spec["RequestType"] == "TaskChain" else "StepChain"
    prefix = "Task" if n_key == "TaskChain" else "Step"
    n = spec.get(n_key)
    if not isinstance(n, int) or n < 1:
        fail(f"'{n_key}' must be a positive integer")

    found = 0
    for i in range(1, n + 1):
        key = f"{prefix}{i}"
        task = spec.get(key)
        if not isinstance(task, dict):
            fail(f"declared {n_key}={n} but '{key}' is missing")
        for field in REQUIRED_TASK_FIELDS:
            if field not in task and field not in spec:
                fail(f"'{key}' is missing required field '{field}' "
                     f"(and no top-level default is set)")
        found += 1

    print(f"OK: {path} is a valid {spec['RequestType']} request with {found} task(s).")


if __name__ == "__main__":
    main()
