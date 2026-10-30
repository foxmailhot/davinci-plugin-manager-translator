import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from updater import unpack_verified,version_tuple,valid_asset_url,RELEASE_ASSET

class UpdateTests(unittest.TestCase):
    def package(self,folder,names):
        archive=folder/'test.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for name,value in names.items():z.writestr(name,value)
        checksum=folder/'sha.txt';checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+RELEASE_ASSET)
        return archive,checksum

    def test_valid_package_and_checksum_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);archive,checksum=self.package(folder,{'ResolvePluginManager.exe':b'test'})
            target=unpack_verified(archive,checksum,folder/'app');self.assertEqual(target.read_bytes(),b'test')
            checksum.write_text('0'*64)
            with self.assertRaises(ValueError):unpack_verified(archive,checksum,folder/'bad')
            self.assertFalse((folder/'bad').exists())

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);archive,checksum=self.package(folder,{'../escape.exe':b'bad','ResolvePluginManager.exe':b'test'})
            with self.assertRaises(ValueError):unpack_verified(archive,checksum,folder/'app')
            self.assertFalse((folder/'escape.exe').exists())

    def test_version_and_download_origin(self):
        self.assertGreater(version_tuple('v0.10.0'),version_tuple('0.2.0'))
        self.assertFalse(valid_asset_url('https://github.com.evil.test/foxmailhot/davinci-plugin-manager-translator/releases/download/v1/update.zip'))
        self.assertFalse(valid_asset_url('https://github.com/other/repo/releases/download/v1/update.zip'))

if __name__=='__main__':unittest.main()
