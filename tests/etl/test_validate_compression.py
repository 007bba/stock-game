import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ETL_PATH = ROOT / "scripts" / "etl"
if str(ETL_PATH) not in sys.path:
    sys.path.insert(0, str(ETL_PATH))

import validate_compression as vc


class TestValidateCompression(unittest.TestCase):
    def test_validate_local_ok(self):
        result = vc.validate_local()
        self.assertTrue(result.ok())
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
