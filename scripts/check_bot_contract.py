"""Prevent deployment of the new API with the legacy bot login/initialization."""
import ast
from pathlib import Path

root=Path(__file__).resolve().parents[1]
tree=ast.parse((root/'bot/main.py').read_text(encoding='utf-8-sig'))
required={'backend.security','backend.search','backend.drafts','backend.lifecycle','backend.notifications','backend.migrations','backend.catalogs','backend.storage'}
imports={node.module for node in tree.body if isinstance(node,ast.ImportFrom)}
missing=required-imports
if missing:
    raise SystemExit('Release blocked: bot/main.py still uses legacy rules. Apply and verify the reviewed bot proposal. Missing shared modules: '+', '.join(sorted(missing)))
for node in tree.body:
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
        continue
    if isinstance(node,ast.If) and ast.unparse(node.test)=="__name__ == '__main__'":
        continue
    for call in ast.walk(node):
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr in {'polling','infinity_polling','start'}:
            raise SystemExit('Release blocked: bot starts a worker or polling at import')
print('Bot/API shared contract checked')
