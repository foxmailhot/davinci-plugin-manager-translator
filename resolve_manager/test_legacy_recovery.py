import tempfile
import unittest
from pathlib import Path
from core import digest,write_json
from translation import recover_legacy_adapters,STATE,ORIGINAL,WORDS,ADAPTER_ABI

class LegacyRecoveryTests(unittest.TestCase):
    def fixture(self,root,name='legacy.ofx',abi=None):
        path=root/name;path.write_bytes(b'legacy adapter')
        saved=Path(str(path)+ORIGINAL);saved.write_bytes(b'vendor module')
        state={'original_sha256':digest(saved),'adapter_sha256':digest(path),'phase':'applied'}
        if abi is not None:state['adapter_abi']=abi
        write_json(Path(str(path)+STATE),state)
        Path(str(path)+WORDS).write_text('Brightness\t亮度\n',encoding='utf-8')
        return {'path':str(path),'disabled':False},state

    def test_legacy_restore_preserves_snapshot_and_skips_current_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);legacy,_=self.fixture(root);current,_=self.fixture(root,'current.ofx',ADAPTER_ABI)
            result=recover_legacy_adapters([legacy,current],root/'data',lambda:False)
            self.assertEqual(result['count'],1)
            self.assertEqual(Path(legacy['path']).read_bytes(),b'vendor module')
            self.assertEqual(Path(current['path']).read_bytes(),b'legacy adapter')
            self.assertTrue(list(Path(result['snapshot']).glob('*/legacy.ofx.rpm-translations.tsv')))
            self.assertFalse(Path(legacy['path']+STATE).exists())

    def test_preflight_checksum_failure_does_not_restore_any_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);first,_=self.fixture(root,'first.ofx');second,_=self.fixture(root,'second.ofx')
            Path(second['path']).write_bytes(b'changed by vendor')
            with self.assertRaisesRegex(RuntimeError,'校验失败'):
                recover_legacy_adapters([first,second],root/'data',lambda:False)
            self.assertEqual(Path(first['path']).read_bytes(),b'legacy adapter')
            self.assertFalse((root/'data').exists())

    def test_running_host_prevents_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);row,_=self.fixture(root)
            with self.assertRaisesRegex(RuntimeError,'退出达芬奇'):
                recover_legacy_adapters([row],root/'data',lambda:True)
            self.assertEqual(Path(row['path']).read_bytes(),b'legacy adapter')

if __name__=='__main__':unittest.main()
