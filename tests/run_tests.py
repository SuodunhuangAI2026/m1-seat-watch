#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零依赖测试运行器。用法：python tests/run_tests.py"""
import importlib.util
import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# CI 上 stdout 未必是 UTF-8，中文断言消息打不出来会让失败原因变成一堆乱码
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    passed = failed = 0
    for path in sorted(HERE.glob("test_*.py")):
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            # 模块级 import 失败：用 GitHub Actions 注解，这样 annotations API 能读到
            tb = traceback.format_exc()
            print(f"::error file={path.name},title=import failed::{type(e).__name__}: {e}")
            print(tb)
            failed += 1
            continue
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print(f"  PASS  {path.stem}::{name}")
            except Exception as e:
                failed += 1
                print(f"::error file={path.name},title={name}::{type(e).__name__}: {e}")
                print(f"  FAIL  {path.stem}::{name}: {type(e).__name__}: {e}")
                traceback.print_exc()
    if failed:
        print(f"\n{passed} passed, {failed} FAILED")
    else:
        print(f"\n{passed} passed, 0 failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
