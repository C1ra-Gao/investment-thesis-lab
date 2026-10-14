"""Offline test runner. --require-real prevents a skipped fixture suite passing."""

import argparse
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-real", action="store_true")
    args = parser.parse_args()
    if args.require_real:
        os.environ["REQUIRE_REAL_REGRESSION"] = "1"
        if not os.environ.get("THESISLAB_PHASE3_ROOT"):
            print("Private Phase 3 root required; refusing synthetic-only success.")
            return 1
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.require_real and result.skipped:
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
