import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

import batch_translation as batch
import translation as tr


class RecoveryTests(unittest.TestCase):
    def catalog(self):
        return {'path':'mock.ofx','texts':['Recovery effect alpha','Recovery effect beta']}

    def raw(self, records):
        return [f'[[{r["id"]}]] 效果{r["line"]}' for r in records]

    def test_timeout_recovers_same_chunk_without_duplicate_mapping(self):
        attempts=[]
        def send(records,*args):
            attempts.append([r['id'] for r in records])
            if len(attempts)==1: raise tr.TranslationServiceError('请求超时',True)
            return self.raw(records)
        with tempfile.TemporaryDirectory() as folder, patch.object(batch,'send_chunk',side_effect=send), \
                patch.object(threading.Event,'wait',return_value=False) as wait:
            result=batch.run_catalog(self.catalog(),{},tr.PROVIDERS[3],folder,'','http://localhost',lambda _:None,None)
            self.assertEqual(result['remaining'],0)
            self.assertEqual(attempts[0],attempts[1])
            wait.assert_any_call(2)
            self.assertTrue(list(Path(result['job_folder']).glob('*.attempt-1.error.json')))

    def test_exhaustion_saves_partial_results_and_resume_skips_them(self):
        calls=[]
        def send(records,*args):
            calls.append(records[0]['source'])
            if records[0]['source'].endswith('beta'): raise tr.TranslationServiceError('请求超时',True)
            return self.raw(records)
        with tempfile.TemporaryDirectory() as folder,patch.object(batch,'send_chunk',side_effect=send), \
                patch.object(batch,'plan_chunks',side_effect=lambda records,*a,**k:[[r] for r in records]), \
                patch.object(threading.Event,'wait',return_value=False):
            result=batch.run_catalog(self.catalog(),{},tr.PROVIDERS[3],folder,'','http://localhost',lambda _:None,None)
            self.assertEqual(len(calls),4)
            self.assertEqual(result['remaining'],1)
            self.assertIn('已暂停',result['error'])
            cache=json.loads((Path(folder)/'translation-cache.json').read_text(encoding='utf-8'))
            self.assertIn('Recovery effect alpha',cache)
            with patch.object(batch,'send_chunk',side_effect=lambda records,*a:self.raw(records)) as send:
                resumed=batch.run_catalog(self.catalog(),{},tr.PROVIDERS[3],folder,'','http://localhost',lambda _:None,None)
                self.assertEqual(resumed['remaining'],0)
                self.assertEqual(send.call_count,1)
                self.assertEqual(send.call_args.args[0][0]['source'],'Recovery effect beta')

    def test_cancel_during_backoff_sends_no_retry(self):
        class CancelDuringWait(threading.Event):
            def wait(self, timeout=None):
                self.set()
                return True
        cancel=CancelDuringWait()
        with tempfile.TemporaryDirectory() as folder,patch.object(batch,'send_chunk',side_effect=tr.TranslationServiceError('超时',True)) as send:
            result=batch.run_catalog(self.catalog(),{},tr.PROVIDERS[3],folder,'','http://localhost',lambda _:None,cancel)
            self.assertEqual(send.call_count,1)
            self.assertIn('已停止',result['error'])

    def test_credentials_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(batch,'send_chunk',side_effect=tr.TranslationServiceError('HTTP 403')) as send:
            result=batch.run_catalog(self.catalog(),{},tr.PROVIDERS[3],folder,'','http://localhost',lambda _:None,None)
            self.assertEqual(send.call_count,1)
            self.assertEqual(result['remaining'],2)

    def test_http_429_classified_and_retry_after_respected(self):
        failure=urllib.error.HTTPError('https://example.invalid/?key=SECRET',429,'limit',{'Retry-After':'12'},io.BytesIO())
        with patch('urllib.request.urlopen',side_effect=failure):
            with self.assertRaises(tr.TranslationServiceError) as caught: tr.request_json('https://example.invalid')
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after,12)
        self.assertNotIn('SECRET',str(caught.exception))
        with tempfile.TemporaryDirectory() as folder,patch.object(batch,'send_chunk',side_effect=[caught.exception,self.raw([batch.make_record(0,'Recovery effect alpha')])]), \
                patch.object(threading.Event,'wait',return_value=False) as wait:
            batch.run_catalog({'path':'mock.ofx','texts':['Recovery effect alpha']},{},tr.PROVIDERS[3],folder,'','http://localhost',lambda _:None,None)
            wait.assert_any_call(12)

    def test_invalid_google_envelope_is_retryable(self):
        for value in [None,{},[],[None],[[[]]],[[[42]]]]:
            with self.subTest(value=value),self.assertRaises(tr.TranslationServiceError) as caught:
                tr.google_text(value)
            self.assertTrue(caught.exception.retryable)


if __name__=='__main__': unittest.main()
