"""Run offline regressions while retaining scratch files as diagnostic evidence."""
import argparse
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    scratch = args.output / "test_scratch"
    scratch.mkdir(exist_ok=True)

    class PreservedDirectory:
        def __init__(self, *unused, **kwargs):
            # All scratch stays in the explicitly selected evidence directory.
            self.name = tempfile.mkdtemp(dir=scratch)

        def __enter__(self):
            return self.name

        def __exit__(self, *unused):
            return False

        def cleanup(self):
            pass

    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(args.tests) if args.tests
             else loader.discover(str(ROOT), pattern="test_*.py"))
    with (args.output / "unittest.txt").open("w", encoding="utf-8") as log:
        original_directory = tempfile.TemporaryDirectory
        with ExitStack() as patches:
            patches.enter_context(patch.object(tempfile, "TemporaryDirectory", PreservedDirectory))
            # 测试模块直接 from tempfile import 的别名也要保留，避免退出时递归清理。
            for module in list(sys.modules.values()):
                if getattr(module, "__name__", "").split(".")[-1].startswith("test_"):
                    for name, value in list(vars(module).items()):
                        if value is original_directory:
                            patches.enter_context(patch.object(module, name, PreservedDirectory))
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    record = {
        "tests_run": result.testsRun,
        "failures": [{"test": str(test), "traceback": trace} for test, trace in result.failures],
        "errors": [{"test": str(test), "traceback": trace} for test, trace in result.errors],
        "skipped": [(str(test), reason) for test, reason in result.skipped],
        "successful": result.wasSuccessful(),
        "scratch_retained": True,
    }
    (args.output / "unittest.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in record.items()
                      if key not in {"failures", "errors", "skipped"}}, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
