from pathlib import Path
import sys,unittest

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from product_studio.segmentation.quality import inspect_mask
from product_studio.segmentation.mask_processing import make_rgba,composite_preview


class MaskQualityTests(unittest.TestCase):
    def test_empty_mask_detected(self):
        result=inspect_mask(np.full((64,64,3),255,np.uint8),np.zeros((64,64),np.uint8),(0,0,64,64))
        self.assertEqual(result["automatic_status"],"failed")
        self.assertFalse(result["checks"]["nonempty"])

    def test_outside_roi_instance_is_detected(self):
        alpha=np.zeros((100,200),np.uint8);alpha[10:90,10:90]=255;alpha[10:90,110:190]=255
        result=inspect_mask(np.zeros((100,200,3),np.uint8),alpha,(0,0,100,100))
        self.assertEqual(result["automatic_status"],"failed")
        self.assertIn("foreground_outside_selected_roi",result["warnings"])

    def test_irregular_holes_and_connected_regions_reported_not_filled(self):
        alpha=np.zeros((200,200),np.uint8)
        cv2.fillPoly(alpha,[np.array([[20,20],[140,20],[170,140],[90,160],[20,120]],np.int32)],255)
        cv2.fillPoly(alpha,[np.array([[50,45],[100,40],[110,90],[55,100]],np.int32)],0)
        alpha[170:185,170:185]=255
        result=inspect_mask(np.zeros((200,200,3),np.uint8),alpha,(0,0,200,200))
        self.assertEqual(result["metrics"]["enclosed_background_regions_ge128"],1)
        self.assertEqual(result["metrics"]["components_ge128"],2)
        self.assertEqual(result["automatic_status"],"needs_human_review")
        self.assertEqual(result["human_review_status"],"pending")

    def test_antialiasing_and_known_mask_iou_preserved(self):
        big=np.zeros((400,400),np.uint8);cv2.ellipse(big,(200,200),(130,100),15,0,360,255,-1)
        alpha=cv2.resize(big,(100,100),interpolation=cv2.INTER_AREA)
        self.assertTrue(np.any((alpha>0)&(alpha<255)))
        rgb=np.full((100,100,3),250,np.uint8);rgba=make_rgba(rgb,alpha)
        predicted=rgba[:,:,3]>=128;truth=alpha>=128
        iou=np.count_nonzero(predicted&truth)/np.count_nonzero(predicted|truth)
        self.assertEqual(iou,1.0) # 已知真值只验证映射/导出，不宣称模型准确率。
        result=inspect_mask(rgb,alpha,(0,0,100,100))
        self.assertGreater(result["metrics"]["soft_alpha_pixels"],0)

    def test_dark_and_light_previews_use_straight_alpha(self):
        rgb=np.full((2,2,3),200,np.uint8);alpha=np.array([[0,255],[128,64]],np.uint8)
        dark=composite_preview(rgb,alpha,[0,0,0]);light=composite_preview(rgb,alpha,[255,255,255])
        np.testing.assert_array_equal(dark[0,0],[0,0,0]);np.testing.assert_array_equal(dark[0,1],rgb[0,1])
        np.testing.assert_array_equal(light[0,0],[255,255,255])
        self.assertLess(dark[1,0,0],light[1,0,0])

    def test_halo_transparency_and_parts_are_not_falsely_verified(self):
        alpha=np.zeros((80,80),np.uint8);alpha[10:70,10:70]=240
        result=inspect_mask(np.full((80,80,3),250,np.uint8),alpha,(0,0,80,80),risks=["transparent","reflective"])
        self.assertIn("declared_risk:transparent",result["warnings"])
        self.assertIn("declared_risk:reflective",result["warnings"])
        self.assertTrue(result["not_automatically_verified"])


if __name__=="__main__":unittest.main()
