"""Behavioral tests. Model output is simulated; no paid image calls are made."""
import io
import json
import os
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
        temp_root = Path(os.environ.get('DETAIL_SKILL_TEST_ROOT', tempfile.gettempdir())).resolve()
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
        self.put_json(rt.DEFAULT_INTAKE, {'scope': 'Synthetic runtime test', 'coverage_review': 'No real product facts used',
                                         'items': [{'id': 'visual-scope', 'decision': 'No product in fixture',
                                                    'required_information': 'Purpose of the fixture', 'status': 'resolved',
                                                    'answer': 'Synthetic blank-image workflow test', 'source': 'Test fixture'}]})
        self.put('05-提示词与排版数据/prompt.txt', b'White empty background with space for typography. No new text.')
        self.layout = {'canvas': [400, 240], 'protected_regions': [[0, 120, 400, 120]],
                       'no_product_reason': 'Synthetic fixture has no product; lower zone reserved for overlay tests',
                       'text_blocks': [{'text': 'Approved text', 'font': '01-原始资料/font.ttc',
                                        'size': 24, 'color': '#102030', 'box': [20, 20, 360, 80]}]}
        self.put_json('05-提示词与排版数据/layout.json', self.layout)
        self.batch_path = '05-提示词与排版数据/batch.json'
        base = {'width': 400, 'height': 240, 'prompt': '05-提示词与排版数据/prompt.txt',
                'layout': '05-提示词与排版数据/layout.json', 'references': [],
                'product_absence_reason': 'Synthetic fixture only; not a product detail page'}
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
        run = rt.execute(self.ws, self.batch_path, ident, repair_note='TEST: explicitly requested candidate variation')
        rt.import_agent(self.ws, self.relative(run), [self.source], 'TEST-FAKE-TOOL', 'TEST-FAKE-CALL')
        return run

    def accept_page(self, run):
        relative = self.relative(run)
        self.inspect_page(run)
        rt.render_page(self.ws, relative, 1)
        return rt.review(self.ws, relative, 1, 'TEST ONLY: accept synthetic page',
                         dict(identity=True, consistency=True, text=True, layout=True, observations='TEST ONLY: synthetic fixture checks'))

    def inspect_page(self, run, regions=None):
        image = rt.read(run / 'execution.json')['images'][0]
        return rt.inspect_image(self.ws, self.relative(run), 1, {
            'image_sha256': image['sha256'], 'observations': 'TEST ONLY: simulated inspection of blank fixture',
            'actual_protected_regions': regions if regions is not None else self.layout['protected_regions'],
            'checks': dict(composition=True, lighting=True, reference_fidelity=True, no_extra_objects=True)})

    def ref(self, *, path=None, job=None, role='product'):
        return {**({'path': path} if path else {'from_job': job}), 'role': role, 'target': 'TEST subject',
                'preserve': ['Fixture identity'], 'allow': ['Placement only'], 'exclude': ['Unrelated subjects'], 'priority': 10}

    def revised_layout(self, *, box=None, text='Approved revised copy'):
        layout = json.loads(json.dumps(self.layout))
        layout['text_blocks'][0]['text'] = text
        if box is not None:
            layout['text_blocks'][0]['box'] = box
        path = '05-提示词与排版数据/layout-v002.json'
        self.put_json(path, layout)
        return path

    def page_checks(self):
        return dict(identity=True, consistency=True, text=True, layout=True,
                    observations='TEST ONLY: simulated final review')

    def rejection(self, repair='retypeset'):
        return {'issues': [{'category': 'typography', 'region': 'upper text box',
                            'expected': 'Approved copy in readable layout', 'actual': 'Test issue',
                            'correction': 'Use confirmed layout revision', 'severity': 'blocking',
                            'repair': repair}]}

    def test_intake_unresolved_and_unconfirmed_omissions_block_plan(self):
        intake = rt.read(self.ws.path(rt.DEFAULT_INTAKE))
        for state in ('pending', 'conflict', 'omitted_confirmed'):
            intake['items'][0]['status'] = state
            self.put_json(rt.DEFAULT_INTAKE, intake)
            with self.subTest(state=state), self.assertRaises(ValueError):
                rt.approve_plan(self.ws, self.batch['plan'], 'TEST must not approve unresolved intake')

    def test_changed_intake_invalidates_original_plan_confirmation(self):
        intake = rt.read(self.ws.path(rt.DEFAULT_INTAKE))
        intake['items'][0]['answer'] = 'Changed design scope; needs a new plan confirmation'
        self.put_json(rt.DEFAULT_INTAKE, intake)
        with self.assertRaises(FileNotFoundError):
            rt.execute(self.ws, self.batch_path, 'page-001')

    def test_reference_roles_and_product_absence_are_required(self):
        self.put('01-原始资料/reference.png', png())
        reference = self.ref(path='01-原始资料/reference.png')
        del reference['role']
        self.batch['jobs'][0]['references'] = [reference]
        self.put_json(self.batch_path, self.batch)
        with self.assertRaisesRegex(ValueError, 'explicit.*role'):
            rt.approve_batch(self.ws, self.batch_path, 'TEST invalid role')
        reference['role'] = 'style'
        del self.batch['jobs'][0]['product_absence_reason']
        self.put_json(self.batch_path, self.batch)
        with self.assertRaises(ValueError):
            rt.approve_batch(self.ws, self.batch_path, 'TEST style is not product identity')

    def test_effective_prompt_preserves_reference_order_and_constraints(self):
        job = {**self.batch['jobs'][0], 'references': [self.ref(path='one.png', role='style'),
                                                    self.ref(path='two.png', role='product')]}
        prompt = rt.effective_prompt(self.ws, job)
        roles = json.loads(prompt.split('precedence over style):\n', 1)[1])
        self.assertEqual([(row['image'], row['role']) for row in roles], [(1, 'style'), (2, 'product')])
        self.assertEqual(roles[1]['preserve'], ['Fixture identity'])

    def test_typography_preflight_stops_before_allocating_attempt(self):
        self.layout['text_blocks'][0]['text'] = '\U0010ffff'
        self.put_json('05-提示词与排版数据/layout.json', self.layout)
        with self.assertRaisesRegex(ValueError, 'missing characters'):
            rt.preflight_batch(self.ws, self.batch_path)
        with self.assertRaises(ValueError):
            rt.execute(self.ws, self.batch_path, 'page-001')
        self.assertFalse(list(self.ws.path(rt.FOLDERS[5]).rglob('execution.json')))

    def test_render_requires_actual_inspection_and_matching_image_hash(self):
        run = self.generate_agent()
        relative = self.relative(run)
        with self.assertRaisesRegex(ValueError, 'inspect the actual'):
            rt.render_page(self.ws, relative, 1)
        inspection = {'image_sha256': 'wrong', 'observations': 'TEST', 'actual_protected_regions': [],
                      'checks': dict(composition=True, lighting=True, reference_fidelity=True, no_extra_objects=True)}
        with self.assertRaisesRegex(ValueError, 'actual generated image hash'):
            rt.inspect_image(self.ws, relative, 1, inspection)

    def test_shifted_product_requires_new_layout_but_reuses_the_base(self):
        run = self.generate_agent()
        relative = self.relative(run)
        report = self.inspect_page(run, [[0, 0, 400, 120]])
        self.assertIsNotNone(report['planned_layout_conflict'])
        with self.assertRaisesRegex(ValueError, 'protected'):
            rt.render_page(self.ws, relative, 1)
        path = self.revised_layout(box=[20, 140, 360, 80])
        # The new layout's intended protection is updated to match the inspected geometry.
        layout = rt.read(self.ws.path(path))
        layout['protected_regions'] = [[0, 0, 400, 120]]
        self.put_json(path, layout)
        rt.approve_layout(self.ws, relative, 1, path, 'TEST user accepts avoiding actual product')
        result = rt.render_page(self.ws, relative, 1, path)
        self.assertEqual(result['image']['sha256'], rt.sha(self.source.read_bytes()))
        self.assertEqual(len(list(run.parent.glob('attempt-*'))), 1)

    def test_layout_revision_needs_confirmation_and_preserves_old_result(self):
        run = self.generate_agent()
        original = self.accept_page(run)
        old_bytes = self.ws.path(original['delivery']).read_bytes()
        relative = self.relative(run)
        path = self.revised_layout()
        with self.assertRaises(FileNotFoundError):
            rt.render_page(self.ws, relative, 1, path)
        rt.approve_layout(self.ws, relative, 1, path, 'TEST actual confirmation of revised layout')
        status = rt.batch_status(self.ws, self.batch_path)
        self.assertEqual(status['jobs'][0]['status'], 'not_accepted_or_stale')
        rt.render_page(self.ws, relative, 1, path)
        revised = rt.review(self.ws, relative, 1, 'TEST user accepts revised page', self.page_checks())
        self.assertNotEqual(revised['delivery'], original['delivery'])
        self.assertEqual(self.ws.path(original['delivery']).read_bytes(), old_bytes)
        self.assertEqual(rt.read(run / 'execution.json')['images'][0]['sha256'], rt.sha(self.source.read_bytes()))
        self.assertEqual(rt.batch_status(self.ws, self.batch_path)['jobs'][0]['status'], 'accepted')

    def test_generation_change_blocks_typography_only_reuse(self):
        run = self.generate_agent()
        self.inspect_page(run)
        path = self.revised_layout()
        self.put('05-提示词与排版数据/prompt.txt', b'Changed image content')
        with self.assertRaisesRegex(ValueError, 'Generation input changed'):
            rt.approve_layout(self.ws, self.relative(run), 1, path, 'TEST should not reuse')

    def test_retypeset_rejection_requires_a_new_confirmed_render(self):
        run = self.generate_agent()
        self.accept_page(run)
        relative = self.relative(run)
        rt.reject_image(self.ws, relative, 1, self.rejection())
        with self.assertRaisesRegex(ValueError, 'unresolved visual rejection'):
            rt.review(self.ws, relative, 1, 'TEST invalid approval', self.page_checks())
        path = self.revised_layout()
        rt.approve_layout(self.ws, relative, 1, path, 'TEST revised typography approved')
        rt.render_page(self.ws, relative, 1, path)
        rt.review(self.ws, relative, 1, 'TEST repaired result accepted', self.page_checks())
        self.assertEqual(rt.batch_status(self.ws, self.batch_path)['jobs'][0]['status'], 'accepted')
        self.assertEqual(len(list(run.glob('reject-*.json'))), 1)

    def test_image_content_rejection_cannot_be_cleared_by_typography(self):
        run = self.generate_agent()
        self.inspect_page(run)
        relative = self.relative(run)
        rt.reject_image(self.ws, relative, 1, self.rejection('regenerate'))
        rt.reject_image(self.ws, relative, 1, self.rejection('retypeset'))
        path = self.revised_layout()
        rt.approve_layout(self.ws, relative, 1, path, 'TEST typography change')
        rt.render_page(self.ws, relative, 1, path)
        with self.assertRaisesRegex(ValueError, 'unresolved visual rejection'):
            rt.review(self.ws, relative, 1, 'TEST typography cannot repair identity', self.page_checks())
        self.assertEqual(len(rt.read(run / 'execution.json')['images'][0]['rejections']), 1)

    def test_confirmed_layout_cannot_accept_a_previous_render(self):
        run = self.generate_agent()
        relative = self.relative(run)
        self.inspect_page(run)
        rt.render_page(self.ws, relative, 1)
        path = self.revised_layout()
        rt.approve_layout(self.ws, relative, 1, path, 'TEST newer layout confirmation')
        with self.assertRaisesRegex(ValueError, 'not been rendered'):
            rt.review(self.ws, relative, 1, 'TEST cannot accept older render', self.page_checks())
        with self.assertRaisesRegex(ValueError, 'newly confirmed'):
            rt.render_page(self.ws, relative, 1)
        rt.render_page(self.ws, relative, 1, path)
        with self.assertRaisesRegex(ValueError, 'newly confirmed'):
            rt.render_page(self.ws, relative, 1)

    def test_updated_inspection_invalidates_render_and_accepted_selection(self):
        run = self.generate_agent()
        self.accept_page(run)
        relative = self.relative(run)
        self.inspect_page(run, [[0, 160, 400, 80]])
        with self.assertRaisesRegex(ValueError, 'current actual image inspection'):
            rt.review(self.ws, relative, 1, 'TEST cannot reuse stale inspection', self.page_checks())
        self.assertEqual(rt.batch_status(self.ws, self.batch_path)['jobs'][0]['status'], 'not_accepted_or_stale')
        rt.render_page(self.ws, relative, 1)
        rt.review(self.ws, relative, 1, 'TEST new inspection and render accepted', self.page_checks())

    def test_sample_layout_change_invalidates_its_generated_downstream_page(self):
        sample = self.generate_agent()
        self.accept_page(sample)
        page = self.generate_agent('page-002')
        self.accept_page(page)
        path = self.revised_layout()
        relative = self.relative(sample)
        rt.approve_layout(self.ws, relative, 1, path, 'TEST user selects new sample style')
        rt.render_page(self.ws, relative, 1, path)
        rt.review(self.ws, relative, 1, 'TEST accepts revised sample', self.page_checks())
        with self.assertRaisesRegex(ValueError, 'Reference selection changed'):
            rt.review(self.ws, self.relative(page), 1, 'TEST stale downstream page', self.page_checks())
        status = rt.batch_status(self.ws, self.batch_path)
        self.assertEqual(status['jobs'][1]['status'], 'not_accepted_or_stale')

    def test_rejecting_another_candidate_preserves_the_selected_one(self):
        self.batch['candidates_per_job'] = 2
        self.put_json(self.batch_path, self.batch)
        rt.approve_batch(self.ws, self.batch_path, 'TEST two candidates approved')
        run = rt.execute(self.ws, self.batch_path, 'page-001')
        rt.import_agent(self.ws, self.relative(run), [self.source, self.source], 'TEST tool', 'TEST call')
        self.accept_page(run)
        rt.reject_image(self.ws, self.relative(run), 2, self.rejection('regenerate'))
        self.assertEqual(rt.batch_status(self.ws, self.batch_path)['jobs'][0]['status'], 'accepted')

    def test_new_generated_candidate_needs_directed_repair_note(self):
        self.generate_agent()
        with self.assertRaises(ValueError):
            rt.execute(self.ws, self.batch_path, 'page-001')
        run = rt.execute(self.ws, self.batch_path, 'page-001', repair_note='TEST repair the observed background defect')
        self.assertEqual(rt.read(run / 'execution.json')['repair_note'], 'TEST repair the observed background defect')

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
        self.inspect_page(run)
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
        self.batch['jobs'][1]['references'] = [self.ref(job='character-001', role='person')]
        self.put_json(self.batch_path, self.batch)
        rt.approve_batch(self.ws, self.batch_path, 'TEST updated batch')
        with self.assertRaises(FileNotFoundError):
            rt.execute(self.ws, self.batch_path, 'page-001')
        run = self.generate_agent('character-001')
        rt.review(self.ws, self.relative(run), 1, 'TEST accept asset', dict(identity=True, consistency=True, observations='TEST ONLY fixture'))
        page = self.generate_agent()
        record = rt.read(page / 'execution.json')
        self.assertIn('character-001', record['dependency_jobs'])
        self.accept_page(page)
        other = self.generate_agent('character-001')
        # A new selection invalidates downstream approval even when bytes happen to match.
        rt.review(self.ws, self.relative(other), 1, 'TEST select another asset', dict(identity=True, consistency=True, observations='TEST ONLY fixture'))
        with self.assertRaises(ValueError):
            rt.execute(self.ws, self.batch_path, 'page-002')

    def remote_fixture(self):
        owner = self
        self.pending, self.bad_history, self.submissions = True, False, 0
        graph = {'encode': {'class_type': 'Encode', 'inputs': {'prompt': ''}},
                 'latent': {'class_type': 'Latent', 'inputs': {'width': 400, 'height': 240, 'batch_size': 1}},
                 'save': {'class_type': 'Save', 'inputs': {'filename_prefix': '', 'prompt': ['encode', 0], 'latent': ['latent', 0]}}}
        info = {'Encode': {'input': {'required': {'prompt': ['STRING', {}]}}},
                'Latent': {'input': {'required': {key: ['INT', {'min': 1}] for key in ('width', 'height', 'batch_size')}}, 'output': ['LATENT']},
                'Save': {'input': {'required': {'filename_prefix': ['STRING', {}], 'prompt': ['STRING', {}], 'latent': ['LATENT', {}]}}}}
        info['Encode']['output'] = ['STRING']
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
            'capabilities': {'mode': 'background', 'model': 'TEST-only synthetic model', 'max_references': 0,
                             'supported_sizes': [[400, 240]], 'validation_evidence': 'TEST HTTP fixture; no real model execution'},
            'fixed': {key: {'node': 'latent', 'class_type': 'Latent', 'input': field}
                      for key, field in [('width', 'width'), ('height', 'height'), ('candidates', 'batch_size')]},
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

    def test_comfy_preflight_does_not_upload_submit_or_allocate_attempt(self):
        self.remote_fixture()
        result = rt.preflight_batch(self.ws, self.batch_path)
        self.assertEqual(result['status'], 'preflight_passed')
        self.assertFalse(result['semantic_image_quality_verified'])
        self.assertEqual(self.submissions, 0)
        self.assertEqual(self.uploaded, b'')
        self.assertFalse(list(self.ws.path(rt.FOLDERS[5]).rglob('execution.json')))

    def test_workflow_duplicate_binding_and_disconnected_prompt_are_rejected(self):
        self.remote_fixture()
        config_path = '06-工作流与执行记录/config.json'
        config = rt.read(self.ws.path(config_path))
        config['mapping']['prefix'] = config['mapping']['prompt'].copy()
        self.put_json(config_path, config)
        with self.assertRaisesRegex(ValueError, 'share a binding target'):
            rt.preflight_batch(self.ws, self.batch_path)
        config['mapping']['prefix'] = {'node': 'save', 'class_type': 'Save', 'input': 'filename_prefix'}
        self.put_json(config_path, config)
        graph = rt.read(self.ws.path(config['workflow']))
        graph['unapproved'] = {'class_type': 'Encode', 'inputs': {'prompt': 'Unapproved fixed text'}}
        graph['save']['inputs']['prompt'] = ['unapproved', 0]
        self.put_json(config['workflow'], graph)
        with self.assertRaisesRegex(ValueError, 'does not reach'):
            rt.preflight_batch(self.ws, self.batch_path)
        self.assertEqual(self.submissions, 0)
        self.assertEqual(self.uploaded, b'')

    def test_workflow_fixed_dimensions_and_explicit_negative_prompt_are_checked(self):
        self.remote_fixture()
        config = rt.read(self.ws.path('06-工作流与执行记录/config.json'))
        graph = rt.read(self.ws.path(config['workflow']))
        graph['latent']['inputs']['width'] = 401
        self.put_json(config['workflow'], graph)
        with self.assertRaisesRegex(ValueError, 'Fixed workflow parameter'):
            rt.preflight_batch(self.ws, self.batch_path)
        graph['latent']['inputs']['width'] = 400
        self.put_json(config['workflow'], graph)
        self.batch['jobs'][0]['negative_prompt'] = 'TEST explicitly approved unwanted content'
        self.put_json(self.batch_path, self.batch)
        with self.assertRaisesRegex(ValueError, 'negative prompt'):
            rt.preflight_batch(self.ws, self.batch_path)
        self.assertEqual(self.submissions, 0)

    def test_reference_filename_enum_is_rechecked_after_upload(self):
        base = self.remote_fixture()
        config_path = '06-工作流与执行记录/config.json'
        config = rt.read(self.ws.path(config_path))
        config['capabilities'].update(mode='reference_edit', max_references=1)
        config['mapping']['reference_0'] = {'node': 'load', 'class_type': 'LoadImage', 'input': 'image'}
        graph = rt.read(self.ws.path(config['workflow']))
        graph['load'] = {'class_type': 'LoadImage', 'inputs': {'image': 'old.png'}}
        graph['save']['inputs']['image'] = ['load', 0]
        info = rt.Comfy(base).probe()
        info['LoadImage'] = {'input': {'required': {'image': [['old.png'], {}]}}, 'output': ['IMAGE']}
        info['Save']['input']['required']['image'] = ['IMAGE', {}]
        self.put_json(config_path, config)
        self.put_json(config['workflow'], graph)
        job = self.batch['jobs'][0]
        rt.prepare_graph(self.ws, self.batch, job, info, ['pending'], 'TEST', pending_references=True)
        self.assertEqual(info['LoadImage']['input']['required']['image'][0], ['old.png'])
        with self.assertRaises(ValueError):
            rt.prepare_graph(self.ws, self.batch, job, info, ['uploaded.png'], 'TEST')
        info['LoadImage']['input']['required']['image'][0].append('uploaded.png')
        result, output = rt.prepare_graph(self.ws, self.batch, job, info, ['uploaded.png'], 'TEST')
        self.assertEqual(result['load']['inputs']['image'], 'uploaded.png')
        self.assertEqual(output, 'save')

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
