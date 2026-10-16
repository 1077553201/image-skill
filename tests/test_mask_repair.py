import unittest
import tempfile,json
from pathlib import Path
import numpy as np
from PIL import Image

from product_studio.segmentation.repair import local_repair
from product_studio.segmentation.repair import repair_asset
from product_studio.segmentation.pipeline import segment,load_result
from product_studio.segmentation.base import MaskPrediction


class LocalRepairTests(unittest.TestCase):
    def setUp(self):
        self.rgb=np.full((60,80,3),248,np.uint8)
        self.rgb[10:50,10:70]=(15,15,20)
        self.rgb[22:38,30:50]=248
        self.before=np.full((60,80),255,np.uint8)
        self.roi=(10,10,60,40)
        self.edit=np.zeros((60,80),np.uint8);self.edit[20:40,28:52]=255
        self.fg=np.zeros_like(self.edit);self.fg[10:50,10:70]=255;self.fg[self.edit>0]=0
        self.bg=np.zeros_like(self.edit);self.bg[24:36,32:48]=255

    def repair(self,**kw):
        return local_repair(self.rgb,self.before,self.roi,editable=self.edit,foreground=self.fg,background=self.bg,**kw)

    def test_roi_outside_unchanged(self):
        after,_,_=self.repair();outside=np.ones_like(after,bool);outside[10:50,10:70]=False
        self.assertTrue(np.array_equal(after[outside],self.before[outside]))

    def test_protection_keeps_dark_inner_wall(self):
        after,_,_=self.repair();self.assertTrue(np.array_equal(after[self.fg>0],self.before[self.fg>0]))
        self.assertEqual(after[22,26],255)

    def test_background_and_trimap(self):
        after,tri,meta=self.repair();self.assertTrue(np.all(after[self.bg>0]==0))
        self.assertTrue(np.all(tri[self.bg>0]==0));self.assertTrue(np.all(tri[self.fg>0]==255))
        self.assertEqual(meta['human_review'],'pending')

    def test_same_point_conflict(self):
        with self.assertRaises(ValueError):self.repair(foreground_points=[(35,30)],background_points=[(35,30)])

    def test_outside_point_rejected(self):
        with self.assertRaises(ValueError):self.repair(background_points=[(0,0)])

    def test_white_product_highlight_protected(self):
        self.rgb[10:50,10:70]=250
        after,_,_=self.repair();self.assertTrue(np.all(after[self.fg>0]==255))

    def test_unknown_no_seeds_rejected(self):
        with self.assertRaises(ValueError):local_repair(self.rgb,self.before,self.roi)

    def test_external_only_local(self):
        external=np.zeros_like(self.before);after,_,_=self.repair(external=external)
        self.assertTrue(np.all(after[self.edit==0]==255))

    def test_second_provider_local_mapping(self):
        class Provider:
            def predict(self,rgb):
                class Result:pass
                result=Result();result.alpha=np.zeros(rgb.shape[:2],np.uint8);return result
        after,_,meta=self.repair(provider=Provider())
        self.assertTrue(meta['second_model_used']);self.assertEqual(after[30,40],0)
        self.assertEqual(after[0,0],255)

    def test_foreground_soft_alpha_not_fabricated(self):
        self.before[self.fg>0]=180
        after,_,_=self.repair();self.assertTrue(np.all(after[self.fg>0]==180))

    def test_mask_size_error(self):
        with self.assertRaises(ValueError):self.repair(external=np.zeros((3,3),np.uint8))

    def test_editable_cannot_cross_instance_roi(self):
        self.edit[0,0]=255
        with self.assertRaises(ValueError):self.repair()

    def test_incomplete_unknown_retains_pending(self):
        _,tri,meta=self.repair();self.assertTrue(np.any(tri==128));self.assertEqual(meta['human_review'],'pending')


class RepairAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]);self.root=Path(self.temp.name)
        self.source=self.root/'source.png';Image.fromarray(np.full((50,100,3),220,np.uint8)).save(self.source)
        class Fixture:
            def predict(self,rgb):return MaskPrediction(np.full(rgb.shape[:2],255,np.uint8),{'provider':'synthetic_test'})
        for label,roi in [('left',(0,0,50,50)),('right',(50,0,50,50))]:
            segment(self.source,roi,label,self.root/label,Fixture())
    def tearDown(self):self.temp.cleanup()
    def test_repair_cannot_touch_other_instance(self):
        with self.assertRaises(ValueError):repair_asset(self.root/'left/segmentation_result.json',(50,0,50,50),self.root/'bad')
    def test_new_version_pending_and_preserved_history(self):
        parent=self.root/'left/segmentation_result.json';prior=json.loads(parent.read_text(encoding='utf-8'))
        edit=np.zeros((50,100),np.uint8);edit[10:20,10:20]=255
        report=repair_asset(parent,(0,0,50,50),self.root/'fixed',editable=edit,external=np.zeros_like(edit),
                            uncertain_regions=[{'status':'requires_physical_confirmation'}])
        _,result=load_result(self.root/'fixed/segmentation_result.json')
        self.assertNotEqual(prior['binding']['mask_version'],result['binding']['mask_version'])
        self.assertEqual(result['human_review']['status'],'pending')
        self.assertEqual(report['uncertain_regions'][0]['status'],'requires_physical_confirmation')
        self.assertEqual(json.loads(parent.read_text(encoding='utf-8')),prior)
        with Image.open(self.root/'fixed/product_rgba.png') as im:self.assertTrue(np.all(np.asarray(im)[:,:,:3]==220))
    def test_changed_source_rejected(self):
        Image.fromarray(np.full((50,100,3),10,np.uint8)).save(self.source)
        with self.assertRaises(ValueError):repair_asset(self.root/'left/segmentation_result.json',(0,0,50,50),self.root/'bad')
    def test_cross_instance_prompt_rejected(self):
        edit=np.zeros((50,100),np.uint8);edit[10,70]=255
        with self.assertRaises(ValueError):repair_asset(self.root/'left/segmentation_result.json',(0,0,50,50),self.root/'bad',editable=edit,external=edit)


if __name__=='__main__':unittest.main()
