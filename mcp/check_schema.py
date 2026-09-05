"""Drift check: run from the repo root, with the main app importable.

The connector deploys standalone, so it keeps its own narrow copy of the tables
it reads. This compares that copy against the main app's models.py and reports
any table or column that has been renamed or retyped out from under it.

    python mcp/check_schema.py
"""
import sys
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import models as main_models

del sys.modules['models']
spec = importlib.util.spec_from_file_location('mirror_models', HERE / 'models.py')
mirror = importlib.util.module_from_spec(spec); spec.loader.exec_module(mirror)

main_tables = {t.name: t for t in main_models.db.metadata.sorted_tables}
ok = True
for table in mirror.db.metadata.sorted_tables:
    if table.name not in main_tables:
        print('MISSING TABLE:', table.name); ok = False; continue
    src = main_tables[table.name]
    for col in table.columns:
        if col.name not in src.columns:
            print(f'MISSING COLUMN: {table.name}.{col.name}'); ok = False; continue
        a, b = type(col.type).__name__, type(src.columns[col.name].type).__name__
        if a != b:
            print(f'TYPE MISMATCH: {table.name}.{col.name}: mirror={a} main={b}'); ok = False
    extra = set(src.columns.keys()) - set(table.columns.keys())
    print(f'{table.name}: {len(table.columns)} mirrored, not mirrored: {sorted(extra) or "none"}')
print('\nSCHEMA CONSISTENT' if ok else '\nSCHEMA DRIFT')
sys.exit(0 if ok else 1)
