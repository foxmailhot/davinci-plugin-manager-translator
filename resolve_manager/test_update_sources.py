import io
import unittest
import urllib.error
from unittest.mock import patch
import updater as u

class Reply(io.BytesIO):
    def __init__(self,url,body=b''):super().__init__(body);self.url=url
    def geturl(self):return self.url

class UpdateSourceTests(unittest.TestCase):
    def page(self,tag):return f'https://github.com/{u.REPOSITORY}/releases/tag/{tag}'

    def test_current_version_does_not_call_rate_limited_api(self):
        with patch.object(u,'VERSION','1.0.0'),patch.object(u.urllib.request,'urlopen',return_value=Reply(self.page('v1.0.0'))) as network,patch.object(u,'check_api',side_effect=u.ApiRateLimited('limited')) as api:
            self.assertIsNone(u.check_latest());api.assert_not_called()
            self.assertEqual(network.call_count,1)
            self.assertEqual(network.call_args.args[0].get_method(),'HEAD')

    def test_new_version_uses_public_page_and_checksum_without_api(self):
        zip_url,sha_url=u.release_urls('v1.0.1')
        checksum=('a'*64+'  '+u.RELEASE_ASSET+'\n').encode()
        with patch.object(u,'VERSION','1.0.0'),patch.object(u.urllib.request,'urlopen',side_effect=[Reply(self.page('v1.0.1')),Reply(sha_url,checksum)]) as network,patch.object(u,'check_api') as api:
            result=u.check_latest();api.assert_not_called()
            self.assertEqual(result['version'],'v1.0.1');self.assertEqual(result['source'],'release-page')
            self.assertEqual(result['expected_sha256'],'a'*64);self.assertEqual(result['zip'],zip_url)
            self.assertTrue(all('api.github.com' not in call.args[0].full_url for call in network.call_args_list))

    def test_head_unsupported_uses_get(self):
        error=urllib.error.HTTPError('https://github.com',405,'HEAD not supported',{},None)
        with patch.object(u,'VERSION','1.0.0'),patch.object(u.urllib.request,'urlopen',side_effect=[error,Reply(self.page('v1.0.0'))]) as network:
            self.assertIsNone(u.check_latest())
            self.assertEqual([c.args[0].get_method() for c in network.call_args_list],['HEAD','GET'])

    def test_api_is_backup_for_public_page_failure(self):
        release={'version':'v2.0.0','source':'api'}
        with patch.object(u,'check_release_page',side_effect=urllib.error.URLError('offline')),patch.object(u,'check_api',return_value=release):
            self.assertIs(u.check_latest(),release)

    def test_both_sources_failed_does_not_claim_up_to_date(self):
        with patch.object(u,'check_release_page',side_effect=urllib.error.URLError('offline')),patch.object(u,'check_api',side_effect=u.ApiRateLimited('limited')):
            with self.assertRaisesRegex(RuntimeError,'限流'):u.check_latest()

    def test_api_403_quota_header_is_classified(self):
        error=urllib.error.HTTPError('https://api.github.com',403,'Forbidden',{'X-RateLimit-Remaining':'0'},None)
        with patch.object(u.urllib.request,'urlopen',side_effect=error):
            with self.assertRaises(u.ApiRateLimited):u.check_api()

    def test_building_release_does_not_offer_unavailable_package(self):
        error=urllib.error.HTTPError('https://github.com',404,'not ready',{},None)
        with patch.object(u,'VERSION','1.0.0'),patch.object(u.urllib.request,'urlopen',side_effect=[Reply(self.page('v1.0.1')),error]),patch.object(u,'check_api',side_effect=u.ApiRateLimited('limited')):
            with self.assertRaisesRegex(RuntimeError,'发布中'):u.check_latest()

    def test_untrusted_redirect_and_bad_checksums_are_rejected(self):
        for url in ('https://github.com.evil.test/'+u.REPOSITORY+'/releases/tag/v1.0.0',
                    'https://github.com/other/repo/releases/tag/v1.0.0',
                    f'https://github.com/{u.REPOSITORY}/releases/tag/latest'):
            with self.assertRaises(ValueError):u.tag_from_page(url)
        for value in ('','not-a-hash','a'*64+'  different.zip'):
            with self.assertRaises(ValueError):u.checksum_value(value)

if __name__=='__main__':unittest.main()
