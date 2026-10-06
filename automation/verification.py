"""Run original tests separately from new agent-supplied regressions."""
import json
import subprocess
import sys
from pathlib import Path
from sandboxed_hermes import run_sandboxed_command


def verify_original_tests(root, baseline):
    files = subprocess.check_output(['git','ls-tree','-r','--name-only',baseline,'tests'],cwd=root,text=True).splitlines()
    modules = [Path(p).stem for p in files if p.startswith('tests/test_') and p.endswith('.py') and '/' not in p[6:]]
    script = ('import sys, unittest; sys.path.insert(0,"tests"); '
              'suite=unittest.defaultTestLoader.loadTestsFromNames('+json.dumps(modules)+'); '
              'result=unittest.TextTestRunner().run(suite); '
              'sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)')
    return bool(modules) and run_sandboxed_command([sys.executable,'-c',script],workspace=root,timeout_seconds=300).returncode == 0


def regression_result(root, modules, *, expect_failure=False):
    script = ('import sys, unittest; sys.path.insert(0,"tests"); '
              'result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames('+json.dumps(modules)+')); '
              'ok = result.testsRun > 0 and ' + ('bool(result.failures) and not result.errors' if expect_failure else 'result.wasSuccessful()') + '; sys.exit(0 if ok else 1)')
    return bool(modules) and run_sandboxed_command([sys.executable,'-c',script],workspace=root,timeout_seconds=90).returncode == 0


def verify_new_regression(candidate, baseline, project_root):
    import continuous_improvement as ci
    from sandboxed_hermes import snapshot_candidate_files
    files = subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=candidate,text=True).splitlines()
    files = [p for p in files if p.startswith('tests/test_auto_') and p.endswith('.py')]
    modules = [Path(p).stem for p in files]
    original = ci._create_worktree(project_root,baseline)
    if not original:
        return False
    try:
        return (snapshot_candidate_files(candidate,original,files)
                and regression_result(original,modules,expect_failure=True)
                and regression_result(candidate,modules))
    finally:
        ci._remove_worktree(project_root,original)
