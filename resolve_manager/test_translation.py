import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import translation as tr
from core import scan, digest

BASE=Path(__file__).resolve().parent
ZIG=Path(os.environ.get('ZIG_EXE',str(BASE.parent/'.tools'/'ziglang'/'zig.exe')))

class TranslationTests(unittest.TestCase):
    def test_response_parsers_and_cache(self):
        with patch.object(tr,'request_json',return_value={'responseStatus':200,'responseData':{'translatedText':'亮度'}}):
            self.assertEqual(tr.translate_one('Brightness',tr.PROVIDERS[0]),'亮度')
        with patch.object(tr,'request_json',return_value=[[['亮度','Brightness']]]):
            self.assertEqual(tr.translate_one('Brightness',tr.PROVIDERS[1]),'亮度')
        with patch.object(tr,'request_json',return_value={'data':{'translations':[{'translatedText':'辉光'}]}}) as request:
            self.assertEqual(tr.translate_one('Glow',tr.PROVIDERS[2],'not-a-real-key'),'辉光')
            self.assertNotIn('not-a-real-key',request.call_args.args[0])
        with tempfile.TemporaryDirectory() as folder:
            catalog={'path':'test.ofx','texts':['Brightness','Some Effect']}
            with patch.object(tr,'translate_one',return_value='测试特效') as call,patch.object(tr.time,'sleep'):
                result=tr.translate_catalog(catalog,{},tr.PROVIDERS[1],Path(folder))
                self.assertEqual(call.call_count,1); self.assertEqual(result['remaining'],0)
                again=tr.translate_catalog(catalog,{},tr.PROVIDERS[1],Path(folder))
                self.assertEqual(call.call_count,1); self.assertEqual(again['translations'],result['translations'])

    def test_failure_preserves_partial_result_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog={'path':'test.ofx','texts':['Brightness','Pending effect']}
            with patch.object(tr,'translate_one',side_effect=RuntimeError('quota exhausted')):
                result=tr.translate_catalog(catalog,{},tr.PROVIDERS[0],Path(folder))
            self.assertEqual(result['remaining'],1); self.assertIn('Brightness',result['translations']);self.assertIn('quota',result['error'])

    @unittest.skipUnless(ZIG.exists(),'Native tests require Zig; set ZIG_EXE')
    def test_native_adapter_and_reversible_deployment(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary); plugin=folder/'mock.ofx'; include=BASE/'native'/'include'
            subprocess.run([str(ZIG),'cc','-shared','-target','x86_64-windows-gnu','-I',str(include),str(BASE/'native'/'tests'/'mock_plugin.c'),'-o',str(plugin)],check=True,capture_output=True)
            host=folder/'host.exe'
            subprocess.run([str(ZIG),'cc','-target','x86_64-windows-gnu','-I',str(include),str(BASE/'native'/'tests'/'mock_host.c'),'-o',str(host)],check=True,capture_output=True)
            row=scan([folder])[0][0]; original_hash=digest(plugin)
            result={'path':row['path'],'source_sha256':original_hash,'translations':{'Brightness':'亮度'}}
            with self.assertRaises(RuntimeError):tr.apply_adapter(row,result,folder/'data',process_check=lambda:True)
            tr.apply_adapter(row,result,folder/'data',process_check=lambda:False)
            completed=subprocess.run([str(host),str(plugin)],capture_output=True,text=True,timeout=15)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            self.assertIn('PASS',completed.stdout)
            self.assertEqual(digest(Path(str(plugin)+tr.ORIGINAL)),original_hash)
            tr.restore_adapter(row,process_check=lambda:False)
            self.assertEqual(digest(plugin),original_hash)
            self.assertFalse(Path(str(plugin)+tr.ORIGINAL).exists())

if __name__=='__main__':unittest.main()
