"""Lark CLI boundary. All mutations use user identity and structured stdin."""
from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .model import StudyError, digest


class RemoteError(StudyError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def xml_root(content: str):
    # The CLI returns fragments as well as document wrappers.
    if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
        raise StudyError("Unsupported document XML declaration")
    try:
        return ET.fromstring("<root>" + content + "</root>")
    except ET.ParseError as exc:
        raise StudyError("Cannot parse Lark XML; inspect the installed CLI format") from exc


def node_text(node):
    return "".join(node.itertext())


def block_id(node):
    return node.get("block-id") or node.get("block_id") or node.get("id")


def json_values(content):
    for node in xml_root(content).iter("pre"):
        try:
            value = json.loads(node_text(node))
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("agent_study") == 1:
            yield value


class Lark:
    def __init__(self, profile=None, timeout=90):
        self.profile = profile
        self.timeout = timeout

    def call(self, args, content=None):
        command = ["lark-cli"]
        if self.profile:
            command += ["--profile", self.profile]
        command += args + ["--as", "user", "--format", "json"]
        if content is not None:
            command += ["--content", "-"]
        try:
            result = subprocess.run(command, input=content, text=True, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise RemoteError("Lark request timed out; inspect remote state before retrying writes", uncertain=True) from exc
        except FileNotFoundError as exc:
            raise StudyError("Install the official @larksuite/cli first") from exc
        try:
            response = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        except ValueError as exc:
            raise RemoteError(f"Lark returned an unreadable response (exit {result.returncode}); credentials and raw output suppressed", uncertain=True) from exc
        if result.returncode or response.get("ok") is not True:
            error = response.get("error", {})
            # Raw errors may contain URLs/credentials. Return categories only.
            raise RemoteError(f'Lark error {error.get("type", "unknown")}/{error.get("subtype", "unknown")} code={error.get("code", result.returncode)}; use lark-cli auth/status or the relevant command to diagnose', uncertain=error.get("type") in ("network", "internal", "upstream"))
        data = response.get("data", {})
        if data.get("result") in ("partial_success", "failed") or data.get("warnings"):
            raise RemoteError("Lark reported partial completion or warnings; inspect and resume the existing document", uncertain=True)
        return data

    def list_docs(self, folder):
        files, seen, page = [], set(), ""
        while True:
            params = {"folder_token": folder, "page_size": 200}
            if page:
                params["page_token"] = page
            data = self.call(["drive", "files", "list", "--params", json.dumps(params)])
            files.extend(f for f in data.get("files", []) if f.get("type") == "docx")
            if not data.get("has_more"):
                return files
            page = data.get("next_page_token")
            if not page or page in seen:
                raise StudyError("Incomplete folder pagination; refusing to infer that a document is absent")
            seen.add(page)

    def create(self, folder, title, content):
        data = self.call(["docs", "+create", "--parent-token", folder, "--title", title], content)
        doc = data["document"]
        return {"token": doc["document_id"], "url": doc["url"], "name": title}

    def fetch(self, doc, **scope):
        args = ["docs", "+fetch", "--doc", doc, "--detail", "full"]
        for key, value in scope.items():
            args += ["--" + key.replace("_", "-"), str(value)]
        # Discard reference_map, which may contain comments unrelated to this task.
        return self.call(args)["document"]

    def section(self, doc, title):
        outline = self.fetch(doc, scope="outline", max_depth=1)
        headings = [n for n in xml_root(outline["content"]).iter() if n.tag == "h1" and node_text(n).strip() == title]
        if len(headings) != 1 or not block_id(headings[0]):
            raise StudyError(f"Missing or ambiguous section {title}; restore its original heading")
        heading_id = block_id(headings[0])
        section = self.fetch(doc, scope="section", start_block_id=heading_id)
        section["heading_id"] = heading_id
        return section

    def update(self, doc, content, command="append", **kwargs):
        args = ["docs", "+update", "--doc", doc, "--command", command]
        for key, value in kwargs.items():
            args += ["--" + key.replace("_", "-"), str(value)]
        return self.call(args, content)

    def preview(self, token, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        # Feishu chooses PNG or JPEG. A forced .png rejects valid JPEG exports.
        name = "board-" + digest(token)
        command = ["lark-cli"] + (["--profile", self.profile] if self.profile else [])
        command += ["whiteboard", "+export", "--whiteboard-token", token, "--output-type", "preview", "--output", "./" + name, "--overwrite", "--as", "user", "--format", "json"]
        try:
            result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise RemoteError("Diagram preview timed out; resume publication") from exc
        try:
            response = json.loads(result.stdout)
            output = response["data"]["preview_image_path"]
            path = (directory / output).resolve()
        except (ValueError, KeyError, TypeError) as exc:
            raise RemoteError("Diagram export response has no usable image path; resume publication") from exc
        if path.parent != directory.resolve():
            raise RemoteError("Diagram export path escaped its private preview directory")
        if result.returncode or response.get("ok") is not True or not path.is_file():
            raise RemoteError("Diagram preview unavailable; publication remains incomplete")
        header = path.read_bytes()[:8]
        if not (header == b"\x89PNG\r\n\x1a\n" or header.startswith(b"\xff\xd8\xff")):
            raise RemoteError("Diagram preview unavailable; publication remains incomplete")
        return str(path)
