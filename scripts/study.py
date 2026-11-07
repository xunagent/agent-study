#!/usr/bin/env python3
"""Portable CLI; the host Agent researches and produces reviewed lesson JSON."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from agent_study.engine import Engine
from agent_study.lark import Lark
from agent_study.model import StudyError, validate_config, validate_lesson, diagram_svg
from agent_study.storage import Local


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=os.environ.get("AGENT_STUDY_STATE", str(Path.home() / ".local/share/agent-study")))
    parser.add_argument("--profile", help="lark-cli account profile")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("validate"); p.add_argument("file"); p.add_argument("--config", action="store_true")
    p = sub.add_parser("diagram"); p.add_argument("file"); p.add_argument("--output", required=True)
    p = sub.add_parser("init"); p.add_argument("--folder", required=True); p.add_argument("--config", required=True)
    p = sub.add_parser("restore"); p.add_argument("homepage")
    p = sub.add_parser("resume"); p.add_argument("operation")
    sub.add_parser("daily")
    sub.add_parser("sync")
    sub.add_parser("schedule-prompt")
    p = sub.add_parser("configure"); p.add_argument("file")
    p = sub.add_parser("candidate"); p.add_argument("file")
    p = sub.add_parser("publish"); p.add_argument("file"); p.add_argument("--mode", choices=("daily", "specified"), default="daily")
    p = sub.add_parser("status"); p.add_argument("status", choices=("待学习", "阅读中", "已读", "已跳过")); p.add_argument("--material")
    p = sub.add_parser("select"); p.add_argument("material")
    p = sub.add_parser("topic"); p.add_argument("topic")
    p = sub.add_parser("review"); p.add_argument("topic")
    p = sub.add_parser("questions"); p.add_argument("--material"); p.add_argument("--user-requested", action="store_true")
    p = sub.add_parser("reply"); p.add_argument("file"); p.add_argument("--material"); p.add_argument("--request-id", required=True); p.add_argument("--user-requested", action="store_true")
    args = parser.parse_args(argv)
    cmd = args.command
    if cmd == "doctor":
        result = {"python": sys.version.split()[0], "python_supported": sys.version_info >= (3, 10),
                  "lark_cli": bool(shutil.which("lark-cli")), "host_requirements": ["network search/read", "file access", "Python execution"],
                  "scheduling": "Provided by your host; manual execution always supported"}
        if result["lark_cli"]:
            result["lark_version"] = subprocess.run(["lark-cli", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        return result
    if sys.version_info < (3, 10):
        raise StudyError("Python 3.10+ required. Choose a newer Python executable or use uv run --python 3.12")
    if cmd == "validate":
        value = (validate_config if args.config else validate_lesson)(read_json(args.file))
        return {"valid": True, "material_id": value.get("material_id")}
    if cmd == "diagram":
        value = validate_lesson(read_json(args.file))
        Path(args.output).write_text(diagram_svg(value["diagram"]), encoding="utf-8")
        return {"svg": str(Path(args.output).resolve())}
    local = Local(args.state_dir)
    profile = args.profile or local.read().get("lark_profile")
    engine = Engine(Lark(profile), local)
    def execute():
        if cmd == "init": return engine.init(args.folder, read_json(args.config))
        if cmd == "restore": return engine.restore(args.homepage)
        if cmd == "resume": return engine.resume(args.operation)
        if cmd == "daily": return engine.daily()
        if cmd == "sync": return engine.sync_indexes()
        if cmd == "configure": return engine.configure(read_json(args.file))
        if cmd == "candidate": return engine.candidate(read_json(args.file))
        if cmd == "publish": return engine.publish(read_json(args.file), args.mode)
        if cmd == "status": return engine.set_status(args.status, args.material)
        if cmd == "select": return engine.select(args.material)
        if cmd == "topic": return engine.topic(args.topic)
        if cmd == "review": return engine.review(args.topic)
        if cmd == "questions": return engine.questions(args.material, args.user_requested)
        if cmd == "reply": return engine.reply(args.material, Path(args.file).read_text(encoding="utf-8"), args.request_id, args.user_requested)
        if cmd == "schedule-prompt": return engine.schedule_prompt()
        raise StudyError("Unknown command")
    with local.lock():
        if args.profile:
            saved = local.read()
            saved["lark_profile"] = args.profile
            local.write(saved)
        if cmd in ("daily", "restore", "questions", "review", "schedule-prompt", "init"):
            return execute()
        with engine.writer():
            return execute()


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "data": main()}, ensure_ascii=False, indent=2))
    except (StudyError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
