import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import batch_translation as b
from translation import PROVIDERS, translate_catalog

class BatchTests(unittest.TestCase):
    def records(self,count=3):return [b.make_record(i,f'Example effect number {i}') for i in range(count)]
    def raw(self,records):return [f'[[{r["id"]}]] 效果 {r["line"]}' for r in records]

    def test_provider_limits_and_real_thousand_item_request(self):
        records=self.records(1000)
        self.assertEqual(len(b.plan_chunks(records,PROVIDERS[3])),1)
        cloud=b.plan_chunks(records,PROVIDERS[2]);self.assertEqual(len(cloud),8)
        self.assertTrue(all(len(c)<=128 for c in cloud))
        memory=b.plan_chunks(records,PROVIDERS[0])
        self.assertTrue(all(len('\n'.join(b.tagged(r) for r in c).encode())<=500 for c in memory))
        with patch('translation.request_json',return_value={'translatedText':self.raw(records)}) as request:
            result=b.send_chunk(records,PROVIDERS[3],'','http://localhost:5000',Path('.'))
            self.assertEqual(len(request.call_args.args[1]['q']),1000)
            self.assertEqual(len(b.validate_response(records,result)[0]),1000)

    def test_reordered_output_maps_by_id(self):
        records=self.records(); raw=list(reversed(self.raw(records)))
        valid,issues=b.validate_response(records,raw)
        self.assertFalse(issues);self.assertEqual(valid['00000001'],'效果 1')

    def test_single_and_fullwidth_brackets_are_unambiguous(self):
        records=self.records(2)
        valid,issues=b.validate_response(records,'[00000001] 效果甲\n［［00000002］］ 效果乙')
        self.assertEqual(len(valid),2);self.assertFalse(issues)

    def test_untranslated_brand_name_retry_preserves_original_mapping(self):
        def send(rows,*args):
            record=rows[0]
            if record.get('request_source'):
                self.assertEqual(record['request_source'],'De Grain')
                return ['[[00000001]] 去颗粒']
            return ['[[00000001]] BCC DeGrain']
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'send_chunk',side_effect=send):
            result=translate_catalog({'path':'mock.ofx','texts':['BCC DeGrain']},{},PROVIDERS[3],Path(folder))
            self.assertEqual(result['remaining'],0)
            self.assertEqual(result['translations']['BCC DeGrain'],'BCC 去颗粒')

    def test_missing_duplicate_unknown_and_merged_lines_rejected(self):
        records=self.records(4)
        raw='[[00000001]] 正确\n[[00000002]] 重复甲\n[[00000002]] 重复乙\n[[00000003]] 合并第一行\n丢失编号的一行\n[[99999999]] 陌生编号'
        valid,issues=b.validate_response(records,raw)
        self.assertEqual(valid,{'00000001':'正确'})
        kinds={i['kind'] for i in issues}
        self.assertTrue({'duplicate_id','unknown_id','ambiguous_lines','unmatched'}<=kinds)
        self.assertTrue(any(i.get('source_line')==4 for i in issues))

    def test_pipeline_sends_next_before_verifying_previous_and_prepacks(self):
        texts=[r['source'] for r in self.records(2001)]
        second_sent=threading.Event(); sending=[]; observed=[]
        real_validate=b.validate_response
        def send(records,provider,key,endpoint,data):
            sending.append(len(records))
            if records[0]['line']==1001:second_sent.set()
            if records[0]['line']==1:
                # While network 1 is outstanding, the producer must prepare package 2.
                jobs=Path(data)/'batch-jobs'
                import time
                deadline=time.monotonic()+2
                while not list(jobs.glob('*/batch-0002.request.json')) and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(list(jobs.glob('*/batch-0002.request.json')))
            return self.raw(records)
        def verify(records,raw):
            if records[0]['line']==1:
                self.assertTrue(second_sent.wait(2),'package 2 was not sent before package 1 validation')
                observed.append('overlap')
            return real_validate(records,raw)
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'send_chunk',side_effect=send),patch.object(b,'validate_response',side_effect=verify):
            result=translate_catalog({'path':'mock.ofx','texts':texts},{},PROVIDERS[3],Path(folder))
            self.assertIsNone(result['error']);self.assertEqual(result['remaining'],0)
            self.assertEqual(sending,[1000,1000,1]);self.assertEqual(observed,['overlap'])
            self.assertTrue((Path(result['job_folder'])/'summary.json').is_file())

    def test_bad_subset_retried_without_poisoning_cache(self):
        records=self.records(20);calls=[]
        def send(rows,*args):
            calls.append([r['id'] for r in rows])
            response=self.raw(rows)
            return response[:-1] if len(calls)==1 else response
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'send_chunk',side_effect=send):
            result=translate_catalog({'path':'mock.ofx','texts':[r['source'] for r in records]},{},PROVIDERS[3],Path(folder))
            self.assertEqual(result['remaining'],0)
            self.assertEqual(calls[1],['00000020'])
            cache=json.loads((Path(folder)/'translation-cache.json').read_text(encoding='utf-8'))
            self.assertEqual(cache[records[-1]['source']],'效果 20')
            reports=list(Path(result['job_folder']).glob('*.validation.json'))
            self.assertTrue(any('unmatched' in p.read_text(encoding='utf-8') for p in reports))

    def test_persistent_marker_loss_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'send_chunk',return_value='没有任何编号'):
            result=translate_catalog({'path':'mock.ofx','texts':[r['source'] for r in self.records(10)]},{},PROVIDERS[3],Path(folder))
            self.assertEqual(result['remaining'],10);self.assertFalse(result['translations'])
            self.assertIn('停止自动重试',result['error']);self.assertEqual(len(result['unmatched_records']),10)

    def test_cancel_keeps_inflight_results_and_resume_skips_cached(self):
        cancel=threading.Event();calls=[]
        def send(rows,*args):
            calls.append(len(rows));cancel.set();return self.raw(rows)
        texts=[r['source'] for r in self.records(1001)]
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'send_chunk',side_effect=send):
            result=translate_catalog({'path':'mock.ofx','texts':texts},{},PROVIDERS[3],Path(folder),cancel=cancel)
            self.assertEqual(result['remaining'],1);self.assertEqual(calls,[1000])
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(b,'send_chunk',side_effect=lambda rows,*args:self.raw(rows)) as send:
                result=translate_catalog({'path':'mock.ofx','texts':texts},{},PROVIDERS[3],Path(folder))
                count=send.call_count
                again=translate_catalog({'path':'mock.ofx','texts':texts},{},PROVIDERS[3],Path(folder))
                self.assertEqual(again['remaining'],0);self.assertEqual(send.call_count,count)

    def test_rejected_large_body_splits_safely(self):
        records=self.records(10);attempts=[]
        def send(rows,*args):
            attempts.append(len(rows))
            if len(rows)>3:raise RuntimeError('翻译服务返回 HTTP 413')
            return self.raw(rows)
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'send_chunk',side_effect=send):
            result=translate_catalog({'path':'mock.ofx','texts':[r['source'] for r in records]},{},PROVIDERS[3],Path(folder))
            self.assertEqual(result['remaining'],0);self.assertEqual(attempts,[10,5,2,3,5,2,3])

if __name__=='__main__':unittest.main()
