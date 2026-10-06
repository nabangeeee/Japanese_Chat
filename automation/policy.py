"""Small automatic fixes only; larger changes retain manual approval."""
import ast
import copy
import re
import os
import subprocess
from pathlib import Path

ALLOWED_FUNCTIONS = {'clean_japanese_text', 'clean_translation_text'}


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', *args], cwd=root, text=True, env={**os.environ, 'GIT_OPTIONAL_LOCKS':'0'})


def allowed_candidate(root: Path, baseline: str) -> bool:
    paths = git(root, 'diff', '--no-ext-diff', '--no-textconv', '--name-only', baseline).splitlines()
    paths += git(root, 'ls-files', '--others', '--exclude-standard').splitlines()
    if not paths or len(set(paths)) > 4:
        return False
    size = git(root, 'diff', '--no-ext-diff', '--no-textconv', '--numstat', baseline)
    try:
        if sum(int(x) for line in size.splitlines() for x in line.split('\t')[:2]) > 160:
            return False
        has_test = False
        production = False
        for name in set(paths):
            path = root / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
                return False
            if re.fullmatch(r'tests/test_auto_[a-z0-9_]+\.py', name):
                if subprocess.run(['git','cat-file','-e',f'{baseline}:{name}'],cwd=root,capture_output=True).returncode == 0:
                    return False  # Existing regression tests cannot be weakened.
                if len(path.read_text().splitlines()) > 160:
                    return False
                ast.parse(path.read_text())
                has_test = True
            elif name == 'main.py':
                old = ast.parse(git(root, 'show', baseline + ':main.py'))
                new = ast.parse(path.read_text())
                if len(old.body) != len(new.body):
                    return False
                for a, b in zip(old.body, new.body):
                    if ast.dump(a) == ast.dump(b):
                        continue
                    if not (isinstance(a, ast.FunctionDef) and isinstance(b, ast.FunctionDef)
                            and a.name == b.name and a.name in ALLOWED_FUNCTIONS
                            and ast.dump(a.args) == ast.dump(b.args)
                            and not b.decorator_list):
                        return False
                    signature = copy.deepcopy(b)
                    signature.body = a.body
                    if ast.dump(signature) != ast.dump(a):
                        return False
                    locals_ = {'text'} | {n.id for n in ast.walk(b) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                    if locals_ & {'re', 'str', 'len', 'range', 'enumerate'}:
                        return False
                    for node in ast.walk(b):
                        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in locals_ | {'re','str','len','range','enumerate'}:
                            return False
                        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
                            return False
                        if isinstance(node, ast.Attribute) and node.attr.startswith('_'):
                            return False
                        if isinstance(node, (ast.ClassDef, ast.Lambda, ast.AsyncFunctionDef)):
                            return False
                        if isinstance(node, ast.FunctionDef) and node is not b:
                            return False
                    # Formatting functions must remain pure: no calls into auth,
                    # persistence, imports, I/O or dynamic execution.
                    for node in ast.walk(b):
                        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                            return False
                        if isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name) and node.func.id not in {'str','len','range','enumerate'}:
                                return False
                            if isinstance(node.func, ast.Attribute):
                                if node.func.attr not in {'sub','search','match','findall','strip','replace','split','join','startswith','endswith','lower','upper','group'}:
                                    return False
                production = True
            elif name == 'static/style.css':
                if re.search(r'url\s*\(|@import|expression\s*\(|javascript:', path.read_text(), re.I):
                    return False
                production = True
            else:
                return False
        return has_test and production
    except (SyntaxError, ValueError, OSError):
        return False
