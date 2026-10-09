"""Stand-in for the gh CLI: replays recorded responses from a scenario file.

FAKE_GH_SCENARIO points to a JSON file {"calls": [{"args": [...], "stdout": "", "stderr": "",
"exit_code": 0}]}; every invocation is appended to the JSON-lines file FAKE_GH_LOG.
"""

import json
import os
import sys
from pathlib import Path

UNRECORDED_EXIT_CODE = 99


def main() -> int:
    arguments = sys.argv[1:]
    stdin_text = sys.stdin.read()
    with Path(os.environ["FAKE_GH_LOG"]).open("a", encoding="utf-8") as log:
        record = {"args": arguments, "stdin": stdin_text, "gh_host": os.environ.get("GH_HOST")}
        log.write(json.dumps(record) + "\n")
    scenario = json.loads(Path(os.environ["FAKE_GH_SCENARIO"]).read_text(encoding="utf-8"))
    for call in scenario["calls"]:
        if call["args"] == arguments:
            sys.stdout.write(call.get("stdout", ""))
            sys.stderr.write(call.get("stderr", ""))
            return int(call.get("exit_code", 0))
    sys.stderr.write(f"fake gh: no recorded response for {arguments}\n")
    return UNRECORDED_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
