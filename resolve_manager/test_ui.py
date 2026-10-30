import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import app

class WindowIntegrationTests(unittest.TestCase):
    def test_scan_filter_and_dictionary_persistence(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / 'plugins'; root.mkdir()
            (root / 'Test.ofx').write_bytes(b'test')
            with patch.object(app,'DATA',base/'data'), patch.object(app,'default_roots',lambda:[str(root)]):
                window = app.App()
                window.withdraw()
                try:
                    deadline = time.monotonic() + 5
                    while window.busy and time.monotonic() < deadline:
                        window.update(); time.sleep(.01)
                    self.assertFalse(window.busy, 'asynchronous scan did not finish')
                    self.assertEqual(len(window.tree.get_children()),1)
                    window.query.set('no match')
                    self.assertEqual(len(window.tree.get_children()),0)
                    window.query.set('Test')
                    self.assertEqual(len(window.tree.get_children()),1)
                    window.en.set('Test effect'); window.zh.set('测试效果'); window.save_word()
                    self.assertEqual(app.read_json(base/'data'/'dictionary.json',{})['Test effect'],'测试效果')
                    window.tree.selection_set('0'); window.selection()
                    self.assertIn('Test.ofx',window.detail.get())
                finally: window.destroy()

    def test_translation_actions_fit_minimum_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            with patch.object(app,'DATA',folder),patch.object(app,'default_roots',lambda:[]):
                window=app.App()
                try:
                    window.geometry('1000x700');window.update()
                    window.tabs.select(window.translation_tab);window.update()
                    actions=window.translation_tab.winfo_children()[-1]
                    self.assertGreaterEqual(actions.winfo_height(),actions.winfo_reqheight())
                    self.assertLessEqual(actions.winfo_y()+actions.winfo_height(),window.translation_tab.winfo_height())
                    self.assertEqual(window.cget('background'),'#202124')
                finally: window.destroy()

if __name__ == '__main__': unittest.main()
