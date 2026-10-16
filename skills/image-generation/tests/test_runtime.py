"""Behavioral tests. Model output is simulated; no paid image calls are made."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import detail_runtime as rt
import typography


FONT = next((path for path in [Path('C:/Windows/Fonts/msyh.ttc'),
                              Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if path.exists()), None)


def png(size=(400, 240), color='white'):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, 'PNG')
    return stream.getvalue()


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[3] / 'reports' / 'detail_page_validation' / 'tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='detail-runtime-test-', dir=temp_root)
        self.root = Path(self.temp.name).resolve()
        def cleanup():
            if self.root.parent != temp_root.resolve() or not self.root.name.startswith('detail-runtime-test-'):
                raise ValueError('Refusing cleanup outside the isolated test workspace')
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.task = rt.initialize(str(self.root), '测试商品')
        self.ws = rt.Workspace(self.task)
        if FONT is None:
            self.skipTest('No test font installed')
        self.put('01-原始资料/font.ttc', FONT.read_bytes())
        self.put('03-设计方案/plan.md', b'Fixture plan: synthetic image; no product claims.')
        self.put('05-提示词与排版数据/prompt.txt', b'White empty background with space for typography. No new text.')
        self.layout = {'canvas': [400, 240], 'protected_regions': [[0, 120, 400, 120]],
                       'text_blocks': [{'text': 'Approved text', 'font': '01-原始资料/font.ttc',
                                        'size': 24, 'color': '#102030', 'box': [20, 20, 360, 80]}]}
        self.put_json('05-提示词与排版数据/layout.json', self.layout)
        self.batch_path = '05-提示词与排版数据/batch.json'
        base = {'width': 400, 'height': 240, 'prompt': '05-提示词与排版数据/prompt.txt',
                'layout': '05-提示词与排版数据/layout.json', 'references': []}
        self.batch = {'route': 'agent', 'plan': '03-设计方案/plan.md', 'max_attempts': 2, 'candidates_per_job': 1,
                      'jobs': [{**base, 'id': 'page-001', 'kind': 'sample'}, {**base, 'id': 'page-002', 'kind': 'page'}]}
        self.put_json(self.batch_path, self.batch)
        rt.approve_plan(self.ws, self.batch['plan'], 'TEST ONLY: approved plan')
        rt.approve_batch(self.ws, self.batch_path, 'TEST ONLY: approved synthetic batch')
        self.source = self.root / 'simulated-model-output.png'
        self.source.write_bytes(png())

    def put(self, path, raw):
        target = self.ws.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    def put_json(self, path, value):
        self.put(path, rt.encode(value))

    def relative(self, path):
        return path.relative_to(self.task).as_posix()

    def generate_agent(self, ident='page-001'):
        run = rt.execute(self.ws, self.batch_path, ident)
        rt.import_agent(self.ws, self.relative(run), [self.source], 'TEST-FAKE-TOOL', 'TEST-FAKE-CALL')
        return run

    def accept_page(self, run):
        relative = self.relative(run)
        rt.render_page(self.ws, relative, 1)
        return rt.review(self.ws, relative, 1, 'TEST ONLY: accept synthetic page',
                         dict(identity=True, consistency=True, text=True, layout=True))

    def test_reject_ambiguous_roots_and_path_escape(self):
        for root in ['.', str(Path(self.root.anchor)), str(Path.home()), str(rt.SKILL_ROOT)]:
            with self.subTest(root=root), self.assertRaises(ValueError):
                rt.initialize(root, 'bad')
        for path in ['../outside', str(self.root / 'outside'), 'C:\\escape', 'task.json']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.ws.path(path)

    def test_archive_never_moves_or_overwrites_source(self):
        result = self.ws.archive(self.source, '01-原始资料/图片/input.png')
        self.assertTrue(self.source.exists())
        self.assertEqual(result['sha256'], rt.sha(self.source.read_bytes()))
        with self.assertRaises(FileExistsError):
            self.ws.archive(self.source, '01-原始资料/图片/input.png')

    def test_link_escape_is_rejected(self):
        link = self.task / '01-原始资料' / 'outside'
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        with self.assertRaises(ValueError):
            self.ws.path('01-原始资料/outside/stolen.txt')

    def test_batch_must_have_real_plan_confirmation(self):
        plan = self.ws.path(self.batch['plan'])
        plan.write_text('Changed plan', encoding='utf-8')
        with self.assertRaises(FileNotFoundError):
            rt.execute(self.ws, self.batch_path, 'page-001')

    def test_prompt_change_invalidates_batch(self):
        self.put('05-提示词与排版数据/prompt.txt', b'Changed image')
        with self.assertRaises(FileNotFoundError):
            rt.execute(self.ws, self.batch_path, 'page-001')

    def test_route_change_needs_reconfirmation(self):
        self.batch['route'] = 'unselected'
        self.put_json(self.batch_path, self.batch)
        with self.assertRaises(ValueError):
            rt.execute(self.ws, self.batch_path, 'page-001')

    def test_sample_gate_then_delivery_and_batch_page(self):
        with self.assertRaises(FileNotFoundError):
            rt.execute(self.ws, self.batch_path, 'page-002')
        run = self.generate_agent()
        approval = self.accept_page(run)
        final = self.ws.path(approval['delivery'])
        self.assertTrue(final.exists())
        self.assertEqual(final.read_bytes(), self.ws.path(approval['image']).read_bytes())
        self.assertNotEqual(final.read_bytes(), self.source.read_bytes())
        page = rt.execute(self.ws, self.batch_path, 'page-002')
        self.assertEqual(rt.read(page / 'execution.json')['status'], 'awaiting_agent')

    def test_completion_requires_all_accepted_files_and_detects_tampering(self):
        sample = self.generate_agent()
        self.accept_page(sample)
        self.assertFalse(rt.batch_status(self.ws, self.batch_path)['complete'])
        page = self.generate_agent('page-002')
        delivery = self.accept_page(page)
        self.assertTrue(rt.batch_status(self.ws, self.batch_path)['complete'])
        self.ws.path(delivery['delivery']).write_bytes(png(color='red'))
        self.assertFalse(rt.batch_status(self.ws, self.batch_path)['complete'])

    def test_pending_agent_prevents_duplicate_and_limit_is_enforced(self):
        first = rt.execute(self.ws, self.batch_path, 'page-001')
        with self.assertRaises(ValueError):
            rt.execute(self.ws, self.batch_path, 'page-001')
        rt.agent_failure(self.ws, self.relative(first), 'fake', '1', 'TEST failure')
        second = rt.execute(self.ws, self.batch_path, 'page-001')
        rt.agent_failure(self.ws, self.relative(second), 'fake', '2', 'TEST failure')
        with self.assertRaises(ValueError):
            rt.execute(self.ws, self.batch_path, 'page-001')

    def test_wrong_dimensions_not_imported(self):
        run = rt.execute(self.ws, self.batch_path, 'page-001')
        self.source.write_bytes(png((401, 240)))
        with self.assertRaises(ValueError):
            rt.import_agent(self.ws, self.relative(run), [self.source], 'fake', 'fake')
        self.assertEqual(rt.read(run / 'execution.json')['status'], 'awaiting_agent')

    def test_page_cannot_be_accepted_without_typography(self):
        run = self.generate_agent()
        with self.assertRaises(ValueError):
            rt.review(self.ws, self.relative(run), 1, 'TEST', dict(identity=True, consistency=True, text=True, layout=True))
        self.assertFalse(any((self.task / '08-最终交付').rglob('*.png')))

    def test_failed_visual_review_cannot_enter_delivery(self):
        run = self.generate_agent()
        rt.render_page(self.ws, self.relative(run), 1)
        with self.assertRaises(ValueError):
            rt.review(self.ws, self.relative(run), 1, 'TEST', dict(identity=True, consistency=True, text=False, layout=True))
        self.assertFalse(any((self.task / '08-最终交付').rglob('*.png')))

    def test_overflow_and_product_overlap_are_rejected(self):
        for box, text in [([20, 20, 10, 10], 'Does not fit'), ([20, 130, 300, 80], 'Overlap')]:
            layout = json.loads(json.dumps(self.layout))
            layout['text_blocks'][0].update(box=box, text=text)
            with self.subTest(box=box), self.assertRaises(ValueError):
                typography.render(self.source, layout, self.root / 'bad.png', self.ws.path)
            self.assertFalse((self.root / 'bad.png').exists())

    def test_missing_glyph_is_rejected(self):
        layout = json.loads(json.dumps(self.layout))
        layout['text_blocks'][0]['text'] = '\U0010ffff'
        with self.assertRaisesRegex(ValueError, 'missing characters'):
            typography.render(self.source, layout, self.root / 'bad.png', self.ws.path)

    def test_chinese_text_is_rendered_and_source_is_unchanged(self):
        if 'msyh' not in FONT.name:
            self.skipTest('CJK test font unavailable')
        self.layout['text_blocks'][0]['text'] = '中文标题\n准确排版'
        output = self.root / 'chinese.png'
        report = typography.render(self.source, self.layout, output, self.ws.path)
        self.assertEqual(report['blocks'][0]['text'], '中文标题\n准确排版')
        self.assertEqual(self.source.read_bytes(), png())
        with Image.open(output) as image:
            self.assertEqual(image.size, (400, 240))
            self.assertEqual(image.getpixel((200, 180)), (255, 255, 255))
        self.assertNotEqual(output.read_bytes(), self.source.read_bytes())

    def test_asset_dependency_is_resolved_only_after_review(self):
        asset = {'id': 'character-001', 'kind': 'asset', 'width': 400, 'height': 240,
                 'prompt': '05-提示词与排版数据/prompt.txt', 'references': []}
        self.batch['jobs'].insert(0, asset)
        self.batch['jobs'][1]['references'] = [{'from_job': 'character-001'}]
        self.put_json(self.batch_path, self.batch)
        rt.approve_batch(self.ws, self.batch_path, 'TEST updated batch')
        with self.assertRaises(FileNotFoundError):
            rt.execute(self.ws, self.batch_path, 'page-001')
        run = self.generate_agent('character-001')
        rt.review(self.ws, self.relative(run), 1, 'TEST accept asset', dict(identity=True, consistency=True))
        page = self.generate_agent()
        record = rt.read(page / 'execution.json')
        self.assertIn('character-001', record['dependency_jobs'])
        self.accept_page(page)
        other = self.generate_agent('character-001')
        # A new selection invalidates downstream approval even when bytes happen to match.
        rt.review(self.ws, self.relative(other), 1, 'TEST select another asset', dict(identity=True, consistency=True))
        with self.assertRaises(ValueError):
            rt.execute(self.ws, self.batch_path, 'page-002')

    def remote_fixture(self):
        owner = self
        self.pending, self.bad_history, self.submissions = True, False, 0
        graph = {'encode': {'class_type': 'Encode', 'inputs': {'prompt': ''}},
                 'save': {'class_type': 'Save', 'inputs': {'filename_prefix': ''}}}
        info = {'Encode': {'input': {'required': {'prompt': ['STRING', {}]}}},
                'Save': {'input': {'required': {'filename_prefix': ['STRING', {}]}}}}
        self.received_graph = None
        self.uploaded = b''

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def reply(self, value, raw=False):
                self.send_response(200); self.end_headers()
                self.wfile.write(value if raw else rt.encode(value))
            def do_GET(self):
                if self.path == '/object_info': self.reply(info)
                elif self.path == '/queue': self.reply({'queue_running': [], 'queue_pending': []})
                elif self.path.startswith('/history/'):
                    self.reply({} if owner.pending else {'test-id': {
                        'status': {'completed': True, 'status_str': 'success'},
                        'prompt': [0, 'test-id', {} if owner.bad_history else owner.received_graph],
                        'outputs': {'save': {'images': [{'filename': 'test.png', 'subfolder': '', 'type': 'output'}]}}}})
                elif self.path.startswith('/view?'):
                    self.reply(owner.uploaded if 'type=input' in self.path else png(), raw=True)
                else: self.send_error(404)
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                if self.path == '/prompt':
                    owner.submissions += 1
                    owner.received_graph = json.loads(raw)['prompt']
                    self.reply({'prompt_id': 'test-id'})
                elif self.path == '/upload/image':
                    owner.uploaded = raw.split(b'\r\n\r\n', 1)[1].split(b'\r\n--', 1)[0]
                    self.reply({'name': 'uploaded.png', 'subfolder': '', 'type': 'input'})
                else: self.send_error(404)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = 'http://127.0.0.1:' + str(server.server_port)
        rt.configure(self.root, base)
        self.put_json('06-工作流与执行记录/workflow.json', graph)
        self.put_json('06-工作流与执行记录/config.json', {
            'workflow': '06-工作流与执行记录/workflow.json', 'output_node': 'save',
            'mapping': {'prompt': {'node': 'encode', 'class_type': 'Encode', 'input': 'prompt'},
                        'prefix': {'node': 'save', 'class_type': 'Save', 'input': 'filename_prefix'}}})
        self.batch.update(route='comfyui', workflow_config='06-工作流与执行记录/config.json')
        self.put_json(self.batch_path, self.batch)
        rt.approve_batch(self.ws, self.batch_path, 'TEST ONLY mock Comfy server')
        return base

    def test_comfy_http_pending_resume_then_typeset_delivery(self):
        base = self.remote_fixture()
        self.assertEqual(rt.read(self.root / 'detail-page.connection.json')['base_url'], base)
        client = rt.Comfy(base)
        self.assertEqual(client.upload(self.source), 'uploaded.png')
        run = rt.execute(self.ws, self.batch_path, 'page-001')
        self.assertEqual(rt.resume(self.ws, self.relative(run))['status'], 'remote_pending')
        with self.assertRaises(ValueError): rt.execute(self.ws, self.batch_path, 'page-001')
        self.assertEqual(self.submissions, 1)
        self.pending = False
        rt.resume(self.ws, self.relative(run))
        self.accept_page(run)
        self.assertEqual(self.submissions, 1)

    def test_comfy_history_mismatch_cannot_be_imported(self):
        self.remote_fixture()
        run = rt.execute(self.ws, self.batch_path, 'page-001')
        self.pending, self.bad_history = False, True
        with self.assertRaisesRegex(ValueError, 'does not match'):
            rt.resume(self.ws, self.relative(run))
        self.assertNotIn('images', rt.read(run / 'execution.json'))

    def test_uncertain_remote_submission_is_never_automatically_repeated(self):
        self.remote_fixture()
        class LostResponse:
            def probe(inner): return rt.Comfy(rt.read(self.root / 'detail-page.connection.json')['base_url']).probe()
            def get(inner, route, payload=None): raise TimeoutError('TEST: response lost after submission')
        with self.assertRaises(TimeoutError):
            rt.execute(self.ws, self.batch_path, 'page-001', client=LostResponse())
        with self.assertRaisesRegex(ValueError, 'unresolved run'):
            rt.execute(self.ws, self.batch_path, 'page-001')

    def test_failed_connection_validation_keeps_previous_address(self):
        self.remote_fixture()
        target = self.root / 'detail-page.connection.json'
        previous = target.read_bytes()
        with self.assertRaises(ValueError): rt.configure(self.root, 'file:///new-server')
        self.assertEqual(target.read_bytes(), previous)

    def test_different_workflow_per_job_is_part_of_approval(self):
        self.remote_fixture()
        self.put_json('06-工作流与执行记录/override.json', rt.read(self.ws.path('06-工作流与执行记录/config.json')))
        self.batch['jobs'][0]['workflow_config'] = '06-工作流与执行记录/override.json'
        self.put_json(self.batch_path, self.batch)
        rt.approve_batch(self.ws, self.batch_path, 'TEST override confirmed')
        run = rt.execute(self.ws, self.batch_path, 'page-001')
        self.assertEqual(rt.read(run / 'execution.json')['status'], 'submitted')
        config = rt.read(self.ws.path('06-工作流与执行记录/override.json'))
        config['output_node'] = 'changed'
        self.put_json('06-工作流与执行记录/override.json', config)
        with self.assertRaises(FileNotFoundError):
            rt.approved(self.ws, self.batch_path)


if __name__ == '__main__':
    unittest.main()
