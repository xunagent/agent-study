"""In-memory CLI boundary with real block identities and injected response loss."""
import copy
import xml.etree.ElementTree as ET
from agent_study.lark import RemoteError, node_text, xml_root
from agent_study.model import StudyError


class FakeLark:
    def __init__(self):
        self.docs = {}
        self.counter = 0
        self.reads = []
        self.fail_create_after = False
        self.fail_update_after = None
        self.fail_update_before = None
        self.fail_preview = False

    def nodes(self, content):
        nodes = list(xml_root(content))
        for node in nodes:
            self.counter += 1
            node.set("block-id", "b" + str(self.counter))
            if node.tag == "whiteboard":
                node.clear()
                node.set("token", "board" + str(self.counter))
                node.set("block-id", "b" + str(self.counter))
        return nodes

    def list_docs(self, folder):
        return [copy.deepcopy(d["meta"]) for d in self.docs.values() if d["folder"] == folder]

    def create(self, folder, title, content):
        token = "doc" + str(len(self.docs) + 1)
        meta = {"token": token, "url": "https://example.feishu.cn/docx/" + token, "name": title, "type": "docx"}
        self.docs[token] = {"meta": meta, "folder": folder, "nodes": self.nodes(content), "revision": 1}
        if self.fail_create_after:
            self.fail_create_after = False
            raise RemoteError("response lost", uncertain=True)
        return copy.deepcopy(meta)

    def fetch(self, doc, **scope):
        doc = doc.rsplit("/", 1)[-1]
        d = self.docs[doc]
        nodes = d["nodes"]
        mode = scope.get("scope", "full")
        if mode == "outline":
            nodes = [n for n in nodes if n.tag == "h1"]
        elif mode in ("range", "section"):
            ids = [n.get("block-id") for n in nodes]
            start = ids.index(scope["start_block_id"])
            if mode == "range":
                nodes = nodes[start:ids.index(scope["end_block_id"]) + 1]
            else:
                end = next((i for i in range(start + 1, len(nodes)) if nodes[i].tag == "h1"), len(nodes))
                nodes = nodes[start:end]
        self.reads.append((doc, mode, [node_text(n) for n in nodes]))
        content = "".join(ET.tostring(n, encoding="unicode") for n in nodes)
        if mode != "full":
            content = '<fragment mode="' + mode + '">' + content + '</fragment>'
        return {"content": content, "revision_id": d["revision"]}

    def section(self, doc, title):
        nodes = self.docs[doc]["nodes"]
        headings = [n for n in nodes if n.tag == "h1" and node_text(n) == title]
        if len(headings) != 1:
            raise StudyError("ambiguous section")
        ident = headings[0].get("block-id")
        result = self.fetch(doc, scope="section", start_block_id=ident)
        result["heading_id"] = ident
        return result

    def update(self, doc, content, command="append", **kwargs):
        if self.fail_update_before and self.fail_update_before in content:
            self.fail_update_before = None
            raise RemoteError("write failed")
        d = self.docs[doc]
        expected = kwargs.get("revision_id", -1)
        if expected != -1 and expected != d["revision"]:
            raise RemoteError("revision conflict")
        incoming = self.nodes(content)
        if command == "append":
            d["nodes"].extend(incoming)
        else:
            index = next(i for i, n in enumerate(d["nodes"]) if n.get("block-id") == kwargs["block_id"])
            if command == "block_insert_after":
                d["nodes"][index + 1:index + 1] = incoming
            elif command == "block_replace":
                d["nodes"][index:index + 1] = incoming
            elif command == "block_move_after":
                moving = next(n for n in d['nodes'] if n.get('block-id') == kwargs['src_block_ids'])
                d['nodes'].remove(moving)
                index = next(i for i, n in enumerate(d['nodes']) if n.get('block-id') == kwargs['block_id'])
                d['nodes'].insert(index + 1, moving)
            else:
                raise AssertionError(command)
        d["revision"] += 1
        if self.fail_update_after and self.fail_update_after in content:
            self.fail_update_after = None
            raise RemoteError("response lost", uncertain=True)
        return {}

    def preview(self, token, directory):
        if self.fail_preview:
            raise RemoteError("board export unavailable")
        return str(directory / (token + ".png"))
