"""Validated inputs, stable source identities and safe document construction."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


STATUSES = ("待学习", "阅读中", "已读", "已跳过")
TOPICS = ("执行循环", "工具调用", "上下文管理", "记忆与检索", "规划与长任务", "多 Agent 协作", "评测", "工程可靠性")
SECTIONS = {
    "why": "为什么学这一篇", "problem": "问题与背景", "claims": "核心观点",
    "solution": "解决方案", "evidence": "证据与边界", "application": "工程启发",
}


class StudyError(Exception):
    """An actionable failure that is safe to show to the user."""


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def required_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StudyError(f"{field} must be a non-empty string")
    return value.strip()


def public_url(value: str) -> str:
    value = required_text(value, "url")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise StudyError("Source links must be HTTPS URLs without credentials")
    return value


def source_identity(source: dict) -> str:
    url = public_url(source.get("url"))
    parts = urlsplit(url)
    kind = source.get("kind")
    if kind not in ("paper", "official_doc", "official_blog", "source_code"):
        raise StudyError("Unsupported source kind")
    if kind == "paper":
        arxiv = re.search(r"(?:abs/|pdf/|html/)(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", parts.path)
        if parts.hostname in ("arxiv.org", "www.arxiv.org", "export.arxiv.org") and arxiv:
            return "arxiv:" + arxiv.group(1)
        doi = source.get("doi")
        if parts.hostname in ("doi.org", "dx.doi.org"):
            doi = parts.path.lstrip("/")
        if doi:
            doi = re.sub(r"^https?://(?:dx\.)?doi.org/", "", doi).strip().lower()
            if not re.match(r"^10\.\d{4,9}/\S+$", doi):
                raise StudyError("Invalid DOI")
            return "doi:" + doi
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_") and k not in ("ref", "trk")))
    canonical = urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/"), query, parts.fragment))
    if kind == "source_code":
        # Commit is tracked as a version. Logical module identity is stable across commits.
        canonical = public_url(source.get("module_url", url))
    return kind + ":" + canonical


def validate_config(config: dict) -> dict:
    config = dict(config)
    for key in ("level", "goal", "language", "timezone"):
        required_text(config.get(key), key)
    try:
        ZoneInfo(config["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise StudyError("Unknown IANA timezone; install tzdata if needed") from exc
    if not isinstance(config.get("topics"), list) or not config["topics"]:
        raise StudyError("topics must be a non-empty list")
    config["topics"] = list(dict.fromkeys(required_text(x, "topic") for x in config["topics"]))
    products = config.get("products", ["Codex", "Claude Code", "Agent SDKs"])
    if not isinstance(products, list):
        raise StudyError("products must be a list")
    config["products"] = [required_text(x, "product") for x in products]
    config.setdefault("schedule", {"enabled": False, "time": "09:00", "notification": "host"})
    schedule = config["schedule"]
    if not isinstance(schedule, dict) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", schedule.get("time", "")):
        raise StudyError("schedule.time must be HH:MM")
    if schedule.get("notification") not in ("host", "none", "feishu"):
        raise StudyError("Unknown notification channel")
    if not isinstance(schedule.get("enabled", False), bool):
        raise StudyError("schedule.enabled must be a boolean")
    minutes = config.get("reading_minutes", 10)
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 3 <= minutes <= 120:
        raise StudyError("reading_minutes must be an integer between 3 and 120")
    config["reading_minutes"] = minutes
    if schedule.get("notification") == "feishu" and not schedule.get("chat_id"):
        raise StudyError("Feishu notifications require an explicitly selected chat_id")
    config["schema_version"] = 1
    return config


def validate_lesson(lesson: dict) -> dict:
    if not isinstance(lesson, dict):
        raise StudyError("Lesson must be a JSON object")
    for key in ("title", "summary", "recommendation"):
        required_text(lesson.get(key), key)
    source = lesson.get("source", {})
    identity = source_identity(source)
    for key in ("title", "authors", "version", "accessed_at", "locator", "reading_scope"):
        required_text(source.get(key), "source." + key)
    try:
        date.fromisoformat(source["accessed_at"])
    except ValueError as exc:
        raise StudyError("source.accessed_at must be YYYY-MM-DD") from exc
    if source["reading_scope"] not in ("full_text", "relevant_sections", "source_code"):
        raise StudyError("Abstract-only materials must remain candidates")
    if source["kind"] == "source_code" and not re.fullmatch(r"[0-9a-fA-F]{7,40}", source["version"]):
        raise StudyError("Source-code lessons require a commit hash as version")
    if not isinstance(lesson.get("topics"), list) or not lesson["topics"]:
        raise StudyError("At least one topic is required")
    for topic in lesson["topics"]:
        required_text(topic, "topic")
    sections = lesson.get("sections", {})
    for key in SECTIONS:
        required_text(sections.get(key), "sections." + key)
    references = lesson.get("references", [])
    if not references:
        raise StudyError("At least one evidence reference is required")
    for ref in references:
        public_url(ref.get("url"))
        for key in ("claim", "locator", "basis"):
            required_text(ref.get(key), "reference." + key)
        if ref["basis"] not in ("author_claim", "reported_evidence", "implementation", "inference"):
            raise StudyError("Invalid evidence basis")
    graph = lesson.get("diagram", {})
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    if not 2 <= len(nodes) <= 8 or not edges:
        raise StudyError("A diagram requires 2–8 nodes and at least one edge")
    ids = [required_text(n.get("id"), "node.id") for n in nodes]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", x) for x in ids):
        raise StudyError("Diagram node IDs must be unique ASCII identifiers")
    for node in nodes:
        label = required_text(node.get("label"), "node.label")
        if len(label) > 30:
            raise StudyError("Diagram labels must be at most 30 characters")
    for edge in edges:
        if edge.get("from") not in ids or edge.get("to") not in ids:
            raise StudyError("Diagram edge references an unknown node")
        if len(edge.get("label", "")) > 24:
            raise StudyError("Diagram edge labels must be at most 24 characters")
    pseudo = lesson.get("pseudocode", {})
    required_text(pseudo.get("code"), "pseudocode.code")
    if pseudo.get("basis") not in ("source_algorithm", "teaching_reconstruction"):
        raise StudyError("Pseudocode must declare its provenance")
    required_text(pseudo.get("explanation"), "pseudocode.explanation")
    if lesson.get("reviewed") is not True:
        raise StudyError("Host must review evidence, diagram and pseudocode before publishing")
    return {**lesson, "material_id": identity}


def paragraph(text: str) -> str:
    return "".join("<p>" + escape(p).replace("\n", "<br/>") + "</p>" for p in text.split("\n\n") if p)


def code_block(text: str, language="text") -> str:
    return f'<pre lang="{escape(language, quote=True)}"><code>{escape(text)}</code></pre>'


def json_block(value) -> str:
    return code_block(json.dumps(value, ensure_ascii=False, sort_keys=True), "json")


def link(url: str, title: str) -> str:
    public_url(url)
    return f'<a href="{escape(url, quote=True)}">{escape(title)}</a>'


def diagram_svg(graph: dict) -> str:
    """Deterministic single-column flow with side lanes for branches/back edges."""
    nodes = graph["nodes"]
    height = len(nodes) * 116 + 50
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" viewBox="0 0 900 {height}">',
              f'<rect width="900" height="{height}" fill="#f7f9fc"/>']
    positions = {n["id"]: i * 116 + 35 for i, n in enumerate(nodes)}
    order = {n["id"]: i for i, n in enumerate(nodes)}
    for i, edge in enumerate(graph["edges"]):
        start, end = edge["from"], edge["to"]
        y1, y2 = positions[start] + 32, positions[end] + 32
        if order[end] == order[start] + 1:
            points = f'400,{y1+32} 400,{y2-32}'
            arrow = f'394,{y2-40} 400,{y2-32} 406,{y2-40}'
            tx, ty = 420, (y1 + y2) / 2 + 5
        else:
            if order[end] <= order[start]:
                lane = 155 - (i % 3) * 42
                points = f'210,{y1} {lane},{y1} {lane},{y2} 210,{y2}'
                arrow = f'202,{y2-6} 210,{y2} 202,{y2+6}'
                tx, ty = lane + 6, (y1 + y2) / 2
            else:
                lane = 650 + (i % 3) * 48
                points = f'590,{y1} {lane},{y1} {lane},{y2} 590,{y2}'
                arrow = f'598,{y2-6} 590,{y2} 598,{y2+6}'
                tx, ty = lane + 6, (y1 + y2) / 2
        pieces.append(f'<polyline points="{points}" fill="none" stroke="#526882" stroke-width="2"/>')
        pieces.append(f'<polyline points="{arrow}" fill="none" stroke="#526882" stroke-width="2"/>')
        pieces.append(f'<text x="{tx}" y="{ty}" fill="#405571" font-size="14">{escape(edge.get("label", ""))}</text>')
    for i, node in enumerate(nodes):
        y = positions[node["id"]]
        pieces.append(f'<rect x="210" y="{y}" width="380" height="64" rx="12" fill="#e6efff" stroke="#6393ce"/>')
        pieces.append(f'<text x="225" y="{y+38}" font-size="17" fill="#18334f">{i+1}. {escape(node["label"])}</text>')
    return "".join(pieces) + "</svg>"


def lesson_parts(lesson: dict) -> list[tuple[str, str]]:
    source = lesson["source"]
    info = paragraph(lesson["summary"]) + "<p>" + link(source["url"], source["title"]) + "</p>"
    info += paragraph(f'{source["authors"]} · {source["kind"]} · {source["version"]}\n读取于 {source["accessed_at"]} · {source["locator"]}\n主题 {" / ".join(lesson["topics"])}')
    parts = [("材料信息", info)]
    for key in ("why", "problem", "claims", "solution"):
        parts.append((SECTIONS[key], paragraph(lesson["sections"][key])))
    parts.append(("流程图", '<whiteboard type="svg">' + diagram_svg(lesson["diagram"]) + '</whiteboard>' + code_block(json.dumps(lesson["diagram"], ensure_ascii=False, indent=2, sort_keys=True), "json")))
    pseudo = lesson["pseudocode"]
    parts.append(("框架伪代码", paragraph(pseudo["basis"] + "\n" + pseudo["explanation"]) + code_block(pseudo["code"], "python")))
    for key in ("evidence", "application"):
        parts.append((SECTIONS[key], paragraph(lesson["sections"][key])))
    citations = "".join("<p>" + link(r["url"], r["locator"]) + "</p>" + paragraph(r["basis"] + " · " + r["claim"]) for r in lesson["references"])
    parts.append(("证据定位", citations))
    return parts
