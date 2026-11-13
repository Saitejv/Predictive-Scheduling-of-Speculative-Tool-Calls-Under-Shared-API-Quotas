import subprocess
import sys
import unittest


class BaselineDependenciesTests(unittest.TestCase):
    def test_import_does_not_load_historical_experiment_drivers(self):
        code = """
import sys
import quota_spec.hotpot_runtime
import quota_spec.stage_export
retired = ('paper', 'collect_qa', 'experiments', 'replay', 'prediction', 'admission', 'qa')
assert not [name for name in retired if 'quota_spec.' + name in sys.modules]
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
