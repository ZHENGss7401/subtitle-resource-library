import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import author_bridge as bridge
from author_registry import require_author, write_credit

class AuthorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.home()/'.codex')
        self.root = Path(self.tmp.name)
        self.lib, self.repo = self.root/'lib', self.root/'repo'
        self.lib.mkdir(); self.repo.mkdir()
        self.sha = 'a'*64
        for root in (self.lib, self.repo):
            bridge.atomic(root/'INDEX.json', {'versions': {'Q99': {'sha256': self.sha}}})
            bridge.atomic(root/'authors.json', {'schema': 1, 'revision': 0, 'records': {}, 'history': []})
        self.patches = [patch.object(bridge, 'LIB', self.lib), patch.object(bridge, 'REPO', self.repo),
                        patch.object(bridge, 'git', return_value='')]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def payload(self, **changes):
        return dict(code='Q99', sha256=self.sha, author='测试作者', revision=0, **changes)

    def test_pending_and_changed_png_blocked(self):
        with self.assertRaises(ValueError): require_author('Q99', self.sha, self.lib)
        bridge.confirm(self.payload())
        with self.assertRaises(ValueError): require_author('Q99', 'b'*64, self.lib)
        with self.assertRaises(ValueError): require_author('Q98', self.sha, self.lib)

    def test_confirm_and_package_record(self):
        result = bridge.confirm(self.payload())
        self.assertTrue(result['published'])
        credit = require_author('Q99', self.sha, self.lib)
        self.assertEqual(credit['author'], '测试作者')
        write_credit(self.root/'package', credit)
        self.assertIn('测试作者', (self.root/'package'/'作者署名.txt').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((self.root/'package'/'agent夹'/'_作者署名.json').read_text(encoding='utf-8')), credit)

    def test_stale_revision_rejected(self):
        bridge.confirm(self.payload())
        with self.assertRaises(ValueError): bridge.confirm(self.payload())

    def test_publish_failure_is_durable_and_retry_idempotent(self):
        with patch.object(bridge, 'git', side_effect=RuntimeError('offline')):
            result = bridge.confirm(self.payload())
        self.assertFalse(result['published'])
        self.assertEqual(require_author('Q99', self.sha, self.lib)['author'], '测试作者')
        result = bridge.confirm({**self.payload(), 'revision': 1})
        self.assertTrue(result['published'])
        self.assertEqual(len(result['registry']['history']), 1)

    def test_edit_keeps_history(self):
        bridge.confirm(self.payload())
        result = bridge.confirm({**self.payload(), 'revision': 1, 'author': '另一作者'})
        self.assertEqual(len(result['registry']['history']), 2)
        self.assertEqual(result['registry']['history'][1]['previous']['author'], '测试作者')

    def test_invalid_name_or_hash_rejected(self):
        for payload in ({**self.payload(), 'author': ' '}, {**self.payload(), 'author': 'x\ny'},
                        {**self.payload(), 'sha256': 'b'*64}):
            with self.assertRaises(ValueError): bridge.confirm(payload)
        self.assertEqual(bridge.read(self.lib/'authors.json')['revision'], 0)

if __name__ == '__main__': unittest.main()
