import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codex_hermes_loop import run_codex_hermes_self_healing_loop

scratch_dir = os.path.dirname(os.path.abspath(__file__))
target_file = os.path.join(scratch_dir, "buggy_target.py")
test_cmd = f".venv/bin/python {target_file}"

print("🚀 Starting Codex + Hermes Self-Healing Test...")
res = run_codex_hermes_self_healing_loop(target_file=target_file, test_cmd=test_cmd, max_iterations=2)
print("Final Self-Healing Test Result:", res)

# Check repaired code
with open(target_file, "r", encoding="utf-8") as f:
    print("\n[Repaired Code Content]:\n", f.read())
