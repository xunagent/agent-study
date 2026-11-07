import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_study.artwork import replace_artwork
from agent_study.engine import Engine
from agent_study.lark import xml_root, block_id, node_text
from agent_study.model import StudyError
from agent_study.storage import Local
from fake_lark import FakeLark


class ImageRemote(FakeLark):
    def nodes(self, content):
        nodes = super().nodes(content)
        for n in nodes:
            if n.tag == 'img':
                n.attrib.pop('path', None)
                n.attrib.pop('token', None)
                n.set('src', 'uploaded-image')
        return nodes


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.remote = ImageRemote()
        self.engine = Engine(self.remote, Local(self.tmp.name))
        root = Path(__file__).resolve().parents[1]
        self.engine.init('folder', json.loads((root/'assets/config.example.json').read_text()))
        self.doc = self.remote.create('folder', 'fixture', '<h1>流程图</h1><whiteboard/><pre><code>GRAPH_SOURCE</code></pre><h1>我的疑问与感悟</h1><p>USER_TEXT</p>')['token']
        self.remote.update(self.doc, '<img token="uploaded-image"/>')
        self.uploaded = block_id(self.remote.docs[self.doc]['nodes'][-1])
        self.section = self.remote.section(self.doc, '流程图')
        self.block = block_id(next(xml_root(self.section['content']).iter('whiteboard')))

    def replace(self, **overrides):
        args = dict(engine=self.engine, doc=self.doc, heading='流程图',
                    image_bytes=b'\x89PNG\r\n\x1a\nfixture', prompt='Exact nodes and edges',
                    expected_block=self.block, expected_revision=self.section['revision_id'],
                    uploaded_block=self.uploaded, image_token='uploaded-image')
        args.update(overrides)
        return replace_artwork(**args)

    def test_response_loss_reuses_image_and_protects_other_content(self):
        self.remote.fail_update_after = 'agent_study_artwork'
        self.remote.reads.clear()
        first = self.replace()
        second = self.replace()
        self.assertEqual(first, second)
        nodes = self.remote.docs[self.doc]['nodes']
        self.assertEqual(sum(n.tag == 'img' for n in nodes), 1)
        self.assertIn('GRAPH_SOURCE', ''.join(node_text(n) for n in nodes if n.tag == 'pre'))
        self.assertEqual(nodes[-1].text, 'USER_TEXT')
        self.assertTrue(all('USER_TEXT' not in ''.join(r[2]) for r in self.remote.reads))

    def test_revision_conflict_preserves_original(self):
        self.remote.update(self.doc, '<p>user added</p>')
        with self.assertRaises(StudyError):
            self.replace()
        self.assertTrue(any(n.tag == 'whiteboard' for n in self.remote.docs[self.doc]['nodes']))

    def test_non_image_rejected_before_mutation(self):
        with self.assertRaises(StudyError):
            self.replace(image_bytes=b'not an image')
        self.assertTrue(any(n.tag == 'whiteboard' for n in self.remote.docs[self.doc]['nodes']))

    def test_missing_upload_never_removes_old_diagram(self):
        with self.assertRaises(StudyError):
            self.replace(image_token='wrong-token')
        self.assertTrue(any(n.tag == 'whiteboard' for n in self.remote.docs[self.doc]['nodes']))
