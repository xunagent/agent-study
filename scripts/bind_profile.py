#!/usr/bin/env python3
"""Bind an already-created Lark app without echoing its secret or replacing profiles."""
import argparse
import getpass
import json
import subprocess
import sys


def bind(profile, app_id, brand, secret_reader=getpass.getpass):
    result = subprocess.run(["lark-cli", "profile", "list"], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError("Cannot inspect existing profiles; no configuration changed")
    profiles = json.loads(result.stdout)
    if not isinstance(profiles, list):
        raise RuntimeError("Unexpected profile response; no configuration changed")
    if any(p["name"] == profile and p["appId"] != app_id for p in profiles):
        raise RuntimeError("Profile name belongs to another app; choose a new name")
    secret = secret_reader("App Secret（隐藏输入，粘贴后按回车）：").strip()
    if not secret:
        raise RuntimeError("Empty secret; no configuration changed")
    try:
        result = subprocess.run(["lark-cli", "config", "init", "--name", profile,
                                 "--app-id", app_id, "--app-secret-stdin", "--brand", brand],
                                input=secret + "\n", capture_output=True, text=True, timeout=90)
    finally:
        secret = None
    if result.returncode:
        raise RuntimeError("CLI binding/check failed. Inspect profile status; raw output suppressed to protect credentials")
    print("应用配置已保存：" + profile + "。请返回聊天，继续用户登录授权。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", required=True)
    p.add_argument("--app-id", required=True)
    p.add_argument("--brand", choices=("feishu", "lark"), default="feishu")
    args = p.parse_args()
    if not sys.stdin.isatty():
        p.error("Run in your own terminal so the App Secret can be entered without echo")
    try:
        bind(args.profile, args.app_id, args.brand)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
