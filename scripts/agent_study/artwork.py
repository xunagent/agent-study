"""Replace one inspected diagram block; preserve graph source and personal notes."""
from hashlib import sha256
import json

from .lark import RemoteError, block_id, node_text, xml_root
from .model import StudyError, code_block


def media_token(node):
    return node.get('token') or node.get('src')


def replace_artwork(engine, doc, heading, image_bytes, prompt,
                    expected_block, expected_revision, uploaded_block, image_token):
    fingerprint = sha256(image_bytes).hexdigest()
    if not prompt.strip():
        raise StudyError("A reusable generation prompt is required")
    if not (image_bytes.startswith(b'\x89PNG\r\n\x1a\n') or image_bytes.startswith(b'\xff\xd8\xff')):
        raise StudyError("Use a reviewed PNG or JPEG image")
    record = {"agent_study_artwork": 1, "sha256": fingerprint, "prompt": prompt}

    def inspect():
        section = engine.remote.section(doc, heading)
        root = xml_root(section['content'])
        records = []
        for pre in root.iter('pre'):
            try:
                value = json.loads(node_text(pre))
            except ValueError:
                continue
            if isinstance(value, dict) and value.get('agent_study_artwork') == 1:
                records.append(value)
        images = [n for n in root.iter('img') if media_token(n) == image_token]
        if record in records and len(images) == 1:
            return section, root, images[0]
        return section, root, None

    section, root, image = inspect()
    if image is None:
        targets = [n for n in root.iter() if block_id(n) == expected_block and n.tag in ('whiteboard', 'img')]
        if len(targets) != 1 or section.get('revision_id') != expected_revision:
            raise StudyError("Diagram changed since inspection; inspect again before replacing")
        uploaded = engine.remote.fetch(doc, scope='range', start_block_id=uploaded_block, end_block_id=uploaded_block)
        images = [n for n in xml_root(uploaded['content']).iter('img')
                  if block_id(n) == uploaded_block and media_token(n) == image_token]
        if len(images) != 1:
            raise StudyError('Uploaded image block is missing or does not match its token')
        # Upload succeeded before touching the original diagram. Move that exact block.
        try:
            engine.write(doc, '', command='block_move_after', block_id=section['heading_id'],
                         src_block_ids=uploaded_block, revision_id=expected_revision)
        except RemoteError:
            pass
        moved = engine.remote.section(doc, heading)
        if not any(block_id(n) == uploaded_block and media_token(n) == image_token
                   for n in xml_root(moved['content']).iter('img')):
            raise StudyError('Image move incomplete; preserve the old diagram and inspect before retrying')
        content = '<h2>图示生成提示词</h2>' + code_block(json.dumps(record, ensure_ascii=False, indent=2), 'json')
        try:
            engine.write(doc, content, command='block_replace', block_id=expected_block,
                         revision_id=moved['revision_id'])
        except RemoteError:
            pass  # Resolve a lost response from the scoped remote section, never blind retry.
        section, root, image = inspect()
    if image is None:
        raise StudyError("Image replacement incomplete; preserve remote blocks and inspect before retrying")
    engine.event('artwork', {"doc": doc, "heading": heading, "sha256": fingerprint,
                           "image_token": media_token(image)},
                 'artwork:' + sha256((doc + heading + fingerprint + prompt).encode()).hexdigest())
    return {"image_token": media_token(image), "image_block": block_id(image), "sha256": fingerprint}
