"""Portable detail-page workspace, two-route execution and archival helpers."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from PIL import Image

from typography import render as draw_layout
from typography import preflight as layout_preflight, inspection_overlay
from workflow_validation import validate_capabilities, validate_graph


FOLDERS = ['01-原始资料', '02-需求澄清', '03-设计方案', '04-一致性素材',
           '05-提示词与排版数据', '06-工作流与执行记录', '07-生成结果与检查', '08-最终交付']
SKILL_ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value, *, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if replace:
        temp = path.with_name(uuid4().hex[:12] + '.tmp')
        temp.write_bytes(encode(value))
        os.replace(temp, path)
    else:
        with path.open('xb') as stream:
            stream.write(encode(value))


def project_root(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Project root must be explicit and absolute; cwd is never inferred')
    path = path.resolve(strict=True)
    forbidden = [Path.home().resolve(), SKILL_ROOT]
    system = os.environ.get('SystemRoot')
    if path == Path(path.anchor) or not path.is_dir() or path in forbidden:
        raise ValueError('Drive root, home and Skill installation are not project roots')
    if path.is_relative_to(SKILL_ROOT) or (system and path.is_relative_to(Path(system).resolve())):
        raise ValueError('System and Skill directories cannot contain project output')
    return path


class Workspace:
    def __init__(self, task):
        self.task = Path(task).resolve(strict=True)
        self.meta = read(self.task / 'task.json')
        self.root = project_root(self.meta['project_root'])
        if self.task.parent != self.root or self.task.name != self.meta['directory']:
            raise ValueError('Task does not match its bound project root; rebind moved projects explicitly')

    def path(self, relative):
        path = Path(relative)
        if not isinstance(relative, str) or path.is_absolute() or PureWindowsPath(relative).drive or '..' in path.parts:
            raise ValueError('Expected a task-relative path without traversal')
        resolved = (self.task / path).resolve()
        if resolved == self.task or not resolved.is_relative_to(self.task):
            raise ValueError('Path escapes task directory (including symlinks)')
        if path.parts[0] not in FOLDERS:
            raise ValueError('Files must belong to a task category')
        return resolved

    def index(self, stage):
        self.meta.update(stage=stage, updated_at=now())
        save(self.task / 'task.json', self.meta, replace=True)
        lines = ['# 项目索引', '', f'项目根目录：{self.root}', f'当前阶段：{stage}', '', '## 已归档文件', '']
        for folder in FOLDERS:
            for file in sorted((self.task / folder).rglob('*')):
                if file.is_file() and file.resolve().is_relative_to(self.task):
                    rel = file.relative_to(self.task).as_posix()
                    lines.append(f'- [{rel}]({rel})')
        (self.task / '项目索引.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def archive(self, source, destination):
        target = self.path(destination)
        raw = Path(source).read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        entry = {'source': str(Path(source).resolve()), 'path': destination, 'sha256': sha(raw), 'at': now()}
        with self.path(FOLDERS[0] + '/归档记录.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self.index(self.meta['stage'])
        return entry


def initialize(root, name):
    root = project_root(root)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name).strip(' .')[:60] or '待命名商品'
    stem = '详情页-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + name
    task = root / stem
    suffix = 1
    while True:
        try:
            task.mkdir()
            break
        except FileExistsError:
            suffix += 1
            task = root / (stem + '-' + str(suffix))
    for folder in FOLDERS:
        (task / folder).mkdir()
    save(task / 'task.json', {'schema_version': 1, 'project_root': str(root), 'directory': task.name,
                              'created_at': now(), 'stage': '澄清中'})
    workspace = Workspace(task)
    workspace.index('澄清中')
    return task


def url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('Expected an HTTP(S) server origin without credentials or path')
    return value.rstrip('/')


class Comfy:
    def __init__(self, base):
        self.base = url(base)

    def raw(self, route, payload=None, *, content_type='application/json'):
        body = encode(payload) if isinstance(payload, dict) else payload
        req = Request(self.base + route, data=body, headers={'Content-Type': content_type})
        with urlopen(req, timeout=20) as response:
            return response.read()

    def get(self, route, payload=None):
        return json.loads(self.raw(route, payload))

    def probe(self):
        info = self.get('/object_info')
        if not isinstance(info, dict) or not info:
            raise ValueError('Server did not return node definitions')
        self.get('/queue')
        return info

    def upload(self, path):
        raw = path.read_bytes()
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        boundary = 'detail' + uuid4().hex
        filename = sha(raw) + path.suffix.lower()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + raw
        body += f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\nfalse\r\n--{boundary}--\r\n'.encode()
        result = json.loads(self.raw('/upload/image', body, content_type='multipart/form-data; boundary=' + boundary))
        name, sub = result.get('name', ''), result.get('subfolder', '')
        if (result.get('type') != 'input' or not name or '/' in name or '\\' in name
                or '\\' in sub or sub.startswith('/') or '..' in sub.split('/')):
            raise ValueError('Unsafe image upload response')
        uploaded = self.raw('/view?' + urlencode({'filename': name, 'subfolder': sub, 'type': 'input'}))
        if sha(uploaded) != sha(raw):
            raise ValueError('Uploaded reference bytes do not match local reference')
        return (sub + '/' if sub else '') + name


def configure(root, base):
    root = project_root(root)
    base = url(base)
    count = len(Comfy(base).probe())
    target = root / 'detail-page.connection.json'
    if target.resolve().parent != root:
        raise ValueError('Connection configuration escapes project root')
    save(target, {'base_url': base, 'verified_at': now(), 'node_count': count}, replace=True)
    return {'path': str(target), 'base_url': base, 'node_count': count}


def evidence(message):
    if not isinstance(message, str) or not message.strip():
        raise ValueError('Actual user confirmation text is required')
    return message


DEFAULT_INTAKE = FOLDERS[1] + '/intake.json'
REFERENCE_ROLES = {'product', 'person', 'prop', 'style', 'composition', 'background'}


def validate_intake(ws, path=DEFAULT_INTAKE):
    intake = read(ws.path(path))
    evidence(intake.get('scope'))
    evidence(intake.get('coverage_review'))
    if not isinstance(intake.get('items'), list) or not intake['items']:
        raise ValueError('Intake must list the decisions and their required information')
    identifiers = set()
    for item in intake['items']:
        for field in ('id', 'decision', 'required_information', 'answer', 'source'):
            evidence(item.get(field))
        if item['id'] in identifiers:
            raise ValueError('Duplicate intake item ID')
        identifiers.add(item['id'])
        if item.get('status') not in ('resolved', 'not_applicable', 'omitted_confirmed'):
            raise ValueError('Unresolved intake item: ' + item['id'])
        if item['status'] == 'omitted_confirmed':
            evidence(item.get('user_confirmation'))
    return intake


def plan_confirmation_path(ws, plan_hash, intake_hash):
    return ws.path(FOLDERS[2] + '/确认-' + sha((plan_hash + intake_hash).encode())[:32] + '.json')


def approve_plan(ws, plan, message, intake=DEFAULT_INTAKE):
    validate_intake(ws, intake)
    intake_hash = sha(ws.path(intake).read_bytes())
    raw = ws.path(plan).read_bytes()
    approval = {'plan': plan, 'sha256': sha(raw), 'intake': intake, 'intake_sha256': intake_hash,
                'user_confirmation': evidence(message), 'at': now()}
    save(plan_confirmation_path(ws, sha(raw), intake_hash), approval)
    ws.index('方案已确认，待提示词确认')
    return approval


def snapshot(ws, batch_path):
    batch = read(ws.path(batch_path))
    if batch['route'] not in ('agent', 'comfyui'):
        raise ValueError('Select agent or comfyui explicitly')
    for key in ('max_attempts', 'candidates_per_job'):
        if type(batch[key]) is not int or batch[key] < 1:
            raise ValueError(key + ' must be a positive integer')
    intake_path = batch.get('intake', DEFAULT_INTAKE)
    validate_intake(ws, intake_path)
    paths = {batch_path, batch['plan'], intake_path}
    ids = set()
    samples = []
    for job in batch['jobs']:
        ident = job['id']
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', ident) or ident in ids:
            raise ValueError('Job IDs must be unique safe identifiers')
        ids.add(ident)
        if job['kind'] not in ('asset', 'sample', 'page'):
            raise ValueError('Unknown job kind')
        if job['kind'] == 'sample':
            samples.append(ident)
        if any(type(job[k]) is not int or job[k] <= 0 for k in ('width', 'height')):
            raise ValueError('Expected positive integer dimensions')
        paths.add(job['prompt'])
        if not ws.path(job['prompt']).read_text(encoding='utf-8').strip():
            raise ValueError('Empty image prompt')
        if job['kind'] != 'asset':
            paths.add(job['layout'])
            layout = read(ws.path(job['layout']))
            if layout['canvas'] != [job['width'], job['height']]:
                raise ValueError('Layout and job dimensions disagree')
            for block in layout['text_blocks']:
                paths.add(block['font'])
            layout_preflight(layout, ws.path)
        has_product = False
        for ref in job.get('references', []):
            if ('path' in ref) == ('from_job' in ref):
                raise ValueError('References need exactly one path or from_job')
            if ref.get('role') not in REFERENCE_ROLES:
                raise ValueError('Each reference needs an explicit product/person/prop/style/composition/background role')
            evidence(ref.get('target'))
            if type(ref.get('priority')) is not int or ref['priority'] < 0:
                raise ValueError('Reference priority must be a nonnegative integer (higher first)')
            for field in ('preserve', 'allow', 'exclude'):
                if not isinstance(ref.get(field), list) or any(not isinstance(text, str) or not text.strip() for text in ref[field]):
                    raise ValueError('Reference ' + field + ' must be a list of explicit constraints')
            if ref['role'] in ('product', 'person', 'prop') and not ref['preserve']:
                raise ValueError('Identity references must specify the features to preserve')
            has_product |= ref['role'] == 'product'
            if 'path' in ref:
                paths.add(ref['path'])
                with Image.open(ws.path(ref['path'])) as image:
                    image.verify()
        if job['kind'] != 'asset' and not has_product:
            evidence(job.get('product_absence_reason'))
            if not read(ws.path(job['layout'])).get('no_product_reason'):
                raise ValueError('A page without a product reference needs an explicit no-product layout reason')
    if not batch['jobs'] or len(samples) != 1:
        raise ValueError('A batch requires exactly one sample job')
    jobs = {job['id']: job for job in batch['jobs']}
    for job in batch['jobs']:
        for ref in job.get('references', []):
            if 'from_job' in ref and (ref['from_job'] not in jobs or jobs[ref['from_job']]['kind'] != 'asset'):
                raise ValueError('Generated references must identify an asset job in this batch')
    def visit(ident, stack):
        if ident in stack:
            raise ValueError('Circular asset dependency')
        for ref in jobs[ident].get('references', []):
            if 'from_job' in ref:
                visit(ref['from_job'], stack | {ident})
    for ident in jobs:
        visit(ident, set())
    if batch['route'] == 'comfyui':
        for job in batch['jobs']:
            config_path = job.get('workflow_config', batch.get('workflow_config'))
            if not config_path:
                raise ValueError('ComfyUI jobs need a workflow configuration')
            paths.add(config_path)
            config = read(ws.path(config_path))
            paths.add(config['workflow'])
    hashes = {path: sha(ws.path(path).read_bytes()) for path in sorted(paths)}
    plan_sha = hashes[batch['plan']]
    plan_record = read(plan_confirmation_path(ws, plan_sha, hashes[intake_path]))
    if (plan_record['plan'] != batch['plan'] or plan_record['sha256'] != plan_sha
            or plan_record.get('intake_sha256') != hashes[intake_path]):
        raise ValueError('Plan has not been confirmed in its current version')
    return batch, hashes, sha(encode(hashes))


def batch_folder(ws, digest):
    return ws.path(FOLDERS[5] + '/batch-' + digest[:24])


def approve_batch(ws, path, message):
    batch, hashes, digest = snapshot(ws, path)
    folder = batch_folder(ws, digest)
    folder.mkdir(parents=True, exist_ok=True)
    save(folder / 'approval.json', {'batch': path, 'route': batch['route'], 'files': hashes,
                                   'user_confirmation': evidence(message), 'at': now()})
    ws.index('提示词与执行设置已确认，待素材及样张制作')
    return {'batch_id': digest, 'route': batch['route']}


def approved(ws, path):
    batch, hashes, digest = snapshot(ws, path)
    folder = batch_folder(ws, digest)
    approval = read(folder / 'approval.json')
    if hashes != approval['files'] or approval['route'] != batch['route']:
        raise ValueError('Inputs changed; confirm the updated batch before execution')
    return batch, folder, digest


def image_info(raw, expected):
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        if image.size != tuple(expected):
            raise ValueError('Image dimensions differ from approved dimensions')
        if image.format not in ('PNG', 'JPEG', 'WEBP'):
            raise ValueError('Unsupported output image format')
        return {'size': list(image.size), 'sha256': sha(raw),
                'suffix': {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[image.format]}


def reviewed_reference(ws, folder, ident):
    record = read(folder / ('review-' + ident + '.json'))
    if record.get('superseded'):
        raise ValueError('Review is superseded; inspect and accept the updated version')
    path = ws.path(record['image'])
    if record['sha256'] != sha(path.read_bytes()):
        raise ValueError('Reviewed image has changed')
    for dependency, digest in record.get('render_dependencies', {}).items():
        if sha(ws.path(dependency).read_bytes()) != digest:
            raise ValueError('Accepted typography inputs have changed')
    for dependency, expected in record.get('dependency_jobs', {}).items():
        current = reviewed_reference(ws, folder, dependency)
        if current.relative_to(ws.task).as_posix() != expected['path'] or sha(current.read_bytes()) != expected['sha256']:
            raise ValueError('A reviewed dependency has changed; remake and review downstream pages')
    return path


def effective_prompt(ws, job):
    prompt = ws.path(job['prompt']).read_text(encoding='utf-8')
    constraints = []
    for index, ref in enumerate(job.get('references', []), 1):
        constraints.append({'image': index, **{key: ref[key] for key in
                            ('role', 'target', 'preserve', 'allow', 'exclude', 'priority')}})
    if constraints:
        prompt += '\n\nREFERENCE ROLES (in actual upload order; product identity always takes precedence over style):\n'
        prompt += json.dumps(constraints, ensure_ascii=False, indent=2)
    return prompt


def prepare_graph(ws, batch, job, info, refs, prefix, *, pending_references=False):
    config = read(ws.path(job.get('workflow_config', batch.get('workflow_config'))))
    graph = read(ws.path(config['workflow']))
    if not isinstance(graph, dict) or not graph or 'nodes' in graph:
        raise ValueError('Use an API-format workflow, not an editor workflow')
    validate_capabilities(config, job, batch['candidates_per_job'], len(refs))
    for node in graph.values():
        if node['class_type'] not in info:
            raise ValueError('Missing remote node: ' + node['class_type'])
    values = {'prompt': effective_prompt(ws, job), 'width': job['width'],
              'height': job['height'], 'seed': job.get('seed', 0), 'prefix': prefix,
              'negative_prompt': job.get('negative_prompt', ''), 'candidates': batch['candidates_per_job']}
    mapping = config['mapping']
    required = {'prompt', 'prefix'} | {'reference_' + str(i) for i in range(len(refs))}
    if not required.issubset(mapping):
        raise ValueError('Workflow lacks prompt/output-prefix/reference bindings')
    fixed = config.get('fixed', {})
    controlled = {'width', 'height', 'candidates'} | ({'seed', 'negative_prompt'} & job.keys())
    if not controlled.issubset(mapping.keys() | fixed.keys()) or mapping.keys() & fixed.keys():
        raise ValueError('Dimensions/count/explicit seed or negative prompt need dynamic or fixed workflow bindings')
    targets = [(binding['node'], binding['input']) for binding in [*mapping.values(), *fixed.values()]]
    if len(set(targets)) != len(targets):
        raise ValueError('Different workflow parameters cannot share a binding target')
    values.update({'reference_' + str(i): value for i, value in enumerate(refs)})
    for key, binding in mapping.items():
        node = graph[binding['node']]
        declared = info[node['class_type']].get('input', {})
        inputs = {**declared.get('required', {}), **declared.get('optional', {})}
        if (key not in values or node['class_type'] != binding['class_type']
                or binding['input'] not in node['inputs'] or binding['input'] not in inputs):
            raise ValueError('Invalid workflow binding: ' + key)
        node['inputs'][binding['input']] = values[key]
    for key, binding in fixed.items():
        node = graph[binding['node']]
        if (key not in values or node['class_type'] != binding['class_type']
                or node['inputs'].get(binding['input']) != values[key]):
            raise ValueError('Fixed workflow parameter differs from approved task: ' + key)
    bound_images = {binding['node'] for key, binding in mapping.items() if key.startswith('reference_')}
    actual_images = {key for key, node in graph.items() if node['class_type'].startswith('LoadImage')}
    if actual_images != bound_images:
        raise ValueError('Every image loader must bind an approved reference')
    validation_info = deepcopy(info)
    if pending_references:
        for key, binding in mapping.items():
            if key.startswith('reference_'):
                inputs = validation_info[binding['class_type']].get('input', {})
                for category in ('required', 'optional'):
                    declaration = inputs.get(category, {}).get(binding['input'])
                    if declaration and isinstance(declaration[0], list):
                        # File widgets enumerate current server files; no upload exists at preflight.
                        inputs[category][binding['input']] = ['STRING', {}]
    participating = {binding['node'] for binding in [*mapping.values(), *fixed.values()]}
    validate_graph(graph, validation_info, config['output_node'], participating - {config['output_node']})
    return graph, config['output_node']


def preflight_batch(ws, path, *, client=None):
    batch, _, _ = snapshot(ws, path)
    layouts = {job['id']: layout_preflight(read(ws.path(job['layout'])), ws.path)
               for job in batch['jobs'] if job['kind'] != 'asset'}
    if batch['route'] == 'comfyui':
        client = client or Comfy(read(ws.root / 'detail-page.connection.json')['base_url'])
        info = client.probe()
        for job in batch['jobs']:
            prepare_graph(ws, batch, job, info, ['pending_reference'] * len(job.get('references', [])), 'preflight', pending_references=True)
    return {'status': 'preflight_passed', 'route': batch['route'], 'layouts': layouts,
            'semantic_image_quality_verified': False, 'effective_prompts': {
                job['id']: effective_prompt(ws, job) for job in batch['jobs']}}


def generation_file_hashes(ws, batch, job, refs):
    paths = {batch['plan'], batch.get('intake', DEFAULT_INTAKE), job['prompt']}
    paths.update(path.relative_to(ws.task).as_posix() for path in refs)
    if batch['route'] == 'comfyui':
        config = job.get('workflow_config', batch.get('workflow_config'))
        paths.add(config)
        paths.add(read(ws.path(config))['workflow'])
    return {path: sha(ws.path(path).read_bytes()) for path in sorted(paths)}


def execute(ws, batch_path, ident, *, client=None, repair_note=None):
    batch, folder, digest = approved(ws, batch_path)
    job = next(job for job in batch['jobs'] if job['id'] == ident)
    refs = [ws.path(ref['path']) if 'path' in ref else reviewed_reference(ws, folder, ref['from_job'])
            for ref in job.get('references', [])]
    sample_dependency = {}
    if job['kind'] == 'page':
        sample = next(item['id'] for item in batch['jobs'] if item['kind'] == 'sample')
        sample_image = reviewed_reference(ws, folder, sample)
        sample_dependency[sample] = {'path': sample_image.relative_to(ws.task).as_posix(),
                                     'sha256': sha(sample_image.read_bytes())}
    info = None
    if batch['route'] == 'comfyui':
        base = read(ws.root / 'detail-page.connection.json')['base_url']
        client = client or Comfy(base)
        info = client.probe()
        prepare_graph(ws, batch, job, info, ['pending'] * len(refs), 'preflight', pending_references=True)
    runs = folder / ident
    existing = sorted(runs.glob('attempt-*/execution.json')) if runs.exists() else []
    all_job_runs = ws.path(FOLDERS[5]).glob('batch-*/' + ident + '/attempt-*/execution.json')
    for file in all_job_runs:
        state = read(file)
        if state['status'] in ('preparing', 'submitting', 'submitted', 'submission_uncertain', 'remote_pending', 'awaiting_agent'):
            raise ValueError('An unresolved run exists; resume or resolve it before another attempt')
    if len(existing) >= batch['max_attempts']:
        raise ValueError('Approved attempt limit reached')
    if existing and read(existing[-1])['status'] == 'generated_pending_review':
        evidence(repair_note)
    run = runs / ('attempt-' + str(len(existing) + 1).zfill(3))
    run.mkdir(parents=True, exist_ok=False)
    record = {'status': 'preparing', 'route': batch['route'], 'batch_id': digest, 'job': job,
              'generation_files': generation_file_hashes(ws, batch, job, refs),
              'effective_prompt': effective_prompt(ws, job),
              'repair_note': repair_note,
              'reference_files': {str(path.relative_to(ws.task).as_posix()): sha(path.read_bytes()) for path in refs},
              'dependency_jobs': {**sample_dependency, **{
                  ref['from_job']: {'path': path.relative_to(ws.task).as_posix(), 'sha256': sha(path.read_bytes())}
                  for ref, path in zip(job.get('references', []), refs) if 'from_job' in ref}},
              'candidates': batch['candidates_per_job'], 'started_at': now(), 'prompt_id': None}
    save(run / 'execution.json', record)
    try:
        if batch['route'] == 'agent':
            record['status'] = 'awaiting_agent'
            record['instruction'] = 'Invoke the actual built-in image tool with the approved prompt and references; import its real output files.'
        else:
            uploaded = [client.upload(path) for path in refs]
            if refs:
                info = client.probe()
            graph, output_node = prepare_graph(ws, batch, job, info, uploaded, 'detail_' + uuid4().hex)
            save(run / 'submitted_workflow.json', graph)
            record.update(base_url=base, output_node=output_node, status='submitting')
            save(run / 'execution.json', record, replace=True)
            submission = client.get('/prompt', {'prompt': graph, 'client_id': uuid4().hex})
            save(run / 'submission.json', submission)
            if submission.get('error') or submission.get('node_errors') or not submission.get('prompt_id'):
                record['status'] = 'rejected'
                raise ValueError('Remote server rejected workflow')
            record.update(prompt_id=submission['prompt_id'], status='submitted')
    except Exception as exc:
        record['status'] = 'submission_uncertain' if record['status'] == 'submitting' else (
            record['status'] if record['status'] == 'rejected' else 'failed')
        record['error'] = str(exc)
        raise
    finally:
        save(run / 'execution.json', record, replace=True)
        ws.index('制作中，生成结果待检查')
    return run


def run_path(ws, value):
    path = ws.path(value)
    if not path.is_relative_to(ws.path(FOLDERS[5])):
        raise ValueError('Run must be in the execution archive')
    return path


def store_images(ws, run, record, raws):
    if len(raws) != record['candidates']:
        raise ValueError('Output candidate count differs from the approved count')
    expected = [record['job']['width'], record['job']['height']]
    infos = [image_info(raw, expected) for raw in raws]
    relative = FOLDERS[6] + '/' + record['batch_id'][:24] + '/' + record['job']['id'] + '/' + run.name
    out = ws.path(relative)
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for index, (raw, meta) in enumerate(zip(raws, infos), 1):
        name = 'candidate-' + str(index).zfill(3) + meta['suffix']
        (out / name).write_bytes(raw)
        results.append({**meta, 'path': relative + '/' + name})
    record.update(status='generated_pending_review', images=results, generated_at=now())
    save(run / 'execution.json', record, replace=True)
    ws.index('已生成，待排版或视觉检查')
    return results


def import_agent(ws, relative_run, images, tool, call_id):
    run = run_path(ws, relative_run)
    record = read(run / 'execution.json')
    if record['route'] != 'agent' or record['status'] != 'awaiting_agent':
        raise ValueError('Run is not awaiting built-in agent output')
    evidence(tool)
    evidence(call_id)
    record['agent_tool'] = tool
    record['tool_call_id'] = call_id
    return store_images(ws, run, record, [Path(path).read_bytes() for path in images])


def resume(ws, relative_run, *, client=None):
    run = run_path(ws, relative_run)
    record = read(run / 'execution.json')
    if record['route'] != 'comfyui' or not record['prompt_id'] or record['status'] not in ('submitted', 'remote_pending'):
        raise ValueError('No known remote task to resume; uncertain submissions must not be resubmitted')
    client = client or Comfy(record['base_url'])
    pid = record['prompt_id']
    history = client.get('/history/' + pid)
    item = history.get(pid)
    if not item:
        record['status'] = 'remote_pending'
        save(run / 'execution.json', record, replace=True)
        return {'status': 'remote_pending', 'prompt_id': pid}
    status = item.get('status', {})
    if status.get('status_str') == 'error' or any(message[0] in ('execution_error', 'execution_interrupted') for message in status.get('messages', [])):
        record.update(status='failed', remote_error=status)
        save(run / 'execution.json', record, replace=True)
        raise ValueError('Remote generation failed')
    if not status.get('completed') or status.get('status_str') != 'success':
        return {'status': 'remote_pending', 'prompt_id': pid}
    submitted = read(run / 'submitted_workflow.json')
    prompt = item.get('prompt', [])
    if len(prompt) < 3 or prompt[2] != submitted:
        raise ValueError('Remote history does not match submitted workflow')
    images = item.get('outputs', {}).get(record['output_node'], {}).get('images', [])
    if not images or any(image.get('type') != 'output' for image in images):
        raise ValueError('Expected actual output images, not temporary or input files')
    raws = [client.raw('/view?' + urlencode({key: image.get(key, '') for key in ('filename', 'subfolder', 'type')})) for image in images]
    save(run / 'history.json', item)
    return store_images(ws, run, record, raws)


def candidate_image(ws, relative_run, candidate):
    run = run_path(ws, relative_run)
    record = read(run / 'execution.json')
    if record['status'] != 'generated_pending_review' or not 1 <= candidate <= len(record.get('images', [])):
        raise ValueError('Candidate index is out of range')
    image = record['images'][candidate - 1]
    base = ws.path(image['path'])
    if sha(base.read_bytes()) != image['sha256']:
        raise ValueError('Generated source image has changed')
    return run, record, image, base


def supersede_review(ws, run, record, candidate, reason):
    selected_path = run.parent.parent / ('review-' + record['job']['id'] + '.json')
    if selected_path.exists():
        selected = read(selected_path)
        if (selected.get('run') == run.relative_to(ws.task).as_posix()
                and selected.get('candidate') == candidate):
            selected['superseded'] = {'reason': reason, 'at': now()}
            save(selected_path, selected, replace=True)


def generation_unchanged(ws, run, record):
    if not record.get('generation_files'):
        raise ValueError('Legacy run has no separate generation provenance; do not silently reuse it')
    for path, digest in record['generation_files'].items():
        if sha(ws.path(path).read_bytes()) != digest:
            raise ValueError('Generation input changed: ' + path)
    for dependency, expected in record.get('dependency_jobs', {}).items():
        current = reviewed_reference(ws, run.parent.parent, dependency)
        if current.relative_to(ws.task).as_posix() != expected['path'] or sha(current.read_bytes()) != expected['sha256']:
            raise ValueError('Reference selection changed; remake the affected image')


def inspection_preview(ws, relative_run, candidate):
    run, record, image, base = candidate_image(ws, relative_run, candidate)
    if record['job']['kind'] == 'asset':
        raise ValueError('Asset identity is reviewed directly; page layout overlay is for pages')
    layout = read(ws.path(record['job']['layout']))
    digest = sha(encode(layout))[:12]
    output = base.with_name(base.stem + '-inspect-' + digest + '.png')
    report = inspection_overlay(base, layout, output, ws.path)
    return {'image': output.relative_to(ws.task).as_posix(), **report}


def inspect_image(ws, relative_run, candidate, inspection):
    run, record, image, base = candidate_image(ws, relative_run, candidate)
    if record['job']['kind'] == 'asset':
        raise ValueError('Use identity review for assets; no page typography is applied')
    generation_unchanged(ws, run, record)
    if inspection.get('image_sha256') != image['sha256']:
        raise ValueError('Inspection must identify the actual generated image hash')
    evidence(inspection.get('observations'))
    required = ('composition', 'lighting', 'reference_fidelity', 'no_extra_objects')
    if any(inspection.get('checks', {}).get(key) is not True for key in required):
        raise ValueError('Base image inspection failed; record a reject report and repair first')
    layout = read(ws.path(record['job']['layout']))
    actual = inspection.get('actual_protected_regions')
    if not isinstance(actual, list):
        raise ValueError('Actual product regions must be recorded after viewing the image')
    if any(ref['role'] == 'product' for ref in record['job'].get('references', [])) and not actual:
        raise ValueError('Product reference pages must locate the actual product before typography')
    layout['protected_regions'] = actual
    # Record the actual product geometry first; typography may need a new layout to avoid it.
    region_layout = {**layout, 'text_blocks': []}
    layout_preflight(region_layout, ws.path)
    try:
        layout_preflight(layout, ws.path)
        layout_conflict = None
    except ValueError as exc:
        layout_conflict = str(exc)
    report = {**inspection, 'status': 'visually_inspected', 'at': now(), 'automatic_detection': False}
    report['planned_layout_conflict'] = layout_conflict
    path = run / ('inspection-' + str(candidate) + '-' + sha(encode(report))[:12] + '.json')
    save(path, report)
    image['inspection'] = {'path': path.relative_to(ws.task).as_posix(), 'sha256': sha(path.read_bytes())}
    save(run / 'execution.json', record, replace=True)
    supersede_review(ws, run, record, candidate, 'Base image inspection updated; rerender and review again')
    ws.index('底图已看图检查，待真实字体排版')
    return report


def layout_files(ws, relative):
    layout = read(ws.path(relative))
    layout_preflight(layout, ws.path)
    paths = {relative} | {block['font'] for block in layout['text_blocks']}
    return layout, {path: sha(ws.path(path).read_bytes()) for path in sorted(paths)}


def layout_revision(image, files):
    return sha(encode({'base_sha256': image['sha256'], 'files': files}))[:24]


def approve_layout(ws, relative_run, candidate, layout_path, message):
    run, record, image, _ = candidate_image(ws, relative_run, candidate)
    if record['job']['kind'] == 'asset':
        raise ValueError('Only page typography has layout revisions')
    generation_unchanged(ws, run, record)
    layout, files = layout_files(ws, layout_path)
    if layout['canvas'] != [record['job']['width'], record['job']['height']]:
        raise ValueError('A typography-only revision cannot resize the base image')
    revision = layout_revision(image, files)
    approval = {'layout': layout_path, 'files': files, 'base_sha256': image['sha256'],
                'revision': revision, 'user_confirmation': evidence(message), 'at': now()}
    save(run / ('layout-' + revision + '.json'), approval)
    image['pending_layout_revision'] = revision
    image['active_layout_revision'] = revision
    save(run / 'execution.json', record, replace=True)
    supersede_review(ws, run, record, candidate, 'New layout approved; rerender and review again')
    return approval


def render_page(ws, relative_run, candidate, layout_path=None):
    run, record, image, base = candidate_image(ws, relative_run, candidate)
    if record['job']['kind'] == 'asset':
        raise ValueError('Run is not a generated page awaiting typography')
    generation_unchanged(ws, run, record)
    folder = run.parent.parent
    chosen = layout_path or record['job']['layout']
    layout, files = layout_files(ws, chosen)
    revision = layout_revision(image, files)
    if image.get('active_layout_revision') and revision != image['active_layout_revision']:
        raise ValueError('Render the newly confirmed layout revision before acceptance')
    if layout_path:
        confirmation = read(run / ('layout-' + revision + '.json'))
        if confirmation['files'] != files or confirmation['base_sha256'] != image['sha256']:
            raise ValueError('Layout revision has not been confirmed')
    else:
        hashes = read(folder / 'approval.json')['files']
        if any(hashes.get(path) != digest for path, digest in files.items()):
            raise ValueError('Use approve-layout and rerender for typography-only changes')
    inspected = image.get('inspection')
    if not inspected or sha(ws.path(inspected['path']).read_bytes()) != inspected['sha256']:
        raise ValueError('View and inspect the actual base image before typography')
    report = read(ws.path(inspected['path']))
    if report['image_sha256'] != image['sha256']:
        raise ValueError('Inspection belongs to a different base image')
    # The original planned boxes are not proof of where the generated product is.
    layout['protected_regions'] = report['actual_protected_regions']
    layout_preflight(layout, ws.path)
    render_id = sha((revision + inspected['sha256']).encode())[:24]
    output = base.with_name(base.stem + '-type-' + render_id[:12] + '.png')
    rendered = draw_layout(base, layout, output, ws.path)
    image.update(typeset_path=output.relative_to(ws.task).as_posix(), typeset_sha256=sha(output.read_bytes()),
                 layout_revision=revision, render_id=render_id, render_inspection=inspected,
                 render_dependencies={**files, inspected['path']: inspected['sha256']})
    image.pop('pending_layout_revision', None)
    if image.get('rejected'):
        rejections = image.get('rejections', [image['rejected']])
        remaining = [path for path in rejections
                     if any(issue['repair'] != 'retypeset' for issue in read(ws.path(path))['issues'])]
        if remaining:
            image.update(rejections=remaining, rejected=remaining[-1])
        else:
            image.pop('rejected')
            image.pop('rejections', None)
    save(run / ('typography-' + str(candidate) + '-' + render_id + '.json'), rendered)
    save(run / 'execution.json', record, replace=True)
    ws.index('排版完成，待视觉验收')
    return {'image': image, 'report': rendered}


def reject_image(ws, relative_run, candidate, report):
    run, record, image, _ = candidate_image(ws, relative_run, candidate)
    if not isinstance(report.get('issues'), list) or not report['issues']:
        raise ValueError('Rejection needs concrete issues and repair actions')
    for issue in report['issues']:
        for field in ('category', 'expected', 'actual', 'region', 'correction'):
            evidence(issue.get(field))
        if issue.get('repair') not in ('retypeset', 'local_edit', 'regenerate', 'clarify'):
            raise ValueError('Unknown repair action')
        if issue.get('severity') not in ('blocking', 'minor'):
            raise ValueError('Unknown issue severity')
    path = run / ('reject-' + str(candidate) + '-' + uuid4().hex[:12] + '.json')
    save(path, {**report, 'image_sha256': image['sha256'], 'at': now()})
    rejections = list(image.get('rejections', [image['rejected']] if image.get('rejected') else []))
    image['rejected'] = path.relative_to(ws.task).as_posix()
    image['rejections'] = rejections + [image['rejected']]
    save(run / 'execution.json', record, replace=True)
    supersede_review(ws, run, record, candidate, 'Visual rejection: ' + image['rejected'])
    ws.index('视觉退回，按问题记录定向修正')
    return {'status': 'rejected', 'report': image['rejected']}


def review(ws, relative_run, candidate, message, checks):
    run, record, image, _ = candidate_image(ws, relative_run, candidate)
    generation_unchanged(ws, run, record)
    for path, digest in image.get('render_dependencies', {}).items():
        if sha(ws.path(path).read_bytes()) != digest:
            raise ValueError('Rendered layout or font changed')
    if image.get('rejected'):
        raise ValueError('Candidate has unresolved visual rejection')
    if image.get('pending_layout_revision'):
        raise ValueError('Newly confirmed layout has not been rendered')
    if (record['job']['kind'] != 'asset'
            and (not image.get('render_inspection') or image['render_inspection'] != image.get('inspection'))):
        raise ValueError('Render must use the current actual image inspection before acceptance')
    evidence(checks.get('observations'))
    folder = run.parent.parent
    required = {'identity', 'consistency'} if record['job']['kind'] == 'asset' else {'identity', 'consistency', 'text', 'layout'}
    if not required.issubset(checks) or any(checks[key] is not True for key in required):
        raise ValueError('All required visual review checks must pass')
    key = 'path' if record['job']['kind'] == 'asset' else 'typeset_path'
    if key not in image:
        raise ValueError('Page must be typeset before visual acceptance')
    hash_key = 'sha256' if key == 'path' else 'typeset_sha256'
    source = ws.path(image[key])
    if sha(source.read_bytes()) != image[hash_key]:
        raise ValueError('Reviewed image bytes have changed')
    for dependency, expected in record.get('dependency_jobs', {}).items():
        current = reviewed_reference(ws, folder, dependency)
        if current.relative_to(ws.task).as_posix() != expected['path'] or sha(current.read_bytes()) != expected['sha256']:
            raise ValueError('Reference selection changed after generation; remake the affected page')
    approval = {'image': image[key], 'sha256': image[hash_key], 'run': run.relative_to(ws.task).as_posix(), 'candidate': candidate,
                'render_dependencies': image.get('render_dependencies', {}),
                'dependency_jobs': record.get('dependency_jobs', {}),
                'checks': checks, 'user_confirmation': evidence(message), 'at': now()}
    if record['job']['kind'] != 'asset':
        out = ws.path(FOLDERS[7] + '/' + record['batch_id'][:24] + '/' + record['job']['id'] + '/' + run.name + '-' + image.get('render_id', 'original')[:12] + '.png')
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('xb') as stream:
            stream.write(source.read_bytes())
        approval['delivery'] = out.relative_to(ws.task).as_posix()
        save(out.with_suffix('.review.json'), approval)
    save(folder / ('review-' + record['job']['id'] + '.json'), approval, replace=True)
    ws.index('已验收部分素材或页面；按批次清单核对剩余交付')
    return approval


def batch_status(ws, batch_path):
    batch, folder, digest = approved(ws, batch_path)
    jobs = []
    for job in batch['jobs']:
        try:
            reviewed_reference(ws, folder, job['id'])
            entry = read(folder / ('review-' + job['id'] + '.json'))
            if job['kind'] != 'asset':
                delivery = ws.path(entry['delivery'])
                if sha(delivery.read_bytes()) != entry['sha256']:
                    raise ValueError('Delivered file differs from accepted image')
            jobs.append({'id': job['id'], 'status': 'accepted', 'delivery': entry.get('delivery'), 'image': entry['image']})
        except (OSError, KeyError, ValueError) as exc:
            jobs.append({'id': job['id'], 'status': 'not_accepted_or_stale', 'reason': str(exc)})
    complete = all(job['status'] == 'accepted' for job in jobs)
    result = {'batch_id': digest, 'complete': complete, 'jobs': jobs, 'checked_at': now()}
    save(folder / 'status.json', result, replace=True)
    ws.index('当前批次全部已验收归档' if complete else '当前批次仍有待制作、验收或失效内容')
    return result


def agent_failure(ws, relative_run, tool, call_id, message):
    run = run_path(ws, relative_run)
    record = read(run / 'execution.json')
    if record['route'] != 'agent' or record['status'] != 'awaiting_agent':
        raise ValueError('Only a pending built-in image call can be resolved here')
    record.update(status='failed', agent_tool=evidence(tool), tool_call_id=evidence(call_id), error=evidence(message))
    save(run / 'execution.json', record, replace=True)
    ws.index('内置生图失败；按已确认上限决定是否重试')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--project-root', required=True); init.add_argument('--name', required=True)
    conn = sub.add_parser('connection'); conn.add_argument('--project-root', required=True); conn.add_argument('--url', required=True)
    for name in ('archive', 'approve-plan', 'approve-batch', 'preflight', 'run', 'status', 'resume', 'import-agent',
                 'agent-failure', 'inspection-preview', 'inspect-image', 'reject', 'approve-layout', 'render', 'rerender', 'review'):
        item = sub.add_parser(name); item.add_argument('--task', required=True)
        if name == 'archive':
            item.add_argument('--source', required=True); item.add_argument('--destination', required=True)
        if name in ('approve-plan', 'approve-batch', 'approve-layout'):
            item.add_argument('--file', required=True); item.add_argument('--message', required=True)
        if name == 'approve-plan': item.add_argument('--intake', default=DEFAULT_INTAKE)
        if name in ('run', 'status', 'preflight'): item.add_argument('--batch', required=True)
        if name == 'run': item.add_argument('--job', required=True)
        if name == 'run': item.add_argument('--repair-note')
        if name in ('resume', 'import-agent', 'agent-failure', 'inspection-preview', 'inspect-image', 'reject',
                    'approve-layout', 'render', 'rerender', 'review'):
            item.add_argument('--run', required=True)
        if name in ('import-agent', 'agent-failure'):
            item.add_argument('--tool', required=True); item.add_argument('--call-id', required=True)
        if name == 'import-agent': item.add_argument('--images', nargs='+', required=True)
        if name == 'agent-failure': item.add_argument('--message', required=True)
        if name in ('render', 'rerender', 'review', 'inspection-preview', 'inspect-image', 'reject', 'approve-layout'):
            item.add_argument('--candidate', type=int, required=True)
        if name in ('inspect-image', 'reject'): item.add_argument('--file', required=True)
        if name == 'rerender': item.add_argument('--layout', required=True)
        if name == 'review':
            item.add_argument('--message', required=True); item.add_argument('--checks', required=True, help='Task-relative JSON file with boolean review results')
    args = parser.parse_args()
    if args.command == 'init':
        result = str(initialize(args.project_root, args.name))
    elif args.command == 'connection':
        result = configure(args.project_root, args.url)
    else:
        ws = Workspace(args.task)
        if args.command == 'archive': result = ws.archive(args.source, args.destination)
        elif args.command == 'approve-plan': result = approve_plan(ws, args.file, args.message, args.intake)
        elif args.command == 'approve-batch': result = approve_batch(ws, args.file, args.message)
        elif args.command == 'preflight': result = preflight_batch(ws, args.batch)
        elif args.command == 'run': result = str(execute(ws, args.batch, args.job, repair_note=args.repair_note))
        elif args.command == 'status': result = batch_status(ws, args.batch)
        elif args.command == 'resume': result = resume(ws, args.run)
        elif args.command == 'import-agent': result = import_agent(ws, args.run, args.images, args.tool, args.call_id)
        elif args.command == 'agent-failure': result = agent_failure(ws, args.run, args.tool, args.call_id, args.message)
        elif args.command == 'render': result = render_page(ws, args.run, args.candidate)
        elif args.command == 'rerender': result = render_page(ws, args.run, args.candidate, args.layout)
        elif args.command == 'approve-layout': result = approve_layout(ws, args.run, args.candidate, args.file, args.message)
        elif args.command == 'inspection-preview': result = inspection_preview(ws, args.run, args.candidate)
        elif args.command == 'inspect-image': result = inspect_image(ws, args.run, args.candidate, read(ws.path(args.file)))
        elif args.command == 'reject': result = reject_image(ws, args.run, args.candidate, read(ws.path(args.file)))
        elif args.command == 'review': result = review(ws, args.run, args.candidate, args.message, read(ws.path(args.checks)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(json.dumps({'status': 'stopped', 'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
