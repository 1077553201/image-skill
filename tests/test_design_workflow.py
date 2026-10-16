from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from product_studio.creative.design_workflow import DesignSession, validate_page

ROOT=Path(__file__).resolve().parents[1]


def page(pid='a'):
    return {'page_id':pid,'page_purpose':'overview','key_message':'visible shape',
        'target_audience':'buyers','consumer_copy':{'headline':'Brown bag'},
        'composition':{'text_regions':[[.05,.05,.3,.2]],'description':'free editorial'},
        'product_position':[.653,.537],'product_scale':.61,'camera_angle':'source front',
        'focal_point':'bag','background_description':'empty gray','lighting_design':'diffuse upper left',
        'color_palette':['#eeeeee'],'typography':{'size':42},'decorative_elements':[],
        'layer_structure':[],'required_assets':[],'image_generation_route':'background_only',
        'output_size':[1200,1200],'fidelity_level':'source_preserving_preview',
        'quality_criteria':['no extra objects']}


class DesignWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT)
        self.session=DesignSession(self.temp.name)
        self.binding={k:k+'-fixture' for k in ('source_id','source_sha256','instance_id','mask_version','mask_sha256','rgba_sha256')}
        self.session.create(self.binding,'test','synthetic fixture, not real user approval')
        self.brief={'user_requirements':{'audience':'high end'},'verified_product_facts':{},
            'visual_observations':{},'design_recommendations':{},'unknown_properties':{'material':None},'blocking_questions':[]}
        for kind,value in [('creative_brief',self.brief),('product_analysis',{'observed':'brown'}),
                           ('reference_analysis',{'status':'not_provided'}),
                           ('creative_concepts',{'concepts':[{'concept_id':'x'},{'concept_id':'y'}]})]:
            self.session.put(kind,value)

    def tearDown(self):self.temp.cleanup()
    def approve(self):self.session.approve_concept('x','fixture user','test-only selection')
    def pages(self):self.session.put('page_designs',{'pages':[page('a'),page('b')]})

    def test_concept_approval_required(self):
        with self.assertRaisesRegex(ValueError,'concept'):self.pages()
    def test_concept_is_not_page_approval(self):
        self.approve();self.pages()
        with self.assertRaisesRegex(ValueError,'page design'):self.session.handoff('a','unused')
        self.assertEqual(self.session.load()['state'],'awaiting_design_approval')
    def test_page_revision_preserves_sibling_approval(self):
        self.approve();self.pages()
        for pid in ('a','b'):self.session.approve_page(pid,'test user','test-only')
        pages=[page('a'),page('b')];pages[0]['consumer_copy']['headline']='New headline'
        self.session.put('page_designs',{'pages':pages})
        self.assertEqual(set(self.session.load()['page_approvals']),{'b'})
    def test_brief_change_invalidates_all_approvals(self):
        self.approve();self.pages();self.session.approve_page('a','test user','test-only')
        brief=deepcopy(self.brief);brief['user_requirements']['audience']='other'
        self.session.put('creative_brief',brief)
        state=self.session.load()
        self.assertIsNone(state['concept_approval']);self.assertFalse(state['page_approvals'])
        self.assertNotIn('page_designs',state['artifacts'])
    def test_concept_switch_discards_prior_pages(self):
        self.approve();self.pages();self.session.approve_concept('y','test user','test-only')
        self.assertNotIn('page_designs',self.session.load()['artifacts'])
    def test_blocking_answers_prevent_approval(self):
        brief=deepcopy(self.brief);brief['blocking_questions']=['Which product?']
        self.session.put('creative_brief',brief)
        self.assertEqual(self.session.load()['state'],'awaiting_answers')
        with self.assertRaisesRegex(ValueError,'blocking'):self.approve()
    def test_copy_never_uses_internal_notes(self):
        p=page();p['internal_notes']={'headline':'pipeline skill'};validate_page(p)
        p['consumer_copy']['headline']='pipeline skill'
        with self.assertRaises(ValueError):validate_page(p)
    def test_no_fixed_family_or_coordinates_required(self):
        validate_page(page());self.assertNotIn('family',page())
    def test_invalid_coordinates_rejected(self):
        p=page();p['product_position']=[1.1,0]
        with self.assertRaises(ValueError):validate_page(p)
        p=page();p['composition']['text_regions']=[[.9,0,.2,.1]]
        with self.assertRaises(ValueError):validate_page(p)
    def test_unknown_is_not_defaulted_to_claim(self):
        self.assertIsNone(self.session.load()['artifacts']['creative_brief']['unknown_properties']['material'])
        self.assertEqual(self.session.load()['artifacts']['creative_brief']['verified_product_facts'],{})
    def test_snapshot_and_history_tamper_detected(self):
        current=self.session.load();path=Path(self.temp.name)/'revisions/0001.json'
        path.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'history'):self.session.load()
        self.assertGreater(current['revision'],1)
    def test_approval_needs_identity_and_statement(self):
        with self.assertRaises(ValueError):self.session.approve_concept('x','','')
    def test_duplicate_pages_rejected(self):
        self.approve()
        with self.assertRaises(ValueError):self.session.put('page_designs',{'pages':[page(),page()]})
    def test_foreign_page_asset_rejected(self):
        self.approve();p=page();p['required_assets']=[{'binding':{**self.binding,'instance_id':'other'}}]
        with self.assertRaisesRegex(ValueError,'another instance'):self.session.put('page_designs',{'pages':[p]})
    def test_wrong_concept_page_packet_rejected(self):
        self.approve()
        with self.assertRaisesRegex(ValueError,'another concept'):self.session.put('page_designs',{'concept_id':'y','pages':[page()]})
    def test_prompt_uses_actual_page_design_without_submitting(self):
        self.approve();self.pages();self.session.approve_page('a','test user','test-only')
        with patch('product_studio.generation.compositor.load_foreground',return_value=(None,{'binding':self.binding},{})):
            result=self.session.handoff('a','fixture')
        self.assertIn('0.653',result['background_prompt'])
        self.assertIn('diffuse upper left',result['background_prompt'])
        self.assertFalse(result['provider_submitted'])
        self.assertEqual(result['final_asset_review_status'],'pending')
    def test_current_source_binding_required_at_handoff(self):
        self.approve();self.pages();self.session.approve_page('a','test user','test-only')
        wrong={**self.binding,'instance_id':'different'}
        with patch('product_studio.generation.compositor.load_foreground',return_value=(None,{'binding':wrong},{})):
            with self.assertRaisesRegex(ValueError,'binding'):self.session.handoff('a','fixture')
    def test_strict_handoff_uses_existing_mask_gate(self):
        self.approve();p=page();p['fidelity_level']='strict_product'
        self.session.put('page_designs',{'pages':[p]});self.session.approve_page('a','test user','test-only')
        with patch('product_studio.generation.compositor.load_foreground',side_effect=ValueError('mask unreviewed')) as gate:
            with self.assertRaisesRegex(ValueError,'unreviewed'):self.session.handoff('a','fixture')
            self.assertEqual(gate.call_args.kwargs['mode'],'strict')
    def test_revision_snapshots_remain_unchanged(self):
        first=(Path(self.temp.name)/'revisions/0001.json').read_bytes()
        self.approve();self.pages()
        self.assertEqual(first,(Path(self.temp.name)/'revisions/0001.json').read_bytes())


if __name__=='__main__':unittest.main()
