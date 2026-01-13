import json
import subprocess
import sys
from pathlib import Path

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./nodeA")

proc = subprocess.Popen(
    ["lb", "--data", str(DATA), "run-mcp"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
)

def call(method, params=None, rid=1):
    req = {"id": rid, "method": method, "params": params or {}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)

print(call("initialize"))
print(call("list_groups", rid=2))

proc.terminate()
