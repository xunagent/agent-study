#!/usr/bin/env python3
"""Publish an inspected AIGC diagram to an existing study note, using user identity."""
import argparse
import json
import os
from pathlib import Path
import sys

from agent_study.artwork import replace_artwork
from agent_study.engine import Engine
from agent_study.lark import Lark
from agent_study.model import StudyError
from agent_study.storage import Local


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir', default=os.environ.get('AGENT_STUDY_STATE', str(Path.home() / '.local/share/agent-study')))
    p.add_argument('--profile')
    p.add_argument('--material', help='Defaults to the current study material')
    p.add_argument('--image')
    p.add_argument('--prompt')
    p.add_argument('--expected-block')
    p.add_argument('--expected-revision', type=int)
    p.add_argument('--uploaded-block')
    p.add_argument('--image-token')
    p.add_argument('--reviewed', action='store_true')
    args = p.parse_args()
    local = Local(Path(args.state_dir).resolve())
    remote = Lark(args.profile or local.read().get('lark_profile'))
    engine = Engine(remote, local)
    state = engine.state()
    material = state['materials'].get(args.material or state['current'])
    if not material:
        raise StudyError('No matching published material')
    heading = '流程图'
    version_heading = '更新 ' + material['version'] + ' · ' + heading
    if (material['operation'], version_heading) in state['parts']:
        heading = version_heading
    doc = material['doc']['token']
    if not args.image:
        return {'doc': doc, 'heading': heading, **remote.section(doc, heading)}
    if not (args.reviewed and args.prompt and args.expected_block and args.expected_revision is not None and args.uploaded_block and args.image_token):
        raise StudyError('Upload and inspect first; provide --prompt, --expected-block, --expected-revision, --uploaded-block, --image-token and --reviewed')
    image = Path(args.image).resolve()
    prompt = Path(args.prompt).read_text(encoding='utf-8')
    image_bytes = image.read_bytes()
    with local.lock(), engine.writer():
        return replace_artwork(engine, doc, heading, image_bytes, prompt,
                               args.expected_block, args.expected_revision,
                               args.uploaded_block, args.image_token)


if __name__ == '__main__':
    try:
        print(json.dumps({'ok': True, 'data': main()}, ensure_ascii=False, indent=2))
    except (StudyError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
