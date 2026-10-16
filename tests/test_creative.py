from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from product_studio.core.asset_binding import file_sha256
from product_studio.creative.planning import validate_facts, platform_check
from product_studio.generation.marketing_renderer import validate_copy, draw_typography, photo_detail
from product_studio.references.analysis import validate_analysis, DIMENSIONS


def fact(value, status='human_verified'):
    return {'value':value,'status':status,'sources':['source_test'],'method':'test_user_statement','reviewer':'Test Reviewer'}


class CreativeTests(unittest.TestCase):
    def setUp(self):
        self.binding={'source_id':'source_test','source_sha256':'a'*64,'instance_id':'object_1','mask_version':'b'*64}
        self.facts={'binding':self.binding,'facts':{'width_cm':fact(30),'mass_g':fact(500)},
                    'provenance':{'width_cm':{'kind':'user'},'mass_g':{'kind':'user'}}}
        self.style={'copy_vocabulary':['Diameter','cm','Weight','g','Hello','Apple'],
                    'excluded_copy_tokens':['Apple'],'palette':{'ink':'#152736','white':'#ffffff'},
                    'font_regular':'C:/Windows/Fonts/arial.ttf','font_bold':'C:/Windows/Fonts/arialbd.ttf','safe_margin_px':20}
        self.node={'text':'Diameter 30 cm','x':30,'y':30,'size':24,'color':'ink','fact_ids':['width_cm']}

    def test_source_bound_facts(self):
        validate_facts(self.facts,self.binding)
        bad=deepcopy(self.facts);bad['binding']['instance_id']='object_2'
        with self.assertRaises(ValueError):validate_facts(bad,self.binding)

    def test_unknown_not_default(self):
        self.facts['facts']['thickness_mm']={'value':None,'status':'unknown','sources':[],'method':None}
        validate_facts(self.facts,self.binding)
        self.facts['facts']['thickness_mm']['value']=1
        with self.assertRaises(ValueError):validate_facts(self.facts,self.binding)

    def test_estimated_claim_not_accepted(self):
        self.facts['facts']['width_cm']['status']='estimated'
        with self.assertRaises(ValueError):validate_facts(self.facts,self.binding)

    def test_fact_requires_provenance(self):
        self.facts['provenance']={}
        with self.assertRaises(ValueError):validate_facts(self.facts,self.binding)

    def test_matching_quantity(self):
        self.assertTrue(validate_copy(self.node,self.style,self.facts)['numeric_claims_source_checked'])

    def test_fabricated_quantity_rejected(self):
        self.node['text']='Diameter 31 cm'
        with self.assertRaises(ValueError):validate_copy(self.node,self.style,self.facts)

    def test_wrong_units_rejected(self):
        self.node['text']='Weight 500 cm';self.node['fact_ids']=['mass_g']
        with self.assertRaises(ValueError):validate_copy(self.node,self.style,self.facts)

    def test_copy_vocabulary_error(self):
        self.node['text']='Diametre 30 cm'
        with self.assertRaises(ValueError):validate_copy(self.node,self.style,self.facts)

    def test_competitor_token_excluded(self):
        self.node['text']='Apple'
        with self.assertRaises(ValueError):validate_copy(self.node,self.style,self.facts)

    def _draw(self,canvas):
        if not Path(self.style['font_regular']).exists():self.skipTest('Local Arial unavailable')
        return draw_typography(canvas,[self.node],self.style,self.facts)

    def test_text_safe_and_readable(self):
        checks=self._draw(Image.new('RGB',(500,300),'white'))
        self.assertGreater(checks[0]['minimum_glyph_contrast'],4.5)
        self.assertTrue(checks[0]['inside_safe_area'])

    def test_text_overflow_rejected(self):
        self.node['x']=450
        with self.assertRaises(ValueError):self._draw(Image.new('RGB',(500,300),'white'))

    def test_multiline_heading(self):
        self.node['text']='Hello\nHello'
        checks=self._draw(Image.new('RGB',(500,300),'white'))
        self.assertGreater(checks[0]['bbox'][3]-checks[0]['bbox'][1],40)

    def test_text_low_contrast_rejected(self):
        self.node['color']='white'
        with self.assertRaises(ValueError):self._draw(Image.new('RGB',(500,300),'white'))

    def test_product_protection(self):
        if not Path(self.style['font_regular']).exists():self.skipTest('Local Arial unavailable')
        with self.assertRaises(ValueError):
            draw_typography(Image.new('RGB',(500,300),'white'),[self.node],self.style,self.facts,np.full((300,500),255,np.uint8))

    def test_detail_is_source_rgb(self):
        rgba=np.zeros((100,120,4),np.uint8);rgba[:,:,:3]=[1,80,200];rgba[:,:,3]=255
        detail,record=photo_detail(rgba,[10,20,30,40],[30,40])
        np.testing.assert_array_equal(np.asarray(detail),rgba[20:60,10:40])
        self.assertTrue(record['real_detail_not_AI'])

    def test_detail_resolution_limited(self):
        rgba=np.full((100,120,4),255,np.uint8)
        tile,record=photo_detail(rgba,[0,0,30,40],[600,800])
        self.assertLessEqual(record['interpolation_scale'],1.6)
        self.assertTrue(record['resolution_limited'])

    def test_crop_outside_source(self):
        with self.assertRaises(ValueError):photo_detail(np.zeros((100,100,4),np.uint8),[99,99,30,30],[50,50])

    def test_ebay_text_not_listing_safe(self):
        report=platform_check({'id':'ebay'},{'role':'features','text':[{'text':'Hello'}]},occupancy=.8)
        self.assertTrue(report['technical_failures']);self.assertFalse(report['platform_approved'])

    def test_main_marketing_separation(self):
        report=platform_check({'id':'amazon','main_min_longest_axis_fill':.85},{'role':'white_hero','text':[],'background_id':None},occupancy=.86)
        self.assertEqual(report['technical_failures'],[])
        self.assertTrue(report['category_and_site_review_required'])

    def test_agent_analysis_hashes_and_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'ref.png';Image.new('RGB',(100,100),'white').save(path)
            asset={'asset_id':'ref_01','path':str(path),'sha256':file_sha256(path)}
            analysis={'provider':'image_capable_agent','separate_vlm_api_called':False,
                      'images':[{'asset_id':'ref_01','sha256':asset['sha256'],'image_read_tool':'view_image','dimensions':{k:'Actual image observation' for k in DIMENSIONS}}],
                      'summary':{k:'Set observation' for k in DIMENSIONS},'transferable':['general spacing'],'excluded':['competitor logo']}
            validate_analysis({'assets':[asset]},analysis)
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):validate_analysis({'assets':[asset]},analysis)

    def test_no_fake_api_success(self):
        with self.assertRaises(ValueError):validate_analysis({'assets':[]},{'provider':'unrun_vlm_api','separate_vlm_api_called':True})
