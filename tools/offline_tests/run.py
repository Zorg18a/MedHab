"""Запуск тестов без установленного pytest (офлайн-среда): python tools/offline_tests/run.py tests [файл.py ...] [-k часть_имени]
Поддерживает только то, что нужно этим тестам: fixture (scope, autouse, yield), parametrize, tmp_path, request, skip, raises (с .value), mark.skipif.
Настоящий pytest предпочтительнее: python -m pytest tests."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest   # это pytest.py рядом: подмена
args = [a for a in sys.argv[1:] if not a.startswith("-k")]
only = None
if "-k" in sys.argv:
    only = sys.argv[sys.argv.index("-k") + 1]; args = [a for a in args if a != only]
sys.exit(pytest.main(args or ["tests"], only))
