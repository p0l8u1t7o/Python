"""Compatibility entry point; preserve the existing XLSX and update using artifact-tool."""
from pathlib import Path
import os, shutil, subprocess
script=Path(__file__).with_name("update_cost_estimate.mjs")
node=os.environ.get("NODE_BINARY") or shutil.which("node")
if not node:
    node=str(Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
raise SystemExit(subprocess.call([node,str(script)]))
