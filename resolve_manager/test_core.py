import tempfile
import unittest
from pathlib import Path
from core import scan, disable, restore, records, digest, validate_dictionary, SUFFIX

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / '插件'
        self.module = self.root / '测试.ofx.bundle' / 'Contents' / 'Win64' / '测试.ofx'
        self.module.parent.mkdir(parents=True)
        self.module.write_bytes(b'fake module for lifecycle tests\x00\xff')
        self.data = self.base / 'data'
        self.row = scan([self.root])[0][0]

    def tearDown(self): self.temp.cleanup()

    def disable(self): return disable(self.row, self.data, lambda: False)
    def manifest(self): return records(self.data)[0][0]

    def test_scan_deduplicates_roots_and_ignores_other_files(self):
        (self.module.parent / 'helper.dll').write_bytes(b'dependency')
        rows, errors = scan([self.root, self.root / '测试.ofx.bundle'])
        self.assertEqual(len(rows), 1); self.assertFalse(errors)

    def test_disable_and_restore_preserves_binary_and_dependencies(self):
        dep = self.module.parent / 'shared.dll'; dep.write_bytes(b'keep')
        before = digest(self.module)
        self.disable()
        self.assertFalse(self.module.exists()); self.assertTrue(Path(str(self.module)+SUFFIX).exists())
        self.assertTrue(scan([self.root])[0][0]['disabled'])
        restore(self.manifest(), self.data, lambda: False)
        self.assertEqual(digest(self.module), before); self.assertEqual(dep.read_bytes(),b'keep')

    def test_running_resolve_blocks_mutations(self):
        with self.assertRaises(RuntimeError): disable(self.row, self.data, lambda: True)
        self.assertTrue(self.module.exists()); self.assertFalse(records(self.data))

    def test_existing_original_is_not_overwritten(self):
        self.disable(); self.module.write_bytes(b'vendor update')
        with self.assertRaises(FileExistsError): restore(self.manifest(), self.data, lambda: False)
        self.assertEqual(self.module.read_bytes(),b'vendor update')

    def test_modified_disabled_file_blocks_restore(self):
        rec = self.disable(); Path(rec['disabled']).write_bytes(b'changed')
        with self.assertRaises(RuntimeError): restore(self.manifest(), self.data, lambda: False)
        self.assertFalse(self.module.exists())

    def test_damaged_backup_blocks_restore(self):
        rec = self.disable(); Path(rec['backup']).write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError): restore(self.manifest(), self.data, lambda: False)

    def test_missing_disabled_file_can_restore_from_backup(self):
        rec = self.disable(); Path(rec['disabled']).unlink()
        restore(self.manifest(), self.data, lambda: False)
        self.assertEqual(digest(self.module),rec['sha256'])

    def test_wrong_root_cannot_disable(self):
        row = dict(self.row,root=str(self.base/'elsewhere'))
        with self.assertRaises(ValueError): disable(row,self.data,lambda:False)
        self.assertTrue(self.module.exists())

    def test_dictionary_validation(self):
        for value in ([], {'a':4}, {'':'译文'}, {'English':''}):
            with self.assertRaises(ValueError): validate_dictionary(value)
        self.assertEqual(validate_dictionary({'Glow':'辉光'}),{'Glow':'辉光'})

if __name__ == '__main__': unittest.main()
