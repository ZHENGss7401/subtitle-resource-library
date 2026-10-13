"""Load explicitly approved subtitle variants without merging their shared series ID."""
import hashlib
import json
import shutil
from pathlib import Path
from PIL import Image

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def collect_registered_variants(semi, library, days, read_copy):
    entries = []
    library = Path(library)
    for day in days:
        folder = Path(semi) / day
        if not folder.is_dir():
            continue
        for registry in sorted(folder.glob('*/字幕夹/_字幕资源索引.json')):
            package = registry.parent.parent
            listing = json.loads(registry.read_text(encoding='utf-8-sig'))
            for variant in listing['variants']:
                record = json.loads((registry.parent / variant['record']).read_text(encoding='utf-8-sig'))
                if record.get('status') != 'PNG字幕已获用户明确生产定版' or not record.get('approval'):
                    raise ValueError('Variant has no explicit production approval')
                source = registry.parent / variant['subtitle']
                preview = registry.parent / variant['preview']
                if digest(source) != record['sha256'].lower() or digest(preview) != record['preview_sha256'].lower():
                    raise ValueError('Approved variant hash mismatch')
                series, name = listing['code'], variant['variant']
                code = f'{series}【{name}】'
                stem = f'{series}_{name}'
                layer_rel, preview_rel = f'定版/{stem}.png', f'定版/{stem}_预览.png'
                for src, rel in [(source, layer_rel), (preview, preview_rel)]:
                    target = library / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    assert digest(src) == digest(target)
                copy = read_copy(str(package))
                if copy:
                    copy['pkg'] = str(package)
                    if copy['source'].lower().endswith('.docx'):
                        rel = f'文案/{copy["source"]}'
                        (library/'文案').mkdir(exist_ok=True)
                        shutil.copy2(package/copy['source'], library/rel)
                        copy['download_rel'] = rel
                with Image.open(source) as im:
                    size = list(im.size)
                entries.append({'code':code, 'series_code':series, 'variant':name,
                    'pkg_code':series, 'aliases':[series], 'dates':[day],
                    'src_packages':[str(package)], 'src_file':str(source),
                    'definitive':str(library/layer_rel), 'definitive_abs':str(library/layer_rel),
                    'layer_rel':layer_rel, 'preview_rel':preview_rel,
                    'preview_abs':str(library/preview_rel), 'preview_kind':'用户定版预览',
                    'preview_from':str(preview), 'sha256':digest(source),
                    'preview_sha256':digest(preview), 'size':size,
                    'basis':'版本记录与用户明确PNG生产定版', 'confidence':'已证实',
                    'contested':False, 'discarded':[], 'copy':copy,
                    'source_count':variant['source_count'], 'flow_source':variant['flow_source']})
    return entries
