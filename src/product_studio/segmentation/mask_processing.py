"""坐标映射与原 RGB 保护；不按颜色删除背景、不填孔、不丢弃连通区域。"""

from pathlib import Path

import numpy as np
from PIL import Image


def validate_roi(roi, width, height):
    if len(roi) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in roi):
        raise ValueError("ROI 必须由 x,y,width,height 四个整数组成。")
    x,y,w,h = roi
    if x < 0 or y < 0 or w < 1 or h < 1 or x+w > width or y+h > height:
        raise ValueError("ROI 超出原图；不能自动猜测裁剪范围。")
    return tuple(roi)


def validate_alpha(alpha, shape):
    if not isinstance(alpha, np.ndarray) or alpha.dtype != np.uint8 or alpha.ndim != 2 or alpha.shape != tuple(shape):
        raise ValueError("Alpha 必须是指定坐标系尺寸的 uint8 单通道矩阵。")


def place_roi_alpha(local_alpha, roi, source_size):
    width,height = source_size
    x,y,w,h = validate_roi(roi,width,height)
    validate_alpha(local_alpha,(h,w))
    full = np.zeros((height,width),np.uint8)
    full[y:y+h,x:x+w] = local_alpha
    return full


def import_external_mask(path: Path, *, coordinates, roi, source_size):
    width,height = source_size
    validate_roi(roi,width,height)
    with Image.open(path) as opened:
        if opened.mode in {"1","L"}:
            alpha = np.asarray(opened.convert("L")).copy()
        elif opened.mode == "RGBA":
            alpha = np.asarray(opened.getchannel("A")).copy()
        elif opened.mode == "RGB":
            channels = np.asarray(opened)
            if not np.array_equal(channels[:,:,0],channels[:,:,1]) or not np.array_equal(channels[:,:,0],channels[:,:,2]):
                raise ValueError("RGB 遮罩不是灰度，不能猜测哪个颜色代表前景。")
            alpha = channels[:,:,0].copy()
        else:
            raise ValueError("外部 mask 仅支持 L/1/灰度 RGB/RGBA Alpha，不隐式缩放 16 位或调色板数据。")
    if coordinates == "roi":
        return place_roi_alpha(alpha,roi,source_size)
    if coordinates != "source":
        raise ValueError("必须明确 mask 坐标系 source 或 roi。")
    validate_alpha(alpha,(height,width))
    x,y,w,h = roi
    outside = alpha.copy(); outside[y:y+h,x:x+w] = 0
    if np.any(outside):
        raise ValueError("外部遮罩包含 ROI 外像素，可能来自另一实例；拒绝静默裁剪。")
    return alpha


def make_rgba(rgb,alpha):
    validate_alpha(alpha,rgb.shape[:2])
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("RGB 必须是 uint8 三通道。")
    return np.dstack((rgb,alpha))


def select_by_points(alpha,points):
    """只有明确点选时按连通区选择；多个正点可保留一个商品的多个断开部分。"""
    import cv2
    if not points:return alpha.copy(),{"mode":"all_model_regions_retained"}
    core=(alpha>=128).astype(np.uint8)
    distance,labels=cv2.distanceTransformWithLabels(1-core,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_CCOMP)
    selected=set()
    for point in points:
        if len(point)!=2 or any(not isinstance(value,int) for value in point):raise ValueError("选择点必须为全图整数 x,y。")
        x,y=point
        if not 0<=x<alpha.shape[1] or not 0<=y<alpha.shape[0] or core[y,x]==0:
            raise ValueError("选择点未落在模型的高置信前景，请检查预览并重新选择。")
        selected.add(int(labels[y,x]))
    output=np.where(np.isin(labels,list(selected)),alpha,0).astype(np.uint8)
    return output,{"mode":"explicit_positive_point_component_selection","points_source_px":points,
                   "selected_component_labels":sorted(selected),"soft_edges":"nearest selected core component; original Alpha values retained",
                   "removed_alpha_pixels":int(np.count_nonzero((alpha>0)&(output==0)))}


def composite_preview(rgb,alpha,background):
    a = alpha.astype(np.float32)[:,:,None]/255
    bg = np.asarray(background,dtype=np.float32)
    return np.rint(rgb*a+bg*(1-a)).clip(0,255).astype(np.uint8)


def make_previews(rgb,alpha):
    height,width = alpha.shape
    yy,xx = np.indices((height,width))
    pattern = np.where(((xx//24+yy//24)%2)==0,210,160).astype(np.uint8)
    checker = np.repeat(pattern[:,:,None],3,axis=2)
    # 叠加图保留 RGB；半透明青色仅用于预览，不写入 product_rgba。
    tint = np.full_like(rgb,(30,210,120))
    overlay = np.rint(rgb*.72 + tint*.28*(alpha[:,:,None]/255) + rgb*.28*(1-alpha[:,:,None]/255)).clip(0,255).astype(np.uint8)
    return {"mask_overlay.png":overlay,
            "checkerboard_preview.png":composite_preview(rgb,alpha,checker),
            "dark_background_preview.png":composite_preview(rgb,alpha,[24,24,24]),
            "light_background_preview.png":composite_preview(rgb,alpha,[245,245,245])}
