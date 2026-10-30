from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import compatibility as c

class CompatibilityTests(unittest.TestCase):
    def test_unknown_binary_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError,'插件版本'):
            c.ensure_compatible({'path':'unknown.ofx'},'unknown',Path('unused'))

    def test_wrong_filename_is_blocked_even_for_known_hash(self):
        known=next(iter(c.TESTED_MODULES))
        with self.assertRaisesRegex(RuntimeError,'插件版本'):
            c.ensure_compatible({'path':'renamed.ofx'},known,Path('unused'))

    def test_legacy_template_blocked_and_valid_template_accepted(self):
        known,name=next(iter(c.TESTED_MODULES.items()))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'proxy.ofx';path.write_bytes(b'old-template')
            with patch.object(Path,'is_file',return_value=True),patch.object(c,'digest',return_value=c.TESTED_RESOLVE_SHA256):
                with self.assertRaisesRegex(RuntimeError,'旧版'):
                    c.ensure_compatible({'path':name},known,path)
                path.write_bytes(b'MZ'+c.ADAPTER_MARKER)
                c.ensure_compatible({'path':name},known,path)

    def test_unknown_host_is_blocked(self):
        known,name=next(iter(c.TESTED_MODULES.items()))
        with patch.object(Path,'is_file',return_value=True),patch.object(c,'digest',return_value='different-host'):
            with self.assertRaisesRegex(RuntimeError,'达芬奇版本'):
                c.ensure_compatible({'path':name},known,Path('unused'))

if __name__=='__main__':unittest.main()
