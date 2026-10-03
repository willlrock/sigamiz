"""Validated, reversible source edits used while applying the audit."""
import ast
import difflib
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def save(relative, content, emit_patch=False):
    path = (ROOT / relative).resolve()
    assert path.is_relative_to(ROOT) and path.suffix in ('.py', '.html', '.sql', '.txt', '.md', '.yml', '.js', '.css')
    if path.suffix == '.py':
        compile(content, str(path), 'exec')
    if path.exists():
        backup = ROOT / 'audit/2026-10-02/before' / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    if emit_patch:
        old = path.read_text(encoding='utf-8') if path.exists() else ''
        if path.exists():
            print('*** Begin Patch\n*** Update File: ' + relative + '\n@@\n' + '\n'.join('-' + line for line in old.splitlines()) + '\n' + '\n'.join('+' + line for line in content.splitlines()) + '\n*** End Patch')
        else:
            print('*** Begin Patch\n*** Add File: ' + relative + '\n' + '\n'.join('+' + line for line in content.splitlines()) + '\n*** End Patch')
    else:
        path.write_text(content, encoding='utf-8')

def replace_function(text, name, replacement):
    node = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    start = min([node.lineno, *[d.lineno for d in node.decorator_list]]) - 1
    lines = text.splitlines()
    result = '\n'.join(lines[:start] + ([replacement] if replacement else []) + lines[node.end_lineno:]) + '\n'
    compile(result, '<edited source>', 'exec')
    return result

def function_patch(relative, name, replacement):
    text = (ROOT / relative).read_text(encoding='utf-8')
    node = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    start = min([node.lineno, *[d.lineno for d in node.decorator_list]]) - 1
    old = '\n'.join(text.splitlines()[start:node.end_lineno])
    compile(replace_function(text, name, replacement), relative, 'exec')
    print('*** Begin Patch\n*** Update File: ' + relative + '\n@@\n' + '\n'.join('-' + line for line in old.splitlines()) + '\n' + '\n'.join('+' + line for line in replacement.splitlines()) + '\n*** End Patch')

def diff_patch(relative, content):
    old=(ROOT/relative).read_text(encoding='utf-8')
    if relative.endswith('.py'):
        compile(content,relative,'exec')
    lines=list(difflib.unified_diff(old.splitlines(),content.splitlines(),n=3))[2:]
    if lines:
        print('*** Begin Patch\n*** Update File: '+relative+'\n'+'\n'.join('@@' if line.startswith('@@ ') else line for line in lines)+'\n*** End Patch')

def replace_js_function(text,name,replacement):
    import re
    lines=text.splitlines()
    start=next(i for i,line in enumerate(lines) if re.match(r'(async )?function '+re.escape(name)+r'\(',line))
    end=start if lines[start].rstrip().endswith('}') else next(i for i in range(start+1,len(lines)) if lines[i]=='}')
    assert not any(re.match(r'(async )?function ',line) for line in lines[start+1:end])
    return '\n'.join(lines[:start]+[replacement]+lines[end+1:])+'\n'
