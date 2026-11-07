"""Cloud-backed learning workflow. Journal events are append-only and replayable."""
from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from html import escape
from zoneinfo import ZoneInfo

from .lark import RemoteError, block_id, json_values, node_text, xml_root
from .model import (StudyError, STATUSES, digest, json_block, code_block, lesson_parts, link,
                    paragraph, source_identity, validate_config, validate_lesson)


SYSTEM = {
    "home": "Agent Study · 学习首页", "journal": "Agent Study · 运行记录",
    "config": "Agent Study · 个人配置", "route": "Agent Study · 学习路线",
    "materials": "Agent Study · 材料索引", "topics": "Agent Study · 主题索引",
    "history": "Agent Study · 阅读历史",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def body_nodes(content):
    root = xml_root(content)
    # CLI may return a <doc> wrapper rather than a flat fragment.
    for node in list(root):
        if node.tag in ("doc", "document", "body", "fragment"):
            return list(node)
    return list(root)


def text_fingerprint(content):
    root = xml_root(content)
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "whiteboard":
                parent.remove(child)
    return re.sub(r"\s+", "", node_text(root))


def status_checkbox(status):
    label = "已读" if status in ("待学习", "已读") else "已读（当前：" + status + "）"
    return '<checkbox done="' + ('true' if status == '已读' else 'false') + '">' + label + '</checkbox>'


def status_nodes(content):
    return [n for n in xml_root(content).iter() if
            (n.tag == 'p' and node_text(n).strip() in STATUSES) or
            (n.tag == 'checkbox' and node_text(n).strip() in ('已读', '已读（当前：阅读中）', '已读（当前：已跳过）'))]


def read_status(content):
    nodes = status_nodes(content)
    if len(nodes) != 1:
        raise StudyError('Reading status is missing or ambiguous; inspect the status block')
    node = nodes[0]
    label = node_text(node).strip()
    if node.tag == 'p':
        return label
    checked = node.get('done')
    if checked not in ('true', 'false'):
        raise StudyError('Checkbox completion value is missing or unsupported')
    if checked == 'true':
        return '已读'
    return {'已读': '待学习', '已读（当前：阅读中）': '阅读中', '已读（当前：已跳过）': '已跳过'}[label]


class Engine:
    def __init__(self, remote, local):
        self.remote, self.local = remote, local
        self.binding = local.binding()
        self.lease_id = None

    def doc(self, key):
        if not self.binding or key not in self.binding.get("docs", {}):
            raise StudyError("Run init or restore with your learning homepage first")
        return self.binding["docs"][key]

    def events(self):
        values = list(json_values(self.remote.fetch(self.doc("journal")["token"])["content"]))
        events, seen = [], {}
        for event in values:
            if "event_id" not in event:
                continue
            eid = event["event_id"]
            if eid in seen and seen[eid] != event:
                raise StudyError("Conflicting cloud events; preserve both and inspect the runtime document")
            if eid not in seen:
                events.append(event)
                seen[eid] = event
        return events

    def event(self, kind, payload, eid=None):
        if kind not in ("lease", "release"):
            self.check_writer()
        eid = eid or uuid.uuid4().hex
        old = next((e for e in self.events() if e["event_id"] == eid), None)
        if old:
            if old["kind"] != kind or old["payload"] != payload:
                raise StudyError("Operation identity already used with different content")
            return old
        value = {"agent_study": 1, "event_id": eid, "kind": kind, "time": now(), "payload": payload}
        try:
            # Lease acquisition/release must work before/after an active lease.
            self.remote.update(self.doc("journal")["token"], json_block(value))
        except RemoteError:
            if not any(e["event_id"] == eid for e in self.events()):
                raise
        if not any(e["event_id"] == eid for e in self.events()):
            raise StudyError("Cloud event not visible yet; resume later, without recreating documents")
        return value

    def state(self):
        state = {"materials": {}, "candidates": {}, "current": None, "config": None, "topic": None,
                 "intents": {}, "parts": {}, "daily": {}, "payloads": {}, "complete": set(), "events": self.events()}
        for e in state["events"]:
            kind, p = e["kind"], e["payload"]
            if kind == "config":
                state["config"] = p
            elif kind == "topic":
                state["topic"] = p["topic"]
            elif kind == "candidate":
                state["candidates"][p["material_id"]] = p
            elif kind == "intent":
                state["intents"][p["operation"]] = p
            elif kind == "part":
                state["parts"][(p["operation"], p["heading"])] = p
            elif kind == "payload":
                state["payloads"][p["operation"]] = p
            elif kind == "published":
                old = state["materials"].get(p["material_id"], {})
                state["materials"][p["material_id"]] = {**old, **p}
                state["candidates"].pop(p["material_id"], None)
                state["complete"].add(p["operation"])
                state["current"] = p["material_id"]
                if p.get("mode") == "daily":
                    state["daily"][p["day"]] = p["material_id"]
            elif kind == "current":
                state["current"] = p["material_id"]
            elif kind == "status" and p["material_id"] in state["materials"]:
                state["materials"][p["material_id"]]["status"] = p["status"]
            elif kind == "status_block" and p["material_id"] in state["materials"]:
                state["materials"][p["material_id"]]["status_block"] = p["status_block"]
            elif kind == "status_binding" and p["material_id"] in state["materials"]:
                state["materials"][p["material_id"]].update(p)
        return state

    def ensure_doc(self, title, content, operation):
        self.check_writer()
        files = self.remote.list_docs(self.binding['folder'])
        saved = self.local.pending(operation) or {}
        events = self.events() if 'journal' in self.binding['docs'] else []
        known = next((e['payload']['doc'] for e in events if e['kind'] == 'created' and e['payload']['operation'] == operation), saved.get('doc'))
        if known:
            found = next((d for d in files if d['token'] == known['token']), None)
            if not found:
                raise StudyError('Previously created document is missing; do not recreate it automatically')
            return known
        matches = [d for d in files if d["name"] == title]
        if len(matches) > 1:
            raise StudyError("Duplicate remote document titles detected; reconcile them before continuing: " + title)
        if matches:
            if not operation.startswith('system:') and not saved and not any(e['kind'] == 'intent' and e['payload']['operation'] == operation for e in events):
                raise StudyError('An unrelated document already has this title; choose a distinct descriptive title')
            self.local.pending(operation, {"doc": matches[0], "phase": "created"})
            if 'journal' in self.binding['docs']:
                self.event('created', {'operation': operation, 'doc': matches[0]}, 'created:' + operation)
            return matches[0]
        pending = self.local.pending(operation)
        if pending:
            raise StudyError("An earlier creation may have succeeded but is not visible. Check the folder and resume later: " + title)
        # A remote intent from a different device prevents uncertain automatic recreation.
        if "journal" in self.binding["docs"] and operation in self.state()["intents"]:
            raise StudyError("Cloud creation intent exists but its document is missing; inspect the folder before recovery")
        if "journal" in self.binding["docs"]:
            self.event("intent", {"operation": operation, "title": title}, "intent:" + operation)
        self.local.pending(operation, {"phase": "creating", "title": title})
        try:
            self.check_writer()
            doc = self.remote.create(self.binding["folder"], title, content)
        except RemoteError:
            matches = [d for d in self.remote.list_docs(self.binding["folder"]) if d["name"] == title]
            if len(matches) != 1:
                raise
            doc = matches[0]
        self.local.pending(operation, {"doc": doc, "phase": "created"})
        if 'journal' in self.binding['docs']:
            self.event('created', {'operation': operation, 'doc': doc}, 'created:' + operation)
        return doc

    def diagram_source(self, doc, title, graph, operation):
        existing = next((e['payload']['source'] for e in self.events() if e['event_id'] == 'diagram-source:' + operation), None)
        if existing:
            return existing
        source = self.ensure_doc(title + ' · 图示源文件',
            '<h1>结构化图源</h1>' + code_block(json.dumps(graph, ensure_ascii=False, indent=2), 'json') +
            '<h1>生成记录</h1>', 'diagram-source:' + operation)
        self.event('diagram_source', {'doc': doc['token'], 'operation': operation, 'source': source}, 'diagram-source:' + operation)
        return source

    def init(self, folder, config):
        config = validate_config(config)
        if not re.fullmatch(r"[A-Za-z0-9]+", folder):
            raise StudyError("folder must be the folder token, not a URL")
        if self.binding and self.binding["folder"] != folder:
            raise StudyError("This local profile is bound to another library; use a separate --state-dir")
        self.binding = self.binding or {"agent_study": 1, "library_id": uuid.uuid4().hex, "folder": folder, "docs": {}}
        self.local.binding(self.binding)
        for key, title in SYSTEM.items():
            if key in self.binding["docs"]:
                continue
            content = "<h1>" + escape(title) + "</h1>"
            if key == "home":
                content += paragraph("每天学习一篇；读完或跳过后继续。个人疑问与感悟仅在你主动要求时读取。")
            self.binding["docs"][key] = self.ensure_doc(title, content, "system:" + key)
            self.local.binding(self.binding)
        # A complete binding lives in the homepage. Repeating init never overwrites it.
        home = self.remote.fetch(self.doc("home")["token"])["content"]
        existing = [v for v in json_values(home) if v.get("record") == "binding"]
        if existing:
            saved = existing[-1]["binding"]
            if saved["folder"] != folder:
                raise StudyError("Homepage belongs to a different folder")
            self.binding = saved
            self.local.binding(saved)
        else:
            self.write(self.doc("home")["token"],
                "".join("<p>" + link(d["url"], SYSTEM[k]) + "</p>" for k, d in self.binding["docs"].items() if k != "home") +
                json_block({"agent_study": 1, "record": "binding", "binding": self.binding}))
        state = self.state()
        if state["config"] is None:
            self.configure(config)
        self.sync_indexes()
        return {"home": self.doc("home")["url"], "config": self.state()["config"]}

    def restore(self, homepage):
        values = list(json_values(self.remote.fetch(homepage)["content"]))
        records = [v["binding"] for v in values if v.get("record") == "binding"]
        if len(records) != 1:
            raise StudyError("Homepage has no unique recovery record")
        binding = records[0]
        if binding.get("agent_study") != 1 or set(SYSTEM) - set(binding.get("docs", {})):
            raise StudyError("Incomplete library binding")
        self.binding = binding
        state = self.state()  # Verify access before replacing local binding.
        self.local.binding(binding)
        return {"home": self.doc("home")["url"], "current": state["current"], "config": state["config"]}

    @contextmanager
    def writer(self):
        owner = digest(str(self.local.directory))
        def active():
            events = self.events()
            released = {e["payload"]["lease"] for e in events if e["kind"] == "release"}
            return [e for e in events if e["kind"] == "lease" and e["event_id"] not in released and e["payload"]["expires"] > now()]
        if any(e["payload"]["owner"] != owner for e in active()):
            raise StudyError("Another device has an active write lease. Retry after it finishes or the lease expires")
        self.lease_id = uuid.uuid4().hex
        self.event("lease", {"owner": owner, "expires": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}, self.lease_id)
        try:
            if any(e["payload"]["owner"] != owner for e in active()):
                raise StudyError("Concurrent writer detected; keep both run records and retry later")
            yield
        finally:
            self.event("release", {"lease": self.lease_id})
            self.lease_id = None

    def check_writer(self):
        if not self.lease_id:
            return
        events = self.events()
        released = {e["payload"]["lease"] for e in events if e["kind"] == "release"}
        own = next((e for e in events if e["event_id"] == self.lease_id), None)
        if not own or own["payload"]["expires"] <= now():
            raise StudyError("Write lease expired; resume in a new run")
        if any(e["kind"] == "lease" and e["event_id"] not in released and
               e["payload"]["expires"] > now() and e["payload"]["owner"] != own["payload"]["owner"] for e in events):
            raise StudyError("Concurrent device appeared; stop writing and reconcile run records")

    def write(self, doc, content, **kwargs):
        self.check_writer()
        return self.remote.update(doc, content, **kwargs)

    def configure(self, config):
        config = validate_config(config)
        self.event("config", config)
        self.sync_indexes()
        return config

    def status_value(self, material):
        if material.get('status_mode') == 'manual':
            return material.get('status', '待学习'), {'content': '', 'status_source': 'conversation'}
        # Fetch exactly the stored status paragraph, never the full learning document.
        part = self.remote.fetch(material["doc"]["token"], scope="range",
                                 start_block_id=material["status_block"], end_block_id=material["status_block"], max_depth=0)
        return read_status(part['content']), part

    def use_manual_status(self, identity=None):
        state = self.state()
        identity = identity or state['current']
        material = state['materials'].get(identity)
        if not material:
            raise StudyError('No matching published material')
        self.event('status_binding', {'material_id': identity, 'status_mode': 'manual'})
        return {'status_mode': 'manual', 'url': material['doc']['url'],
                'message': 'Progress changes only when the user explicitly confirms it in conversation; widget clicks are not inferred'}

    def daily(self):
        state = self.state()
        config = state["config"]
        if not config:
            raise StudyError("Library has no configuration")
        pending = [p for op, p in state["payloads"].items() if op not in state["complete"]]
        if pending:
            return {"action": "resume_publication", "operation": pending[0]["operation"],
                    "title": pending[0]["lesson"]["title"], "message": "Resume the original cloud draft before selecting another material"}
        current = state["materials"].get(state["current"])
        if current:
            status, _ = self.status_value(current)
            if status in STATUSES[:2]:
                return {"action": "read_current", "title": current["title"], "url": current["doc"]["url"], "status": status}
        day = datetime.now(ZoneInfo(config["timezone"])).date().isoformat()
        if day in state["daily"]:
            item = state["materials"][state["daily"][day]]
            return {"action": "already_generated_today", "title": item["title"], "url": item["doc"]["url"]}
        readings = [{"material_id": k, "title": v["title"], "version": v["version"],
                     "status": self.status_value(v)[0]} for k, v in state["materials"].items()]
        return {"action": "select_material", "topic": state["topic"] or config["topics"][0],
                "config": config, "candidates": list(state["candidates"].values())[:12],
                "studied": [m for m in readings if m["status"] == "已读"],
                "other_readings": [m for m in readings if m["status"] != "已读"],
                "limits": {"screen": 12, "inspect": 3, "publish": 1}}

    def candidate(self, candidate):
        identity = source_identity(candidate["source"])
        if not candidate.get("reason") or not candidate.get("topics"):
            raise StudyError("Candidate needs reason and topics")
        self.event("candidate", {**candidate, "material_id": identity})
        return {"action": "collected", "material_id": identity}

    def fill_part(self, doc, heading, content, operation):
        previous = self.state()["parts"].get((operation, heading))
        if previous:
            # Published sections are immutable; never restore original text over user edits.
            return previous
        section = self.remote.section(doc["token"], heading)
        nodes = body_nodes(section["content"])
        populated = [n for n in nodes if n.tag != "h1" and (node_text(n).strip() or n.tag in ("whiteboard", "image"))]
        if not populated:
            try:
                self.write(doc["token"], content, command="block_insert_after",
                                   block_id=section["heading_id"], revision_id=section.get("revision_id", -1))
            except RemoteError:
                pass  # Read back before deciding whether any retry is safe.
            section = self.remote.section(doc["token"], heading)
        expected = text_fingerprint(content)
        actual = text_fingerprint(section["content"])
        if expected and expected not in actual:
            raise StudyError("Section incomplete or concurrently edited; preserve its content and repair before resuming: " + heading)
        # Verify hyperlinks and code survived rich-text conversion.
        wanted = [n.get("href") for n in xml_root(content).iter("a")]
        got = [n.get("href") for n in xml_root(section["content"]).iter("a")]
        if any(url not in got for url in wanted):
            raise StudyError("Missing link after publication: " + heading)
        if list(xml_root(content).iter("pre")) and not list(xml_root(section["content"]).iter("pre")):
            raise StudyError("Code block missing after publication: " + heading)
        previews = []
        if "<whiteboard" in content:
            boards = list(xml_root(section["content"]).iter("whiteboard"))
            tokens = [n.get("token") or n.get("whiteboard-token") or n.get("whiteboard_token") for n in boards]
            if not tokens or not all(tokens):
                raise StudyError("Rendered diagram missing; repair the existing section before resuming")
            previews = [self.remote.preview(t, self.local.directory / "previews") for t in tokens]
        p = {"operation": operation, "heading": heading, "doc": doc, "previews": previews}
        self.event("part", p, "part:" + digest([operation, heading]))
        return p

    def publish(self, lesson, mode="daily"):
        lesson = validate_lesson(lesson)
        if mode not in ("daily", "specified"):
            raise StudyError("Publish mode must be daily or specified")
        state = self.state()
        identity, version = lesson["material_id"], lesson["source"]["version"]
        operation = digest([identity, version])
        old = state["materials"].get(identity)
        if old and old["version"] == version:
            if mode == "specified" or not state["current"]:
                self.event("current", {"material_id": identity})
            self.sync_indexes()
            return {"action": "existing", "url": old["doc"]["url"], "title": old["title"]}
        if any(e["kind"] == "published" and e["payload"].get("operation") == operation for e in state["events"]):
            return {"action": "existing_version", "url": old["doc"]["url"], "title": old["title"]}
        if mode == "daily":
            decision = self.daily()
            if decision["action"] != "select_material" and not (decision["action"] == "resume_publication" and decision["operation"] == operation):
                return decision
        parts = lesson_parts(lesson)
        payload_key = "payload:" + operation
        payload_hash = digest(lesson)
        recorded = next((e for e in state["events"] if e["event_id"] == payload_key), None)
        if recorded and recorded["payload"]["hash"] != payload_hash:
            raise StudyError("An interrupted publication used different content; resume with the original JSON")
        self.event("payload", {"hash": payload_hash, "operation": operation, "mode": mode, "lesson": lesson}, payload_key)
        if old:
            doc, status_block = old["doc"], old["status_block"]
            prefix = "更新 " + version + " · "
            parts = [(prefix + h, c) for h, c in parts]
            outline = self.remote.fetch(doc["token"], scope="outline", max_depth=1)["content"]
            existing = {node_text(n).strip() for n in xml_root(outline).iter("h1")}
            missing = [h for h, _ in parts if h not in existing]
            if missing:
                self.write(doc["token"], "".join("<h1>" + escape(h) + "</h1>" for h in missing))
        else:
            title = lesson["title"]
            skeleton = '<h1>材料信息</h1>' + parts[0][1] + status_checkbox('待学习')
            skeleton += "".join("<h1>" + escape(h) + "</h1>" for h, _ in parts[1:])
            skeleton += "<h1>我的疑问与感悟</h1><p></p><h1>AI 讨论记录</h1><p></p>"
            doc = self.ensure_doc(title, skeleton, operation)
            section = self.remote.section(doc["token"], "材料信息")
            nodes = status_nodes(section['content'])
            if len(nodes) != 1 or not block_id(nodes[0]):
                raise StudyError("Reading status block missing; inspect the existing document")
            status_block = block_id(nodes[0])
        source_doc = self.diagram_source(doc, lesson['title'] + ' · ' + version, lesson['diagram'], operation)
        parts = [(h, c + ('<p>' + link(source_doc['url'], '图示源文件与生成提示词') + '</p>' if h.endswith('证据定位') else '')) for h, c in parts]
        previews = []
        for heading, content in parts:
            result = self.fill_part(doc, heading, content, operation)
            previews.extend(result["previews"])
        day = datetime.now(ZoneInfo(state["config"]["timezone"])).date().isoformat()
        entry = {"material_id": identity, "version": version, "title": lesson["title"], "doc": doc,
                 "topics": lesson["topics"], "source": lesson["source"], "status_block": status_block,
                 "status": old.get("status", "待学习") if old else "待学习", "mode": mode, "day": day,
                 "recommendation": lesson["recommendation"], "operation": operation}
        entry['status_section'] = old.get('status_section', '阅读状态') if old else '材料信息'
        self.event("published", entry, "published:" + operation)
        self.event("current", {"material_id": identity}, "current:" + operation)
        self.sync_indexes()
        return {"action": "published", "title": lesson["title"], "url": doc["url"], "recommendation": lesson["recommendation"], "diagram_previews": previews}

    def set_status(self, status, identity=None):
        if status not in STATUSES:
            raise StudyError("Unsupported reading status")
        state = self.state()
        identity = identity or state["current"]
        material = state["materials"].get(identity)
        if not material:
            raise StudyError("No matching published material")
        if material.get('status_mode') == 'manual':
            self.event('status', {'material_id': identity, 'status': status})
            self.sync_indexes()
            return {'status': status, 'url': material['doc']['url'], 'status_source': 'conversation'}
        current, part = self.status_value(material)
        if current != status or not list(xml_root(part['content']).iter('checkbox')):
            try:
                self.write(material["doc"]["token"], status_checkbox(status), command="block_replace",
                           block_id=material["status_block"], revision_id=part.get("revision_id", -1))
            except RemoteError:
                pass  # A lost response can still have replaced the block; read back below.
            # block_replace may allocate a new block ID. Resolve only the status section.
            section = self.remote.section(material["doc"]["token"], material.get('status_section', '阅读状态'))
            nodes = status_nodes(section['content'])
            if len(nodes) != 1 or not block_id(nodes[0]) or read_status(section['content']) != status:
                raise StudyError("Status write could not be verified")
            if block_id(nodes[0]) != material["status_block"]:
                material = {**material, "status_block": block_id(nodes[0])}
                self.event("status_block", {"material_id": identity, "status_block": material["status_block"]})
        self.event("status", {"material_id": identity, "status": status})
        self.sync_indexes()
        return {"status": status, "url": material["doc"]["url"]}

    def resume(self, operation):
        payload = self.state()["payloads"].get(operation)
        if not payload:
            raise StudyError("No cloud draft for this operation")
        return self.publish(payload["lesson"], payload["mode"])

    def select(self, identity):
        if identity not in self.state()["materials"]:
            raise StudyError("Material is not yet published; use publish --mode specified")
        self.event("current", {"material_id": identity})
        self.sync_indexes()
        return self.daily()

    def topic(self, topic):
        if topic not in self.state()["config"]["topics"]:
            raise StudyError("Add this topic to configuration first")
        self.event("topic", {"topic": topic})
        self.sync_indexes()
        return {"topic": topic}

    def questions(self, identity, explicit):
        if not explicit:
            raise StudyError("Personal reflections require an explicit user request")
        state = self.state()
        material = state["materials"].get(identity or state["current"])
        if not material:
            raise StudyError("No matching material")
        return self.remote.section(material["doc"]["token"], "我的疑问与感悟")

    def reply(self, identity, answer, request_id, explicit):
        if not explicit or not request_id or not answer.strip():
            raise StudyError("Discussion needs an explicit request, non-empty answer and stable request ID")
        state = self.state()
        material = state["materials"].get(identity or state["current"])
        if not material:
            raise StudyError("No matching material")
        eid = "discussion:" + digest([material["material_id"], request_id])
        section = self.remote.section(material["doc"]["token"], "AI 讨论记录")
        marker = "讨论记录 " + eid
        if marker not in node_text(xml_root(section["content"])):
            content = paragraph(marker + "\n" + now()) + paragraph(answer)
            self.write(material["doc"]["token"], content, command="block_insert_after", block_id=section["heading_id"], revision_id=section.get("revision_id", -1))
            section = self.remote.section(material["doc"]["token"], "AI 讨论记录")
            if marker not in node_text(xml_root(section["content"])):
                raise StudyError("Discussion write not yet visible; retry with the same request ID")
        return {"url": material["doc"]["url"], "request_id": request_id}

    def sync_indexes(self):
        """Append human-readable snapshots, never overwrite user additions in indexes."""
        state = self.state()
        config = state["config"]
        if not config:
            return
        materials = list(state["materials"].values())
        current = state["materials"].get(state["current"])
        payloads = {
            "home": ("<h2>当前学习</h2><p>" + link(current["doc"]["url"], current["title"]) + "</p>" +
                     paragraph("阅读状态以笔记顶部为准。未读期间复用当前篇；读完后告诉 Agent 继续学习。")
                     if current else paragraph("学习库已就绪，向 Agent 说：开始今天的学习。")),
            "config": json_block(config),
            "route": paragraph(" → ".join(config["topics"]) + "\n当前主题：" + (state["topic"] or config["topics"][0]) + "\n已读仅表示完成阅读，不代表掌握。根据前置知识讨论后调整路线。"),
            "materials": "".join("<p>" + link(m["doc"]["url"], m["title"]) + "</p>" + paragraph(m["material_id"] + " · " + m["version"]) for m in materials) or paragraph("尚无已发布材料"),
            "topics": "".join("<h2>" + escape(t) + "</h2>" + "".join("<p>" + link(m["doc"]["url"], m["title"]) + "</p>" for m in materials if t in m["topics"]) for t in config["topics"]),
            "history": paragraph("\n".join(e["time"] + " " + e["kind"] + " " + json.dumps(e["payload"], ensure_ascii=False) for e in state["events"] if e["kind"] in ("status", "current", "topic")) or "尚无阅读历史"),
        }
        for key, content in payloads.items():
            marker = "快照 " + digest(content)
            current = self.remote.fetch(self.doc(key)["token"])["content"]
            if marker not in node_text(xml_root(current)):
                self.write(self.doc(key)["token"], "<h1>" + marker + "</h1>" + content)
                if marker not in node_text(xml_root(self.remote.fetch(self.doc(key)["token"])["content"])):
                    raise StudyError("Index update not visible; resume sync on the existing library")
        return {"action": "indexes_synced"}

    def review(self, topic):
        """Return reading content only; never include the reflections/discussion sections."""
        state = self.state()
        items = [m for m in state["materials"].values() if topic in m["topics"]]
        result = []
        for m in items:
            status, _ = self.status_value(m)
            if status != "已读":
                continue
            sections = {}
            for heading in ("核心观点", "解决方案", "证据与边界", "工程启发"):
                updated = "更新 " + m["version"] + " · " + heading
                anchor = updated if (m["operation"], updated) in state["parts"] else heading
                sections[heading] = self.remote.section(m["doc"]["token"], anchor)["content"]
            result.append({"title": m["title"], "url": m["doc"]["url"], "source": m["source"], "sections": sections})
        return {"topic": topic, "materials": result}

    def schedule_prompt(self):
        config = self.state()["config"]
        return {"time": config["schedule"]["time"], "timezone": config["timezone"],
                "enabled": config["schedule"].get("enabled", False), "host_must_schedule": True,
                "prompt": "使用 agent-study Skill，从学习首页 " + self.doc("home")["url"] +
                " 恢复状态并开始今天的学习。当前未读时只返回该篇；重要进展进入候选池。不要读取我的疑问与感悟。每天最多生成一篇，最终返回标题、推荐原因和飞书链接。定时通知走宿主已配置渠道。"}
