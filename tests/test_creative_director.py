from copy import deepcopy
import unittest
import numpy as np

from product_studio.creative.campaign import campaign_request
from product_studio.creative.layouts import compile_layout
from product_studio.creative.director import FAMILIES,repetition_risks
from product_studio.generation.compositor import composite_arrays


class CreativeDirectorTests(unittest.TestCase):
    def setUp(self):
        self.rgba=np.zeros((300,400,4),np.uint8);self.rgba[20:280,50:350]=[30,90,120,255]
        self.request=campaign_request({'product_id':'example','product_asset':'a','creative_direction':{'enabled':True}})
        self.analysis={'display_name':'Product','consumer_copy':{'studio_photo':{'headline':'A distinct form.','body':'Visible design.'}},
                       'detail_regions':[{'bbox':[70,60,100,100],'label':'Surface detail','fact_ids':[]}],
                       'features':[{'title':'Surface','description':'Visible design','fact_ids':[]}]}
    def compile(self,family,rgba=None):
        r=deepcopy(self.request);r['creative_direction']['intent_layouts']={'studio_photo':{'family':family,'reason':'Marketing purpose selected by current campaign'}}
        return compile_layout('studio_photo',0,r,self.analysis,{'facts':{}},rgba if rgba is not None else self.rgba,{},['studio'])
    def test_all_families_preserve_uniform_uncropped_subject(self):
        for family in FAMILIES:
            for shape in [(210,50),(40,260),(200,210)]:
                rgba=np.zeros((300,300,4),np.uint8);h,w=shape;rgba[10:10+h,10:10+w]=[0,30,90,255]
                with self.subTest(family=family,shape=shape):
                    s=self.compile(family,rgba);_,a,_,t=composite_arrays(rgba,np.zeros((1024,1024,3),np.uint8),scale=s['scale'],center_normalized=s['center'])
                    self.assertGreater(a.sum(),0);self.assertFalse(t['perspective']);self.assertEqual(t['matrix_source_to_output'][0][0],t['matrix_source_to_output'][1][1])
    def test_families_actually_change_positions_and_type_zones(self):
        shots=[self.compile(f) for f in FAMILIES]
        self.assertGreaterEqual(len({tuple(s['center']) for s in shots}),6)
        self.assertGreaterEqual(len({tuple((n['x'],n['y']) for n in s['consumer_copy']) for s in shots}),6)
    def test_category_is_not_a_template_selector(self):
        first=self.compile('asymmetric_editorial');self.request['product_category']='a completely different category'
        second=self.compile('asymmetric_editorial');self.assertEqual(first['layout'],second['layout'])
    def test_unknown_family_is_not_fake_success(self):
        with self.assertRaises(ValueError):self.compile('wearing_contact_scene')
    def test_macro_requires_real_source_crop(self):
        self.analysis['detail_regions']=[]
        with self.assertRaises(ValueError):self.compile('macro_story')
    def test_repeat_detector_flags_same_composition_without_aesthetic_approval(self):
        a=self.compile('magazine_cover');b=deepcopy(a);b['shot_id']='another'
        result=repetition_risks([a,b]);self.assertTrue(result['risks']);self.assertFalse(result['metric_is_aesthetic_approval'])
    def test_new_ambient_layout_has_no_automatic_white_panel(self):
        shot=self.compile('full_frame');self.assertEqual(shot['panels'],[]);self.assertEqual(shot['scene_level'],1)
    def test_explicit_level_two_panel_is_not_silently_ignored(self):
        self.request['scene']={'level':2,'presentation':'editorial_panel'}
        shot=compile_layout('lifestyle_scene',0,self.request,self.analysis,{'facts':{}},self.rgba,{},['environment'])
        self.assertTrue(shot['panels']);self.assertEqual(shot['scene_level'],2)
