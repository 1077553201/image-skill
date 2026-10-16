from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from product_studio.creative.campaign import campaign_request, validate_understanding, organize_facts, validate_agent_copy
from product_studio.creative.intents import select_intents, scene_gate, TYPES
from product_studio.creative.layouts import compile_layout, placement
from product_studio.creative.executor import execute
from product_studio.generation.compositor import composite_arrays
from product_studio.generation.marketing_renderer import draw_typography
from product_studio.segmentation.pipeline import segment
from product_studio.segmentation.base import MaskPrediction

ROOT=Path(__file__).resolve().parents[1]


def observation(binding):
    return {'schema_version':'product_understanding.4b.1','provider':'image_capable_agent','image_read_tool':'fixture_not_real_vision',
            'binding':binding,'visible_view':'front','display_name':'Example object','facts':{},'fact_kinds':{},'features':[],
            'detail_regions':[],'copy':{},'recommended_intents':['white_hero']}


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.binding={'source_id':'src1','source_sha256':'a'*64,'instance_id':'one','mask_version':'b'*64}
        self.analysis=observation(self.binding)
        self.req=campaign_request({'product_id':'new_object','product_asset':'asset.json'})

    def test_optional_defaults(self):
        self.assertIsNone(self.req['product_category']);self.assertEqual(self.req['product_facts'],{})
        self.assertEqual(self.req['output_count'],6);self.assertIsNone(self.req['reference_url'])

    def test_empty_optional_mappings(self):
        r=campaign_request({'product_id':'new_object','product_asset':'a','generation_budget':{},'output_sizes':{}})
        self.assertEqual(r['generation_budget']['max_new_backgrounds'],2);self.assertIn('default',r['output_sizes'])

    def test_one_input_required(self):
        for raw in ({'product_id':'x'},{'product_id':'x','product_asset':'a','product_image':'b'}):
            with self.assertRaises(ValueError):campaign_request(raw)

    def test_path_product_id_rejected(self):
        with self.assertRaises(ValueError):campaign_request({'product_id':'../overwrite','product_asset':'a'})

    def test_sizes_budgets_count(self):
        for extra in ({'output_count':0},{'output_count':12},{'generation_budget':{'max_new_backgrounds':5}},
                      {'output_sizes':{'default':[1000,513]}}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):campaign_request({'product_id':'x','product_asset':'a',**extra})

    def test_analysis_cross_instance_rejected(self):
        self.analysis['binding']={**self.binding,'instance_id':'two'}
        with self.assertRaises(ValueError):validate_understanding(self.analysis,self.binding,(100,100,4))

    def test_agent_not_human_verification(self):
        self.analysis['facts']={'x':{'value':'x','status':'human_verified','sources':['src1'],'method':'agent','reviewer':'Agent'}}
        with self.assertRaises(ValueError):validate_understanding(self.analysis,self.binding,(100,100,4))

    def test_performance_cannot_be_visual_guess(self):
        self.analysis['facts']={'noise_cancellation':{'value':True,'status':'observed','sources':['src1'],'method':'agent'}}
        self.analysis['fact_kinds']={'noise_cancellation':'performance'}
        with self.assertRaises(ValueError):validate_understanding(self.analysis,self.binding,(100,100,4))

    def test_unknowns_stay_null(self):
        facts=organize_facts(self.req,self.analysis,self.binding)
        for key in ['dimensions','weight','material','brand','compatibility','performance']:
            self.assertIsNone(facts['facts'][key]['value']);self.assertEqual(facts['facts'][key]['status'],'unknown')

    def test_sku_claim_contamination(self):
        self.req['product_facts']={'weight_g':{'value':500,'status':'human_verified','reviewer':'User','method':'statement',
                                  'provenance':{'kind':'user_statement','statement':'500 g','product_id':'different_product'}}}
        with self.assertRaises(ValueError):organize_facts(self.req,self.analysis,self.binding)

    def test_human_fact_requires_statement(self):
        self.req['product_facts']={'weight_g':{'value':500,'status':'human_verified','reviewer':'User','method':'statement',
                                  'provenance':{'product_id':'new_object'}}}
        with self.assertRaises(ValueError):organize_facts(self.req,self.analysis,self.binding)

    def test_false_feature_rejected(self):
        self.analysis['features']=[{'title':'Wireless','fact_ids':['wireless']}]
        with self.assertRaises(ValueError):validate_agent_copy(self.analysis,organize_facts(self.req,self.analysis,self.binding))

    def test_dynamic_count_and_missing_spec_fallback(self):
        self.req['output_count']=3;self.req['shot_types']=['specifications','comparison','white_hero','studio_photo','wide_banner']
        selected,decisions=select_intents(self.req,organize_facts(self.req,self.analysis,self.binding),self.analysis)
        self.assertEqual(len(selected),3);self.assertNotIn('specifications',selected);self.assertNotIn('comparison',selected)
        self.assertTrue(decisions)

    def test_structure_not_required(self):
        self.req['output_count']=1
        selected,_=select_intents(self.req,organize_facts(self.req,self.analysis,self.binding),self.analysis)
        self.assertEqual(selected,['white_hero'])

    def test_intent_registry_contract(self):
        self.assertEqual(len(TYPES),11)
        for value in TYPES.values():self.assertTrue(value.required_assets and value.authenticity and value.fallback)

    def test_level_two_editorial_panel(self):
        self.assertTrue(scene_gate({'level':2,'presentation':'editorial_panel'},['evidence_preserving'])['allowed'])

    def test_contact_and_wrong_perspective_rejected(self):
        for scene in ({'level':2,'holding':True},{'level':2,'presentation':'physical_tabletop'},{'level':1,'occlusion':True}):
            self.assertFalse(scene_gate(scene,['evidence_preserving'])['allowed'])

    def test_level_three_interface_not_false_success(self):
        result=scene_gate({'level':3},['concept_creative'])
        self.assertFalse(result['allowed']);self.assertEqual(result['route'],'concept_creative')
        self.assertEqual(result['capability'],'interface_only')

    def test_adaptive_different_shapes_no_stretch(self):
        for w,h in [(60,60),(20,110),(130,30),(79,100)]:
            with self.subTest(w=w,h=h):
                rgba=np.zeros((160,160,4),np.uint8);rgba[5:5+h,5:5+w,:3]=[20,80,140];rgba[5:5+h,5:5+w,3]=255
                scale,center=placement(rgba,[40,40,432,432],[512,512])
                output,a,_,transform=composite_arrays(rgba,np.full((512,512,3),255,np.uint8),scale=scale,center_normalized=center)
                mat=transform['matrix_source_to_output'];self.assertEqual(mat[0][0],mat[1][1]);self.assertEqual(mat[0][1],0)
                self.assertGreater(np.count_nonzero(a),0)

    def test_environment_plan_has_explicit_panel(self):
        rgba=np.full((100,80,4),255,np.uint8)
        facts=organize_facts(self.req,self.analysis,self.binding)
        shot=compile_layout('lifestyle_scene',0,self.req,self.analysis,facts,rgba,{},['environment'])
        self.assertTrue(shot['panels']);self.assertEqual(shot['presentation'],'editorial_panel')

    def test_detail_bbox_bounds(self):
        self.analysis['detail_regions']=[{'bbox':[90,90,30,30]}]
        with self.assertRaises(ValueError):validate_understanding(self.analysis,self.binding,(100,100,4))

    def test_auto_wrap_and_explicit_lines(self):
        font='C:/Windows/Fonts/arial.ttf'
        if not Path(font).exists():self.skipTest('Local test font unavailable')
        style={'copy_vocabulary':['Long','title','fits'],'palette':{'ink':'#111111'},'font_regular':font,'font_bold':font,'safe_margin_px':20}
        node={'text':'Long title\nLong title','x':30,'y':30,'size':60,'color':'ink','auto_wrap':True,
              'prefer_explicit_lines':True,'max_width':210,'max_height':160}
        checks=draw_typography(Image.new('RGB',(400,300),'white'),[node],style,{'facts':{}})
        self.assertEqual(len(checks[0]['rendered_text'].splitlines()),2)
        self.assertFalse(checks[0]['truncated']);self.assertLess(checks[0]['actual_size'],60)

    def test_text_overflow_does_not_silently_truncate(self):
        font='C:/Windows/Fonts/arial.ttf'
        if not Path(font).exists():self.skipTest('Local test font unavailable')
        style={'copy_vocabulary':['Long'],'palette':{'ink':'#111111'},'font_regular':font,'font_bold':font,'safe_margin_px':10}
        node={'text':' '.join(['Long']*100),'x':20,'y':20,'size':50,'color':'ink','auto_wrap':True,'max_width':50,'max_height':20}
        with self.assertRaises(ValueError):draw_typography(Image.new('RGB',(300,200),'white'),[node],style,{'facts':{}})


class CampaignExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        (self.root/'data/outputs').mkdir(parents=True)
        (self.root/'configs/platform_presets').mkdir(parents=True)
        (self.root/'configs/platform_presets/generic.json').write_text('{"id":"generic"}')
        source=self.root/'source.png';Image.new('RGB',(100,100),'red').save(source)
        class Fixture:
            def predict(self,rgb):return MaskPrediction(np.full(rgb.shape[:2],255,np.uint8),{'provider':'synthetic_campaign_fixture'})
        self.result=segment(source,(10,10,60,70),'selected',self.root/'asset',Fixture())
        self.req={'product_id':'unfamiliar','product_asset':str(self.root/'asset/segmentation_result.json'),
                  'output_count':1,'shot_types':['white_hero'],'generation_budget':{'max_new_backgrounds':0},
                  'output_sizes':{'default':[512,512]},'output_dir':'data/outputs/campaign'}
        self.path=self.root/'request.json'
    def tearDown(self):self.temp.cleanup()
    def run_request(self):
        self.path.write_text(json.dumps(self.req),encoding='utf-8');return execute(self.root,self.path)
    def test_missing_vision_handoff_not_success(self):
        result=self.run_request();self.assertEqual(result['status'],'needs_agent_analysis')
        self.assertTrue((self.root/'data/outputs/campaign/agent_handoff.json').exists())
        handoff=json.loads((self.root/'data/outputs/campaign/agent_handoff.json').read_text(encoding='utf-8'))
        self.assertTrue(Path(handoff['source_image']).is_file())
        self.assertEqual(Path(handoff['source_image']).suffix,'.png')
        self.assertFalse((self.root/'data/outputs/campaign/manifest.json').exists())
    def test_strict_gate_rejects_unreviewed(self):
        self.req['review_policy']={'mode':'strict'}
        with self.assertRaises(ValueError):self.run_request()
    def test_no_network_white_campaign_and_resume(self):
        analysis=self.root/'analysis.json';analysis.write_text(json.dumps(observation(self.result['binding'])),encoding='utf-8')
        self.req['agent_analysis']=str(analysis)
        with patch('product_studio.creative.executor.ComfyUIProvider',side_effect=AssertionError('No network/model for white')):
            result=self.run_request();self.assertEqual(result['images'],1);self.assertEqual(result['mode'],'preview')
            from product_studio.creative.quality import validate_campaign
            self.assertTrue(validate_campaign(self.root,self.root/'data/outputs/campaign')['engineering_passed'])
            image=self.root/'data/outputs/campaign/01_white_hero/final.png';before=image.read_bytes()
            self.run_request();self.assertEqual(image.read_bytes(),before)
    def test_changed_request_does_not_overwrite(self):
        self.run_request();self.req['product_id']='another'
        with self.assertRaises(ValueError):self.run_request()
    def test_real_handoff_can_advance_without_losing_initial_request(self):
        self.assertEqual(self.run_request()['status'],'needs_agent_analysis')
        analysis=self.root/'analysis.json';analysis.write_text(json.dumps(observation(self.result['binding'])),encoding='utf-8')
        self.req['agent_analysis']=str(analysis)
        with patch('product_studio.creative.executor.ComfyUIProvider',side_effect=AssertionError('White requires no remote model')):
            self.assertEqual(self.run_request()['status'],'rendered_pending_review')
        self.assertEqual(len(list((self.root/'data/outputs/campaign').glob('request_before_handoff_*.json'))),1)
    def test_output_outside_workspace_rejected(self):
        self.req['output_dir']='../outside'
        with self.assertRaises(ValueError):self.run_request()
