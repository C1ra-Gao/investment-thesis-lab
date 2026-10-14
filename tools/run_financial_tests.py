"""M4 offline suite: deny network and subprocesses; retain scratch files in project."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    folder=ROOT/'.local/m4-test-tmp';folder.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(folder);tempfile.TemporaryDirectory.cleanup=lambda self:self._finalizer.detach()
    names=['tests.test_financial_tools','tests.test_finance','tests.test_conflicts','tests.test_domain',
        'tests.test_store','tests.test_research','tests.test_safety','tests.test_local_corpus','tests.test_orchestrator']
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
    with (patch('socket.socket.connect',side_effect=AssertionError('M4 prohibits network')),
          patch('subprocess.run',side_effect=AssertionError('M4 prohibits credentials/process tools'))):
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':sys.exit(main())
