import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_study.engine import Engine
from agent_study.lark import RemoteError, node_text, xml_root
from agent_study.model import StudyError, source_identity, validate_lesson
from agent_study.storage import Local
from fake_lark import FakeLark

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.remote = FakeLark()
        self.engine = Engine(self.remote, Local(self.temp.name))
        self.config = json.loads((ROOT / "assets/config.example.json").read_text())
        self.lesson = json.loads((ROOT / "assets/react.example.json").read_text())
        self.engine.init("folder", self.config)

    def publish(self):
        return self.engine.publish(self.lesson)

    def test_unread_gate_and_daily_idempotency(self):
        first = self.publish()
        count = len(self.remote.docs)
        self.assertEqual(self.engine.daily()["action"], "read_current")
        self.assertEqual(self.publish()["url"], first["url"])
        other = copy.deepcopy(self.lesson)
        other["source"]["url"] = "https://arxiv.org/abs/2301.12345"
        self.assertEqual(self.engine.publish(other)["action"], "read_current")
        self.engine.set_status("已读")
        self.assertEqual(self.engine.daily()["action"], "already_generated_today")
        self.assertEqual(len(self.remote.docs), count)

    def test_new_device_restore(self):
        self.publish()
        new = Engine(self.remote, Local(Path(self.temp.name) / "new-device"))
        new.restore(self.engine.doc("home")["url"])
        self.assertEqual(new.daily()["action"], "read_current")
        self.assertEqual(new.state()["config"], self.engine.state()["config"])

    def test_create_timeout_adopts_remote_document(self):
        self.remote.fail_create_after = True
        self.publish()
        self.assertEqual(len(self.remote.docs), 8)

    def test_section_response_loss_is_reconciled(self):
        self.remote.fail_update_after = "教学场景"
        self.publish()
        material = next(iter(self.engine.state()["materials"].values()))
        section = self.remote.section(material["doc"]["token"], "问题与背景")
        self.assertEqual(node_text(xml_root(section["content"])).count("教学场景"), 1)

    def test_failed_section_resumes_same_doc(self):
        self.remote.fail_update_before = "教学场景"
        with self.assertRaises(StudyError): self.publish()
        self.publish()
        self.assertEqual(len(self.remote.docs), 8)

    def test_diagram_failure_resumes_without_duplicate(self):
        self.remote.fail_preview = True
        with self.assertRaises(RemoteError): self.publish()
        self.remote.fail_preview = False
        self.publish()
        doc = next(iter(self.engine.state()["materials"].values()))["doc"]["token"]
        self.assertEqual(len(list(xml_root(self.remote.section(doc, "流程图")["content"]).iter("whiteboard"))), 1)

    def test_interrupted_publication_resumes_on_new_device(self):
        self.remote.fail_preview = True
        with self.assertRaises(RemoteError): self.publish()
        self.remote.fail_preview = False
        restored = Engine(self.remote, Local(Path(self.temp.name) / "replacement"))
        restored.restore(self.engine.doc("home")["url"])
        pending = restored.daily()
        self.assertEqual(pending["action"], "resume_publication")
        self.assertEqual(restored.resume(pending["operation"])["action"], "published")
        self.assertEqual(len(self.remote.docs), 8)

    def test_index_failure_resumes(self):
        self.remote.fail_update_before = "arxiv:2210.03629"
        with self.assertRaises(RemoteError): self.publish()
        self.publish()
        self.assertEqual(len(self.remote.docs), 8)

    def test_user_content_preserved_and_not_read(self):
        self.publish()
        doc = next(iter(self.engine.state()["materials"].values()))["doc"]["token"]
        for title, value in (("我的疑问与感悟", "PRIVATE_THOUGHT"), ("核心观点", "MY_EDIT")):
            sec = self.remote.section(doc, title)
            self.remote.update(doc, "<p>" + value + "</p>", command="block_insert_after", block_id=sec["heading_id"])
        self.remote.reads.clear()
        self.engine.daily()
        self.publish()
        self.assertFalse(any("PRIVATE_THOUGHT" in text for _, _, texts in self.remote.reads for text in texts))
        self.assertIn("MY_EDIT", self.remote.section(doc, "核心观点")["content"])
        with self.assertRaises(StudyError): self.engine.questions(None, False)
        self.assertIn("PRIVATE_THOUGHT", self.engine.questions(None, True)["content"])

    def test_version_update_reuses_doc_and_preserves_old(self):
        first = self.publish()
        new = copy.deepcopy(self.lesson)
        new["source"]["version"] = "v4"
        new["source"]["url"] = "https://arxiv.org/abs/2210.03629v4"
        result = self.engine.publish(new, "specified")
        self.assertEqual(first["url"], result["url"])
        self.assertEqual(len(self.remote.docs), 8)
        doc = next(iter(self.engine.state()["materials"].values()))["doc"]["token"]
        self.assertIn("核心观点", self.remote.section(doc, "核心观点")["content"])
        self.assertIn("更新 v4", self.remote.section(doc, "更新 v4 · 核心观点")["content"])

    def test_discussion_idempotent_and_explicit(self):
        self.publish()
        with self.assertRaises(StudyError): self.engine.reply(None, "answer", "q1", False)
        self.engine.reply(None, "answer", "q1", True)
        self.engine.reply(None, "answer", "q1", True)
        doc = next(iter(self.engine.state()["materials"].values()))["doc"]["token"]
        self.assertEqual(self.remote.section(doc, "AI 讨论记录")["content"].count("answer"), 1)

    def test_different_payload_cannot_resume_over_user_content(self):
        self.remote.fail_preview = True
        with self.assertRaises(RemoteError): self.publish()
        self.lesson["sections"]["problem"] = "different draft"
        self.remote.fail_preview = False
        with self.assertRaisesRegex(StudyError, "different content"): self.publish()

    def test_foreign_lease_blocks_write(self):
        self.engine.event("lease", {"owner": "other-device", "expires": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
        with self.assertRaises(StudyError):
            with self.engine.writer(): self.publish()

    def test_writer_acquires_publishes_and_releases(self):
        with self.engine.writer():
            self.assertEqual(self.publish()["action"], "published")
        self.assertEqual(self.engine.events()[-1]["kind"], "release")

    def test_new_foreign_lease_stops_existing_writer(self):
        with self.engine.writer():
            self.engine.event("lease", {"owner": "arriving-device", "expires": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
            with self.assertRaisesRegex(StudyError, "Concurrent device"):
                self.publish()

    def test_manual_status_is_seen_without_reflections(self):
        self.publish()
        material = next(iter(self.engine.state()["materials"].values()))
        status = next(n for n in self.remote.docs[material["doc"]["token"]]["nodes"] if n.get("block-id") == material["status_block"])
        status.set('done', 'true')
        self.assertEqual(self.engine.daily()["action"], "already_generated_today")
        status.set('done', 'false')
        self.assertEqual(self.engine.daily()['status'], '待学习')

    def test_after_read_next_day_allows_selection(self):
        from unittest.mock import patch
        import agent_study.engine as module
        self.publish()
        self.engine.set_status("已跳过")
        future = datetime.now(timezone.utc) + timedelta(days=1)
        with patch.object(module, "datetime") as clock:
            clock.now.return_value = future
            result = self.engine.daily()
            self.assertEqual(result["action"], "select_material")
            self.assertEqual(result["studied"], [])
            self.assertEqual(result["other_readings"][0]["status"], "已跳过")

    def test_legacy_status_migrates_to_clickable_checkbox(self):
        self.publish()
        material = next(iter(self.engine.state()['materials'].values()))
        node = next(n for n in self.remote.docs[material['doc']['token']]['nodes'] if n.get('block-id') == material['status_block'])
        node.tag = 'p'
        node.attrib.pop('done', None)
        node.text = '待学习'
        self.assertEqual(self.engine.daily()['status'], '待学习')
        self.engine.set_status('待学习')
        material = next(iter(self.engine.state()['materials'].values()))
        value, part = self.engine.status_value(material)
        self.assertEqual(value, '待学习')
        self.assertEqual(len(list(xml_root(part['content']).iter('checkbox'))), 1)

    def test_conversation_statuses_keep_checkbox_semantics(self):
        self.publish()
        for requested in ('阅读中', '已跳过', '已读', '待学习'):
            self.engine.set_status(requested)
            material = next(iter(self.engine.state()['materials'].values()))
            value, part = self.engine.status_value(material)
            self.assertEqual(value, requested)
            self.assertEqual(len(list(xml_root(part['content']).iter('checkbox'))), 1)

    def test_status_response_loss_recovers_new_block_id(self):
        self.publish()
        self.remote.fail_update_after = "已读"
        self.engine.set_status("已读")
        item = next(iter(self.engine.state()["materials"].values()))
        self.assertEqual(self.engine.status_value(item)[0], "已读")

    def test_review_reads_content_matching_latest_version(self):
        self.publish()
        updated = copy.deepcopy(self.lesson)
        updated["source"]["version"] = "v4"
        updated["sections"]["solution"] = "NEW_VERSION_MECHANISM"
        self.engine.publish(updated, "specified")
        self.engine.set_status("已读")
        result = self.engine.review("执行循环")
        self.assertIn("NEW_VERSION_MECHANISM", result["materials"][0]["sections"]["解决方案"])

    def test_abstract_only_is_candidate(self):
        self.lesson["source"]["reading_scope"] = "abstract"
        with self.assertRaises(StudyError): validate_lesson(self.lesson)
        self.engine.candidate({"source": self.lesson["source"], "reason": "全文尚未取得", "topics": ["执行循环"]})
        self.assertEqual(len(self.engine.state()["candidates"]), 1)

    def test_duplicate_remote_names_are_rejected(self):
        self.publish()
        material = next(iter(self.engine.state()["materials"].values()))
        title = material["doc"]["name"]
        self.remote.create("folder", title, "<p>duplicate</p>")
        with self.assertRaises(StudyError): self.engine.ensure_doc(title, "<p>x</p>", "another-operation")

    def test_arxiv_versions_and_doi_identity(self):
        a = {"kind": "paper", "url": "https://arxiv.org/pdf/2210.03629v3.pdf"}
        b = {"kind": "paper", "url": "https://arxiv.org/abs/2210.03629v4"}
        self.assertEqual(source_identity(a), source_identity(b))
        self.assertEqual(source_identity({"kind": "paper", "url": "https://doi.org/10.1234/ABC"}), "doi:10.1234/abc")


if __name__ == "__main__":
    unittest.main()
