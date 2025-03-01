import os
from appendix_comparison import cosine_embedding, euclidean_embedding
import matplotlib.pyplot as plt
from shapely.geometry import Polygon
from skimage.transform import resize
import numpy as np
from toolkits import read_images, read_nan_mask, construct_feature_extractor, deep_features
from feature_filters import channel_mean_image
import cv2
from sklearn.metrics import f1_score, precision_recall_curve

dataset_root = './tgrs_dataset'
events = os.listdir(dataset_root)
prior_paths = [dataset_root + '/' + event + '/pre.tif' for event in events]
detection_paths = [dataset_root + '/' + event + '/post.tif' for event in events]
labels_paths = [dataset_root + '/' + event + '/label.png' for event in events]
prior_bases = ['./prior_base/tgrs_dataset_gmm_prior/' + event + '' for event in events]

#  run time parameters
band_choices = {
    'optic': [3, 2, 1], 'fire': [5, 4, 2], 'veg': [4, 3, 2],
    'l7_optic': [2, 1, 0], 'l7_veg': [3, 2, 1], 'l7_fire': [4, 3, 2],
    'band3': [2, 1, 0]
}
#test_event = ['paradise_fire', 'karymsky_volcano', 'mao_landslide', 'florence_flood', 'co_mudslide']
test_event = ['florence_flood',]
glb_bc = 'fire'
bc_prior = {'aoraki_landslide': 'band3', 'co_mudslide': 'l7_fire'}
bc_predict = {'aoraki_landslide': 'band3', }
sam_encoder = construct_feature_extractor()

optimal_threshold = {
    'CEMB': {'paradise_fire': 0.39, 'karymsky_volcano': 0.34, 'mao_landslide': 0.44, 'florence_flood': 0.41,
             'co_mudslide': 0.40, },
    'EEMB': {'paradise_fire': 0.50, 'karymsky_volcano': 0.43, 'mao_landslide': 0.63, 'florence_flood': 0.60,
             'co_mudslide': 0.59, },
    'Ours': {'paradise_fire': 0.62, 'karymsky_volcano': 0.53, 'mao_landslide': 0.56, 'florence_flood': 0.53,
             'co_mudslide': 0.69, },
}

def track_objects(binary_map, area_threshold=7000):
    pre_objs, _ = cv2.findContours(binary_map, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # filter out bad objects
    selected_pre_objs = []
    f_area = area_threshold
    for pre_obj in pre_objs:
        if pre_obj.shape[0] > 4:
            pre_polygon = Polygon(pre_obj.reshape(-1, 2).tolist())
            if not pre_polygon.is_valid:
                pre_polygon = pre_polygon.buffer(0)
            if pre_polygon.area > f_area:
                selected_pre_objs.append(pre_polygon)
    return selected_pre_objs


for i, detect_path in enumerate(detection_paths):
    event = events[i]
    if event in test_event:
        # Load Image
        prior_bc = bc_prior[event] if event in bc_prior.keys() else glb_bc
        det_bc = bc_predict[event] if event in bc_predict.keys() else glb_bc
        det_image = read_images(detect_path, band_choices[det_bc])
        h, w, _ = det_image.shape
        nan_mask = read_nan_mask(detect_path)
        prior_image = read_images(prior_paths[i], band_choices[prior_bc])
        # Load Label
        label_image = cv2.imread(labels_paths[i], cv2.IMREAD_GRAYSCALE)
        label_bin = np.where(label_image > 0, 1, 0).astype(np.uint8)
        gt_objs, _ = cv2.findContours(label_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Load Prior Base
        center_his = np.load(prior_bases[i] + '/prior_file_ctr.npy')
        std_his = np.load(prior_bases[i] + '/prior_file_var.npy')

        # feature extraction here
        det_feat = deep_features(det_image, sam_encoder, layer=-1)
        det_feat = channel_mean_image(det_feat, near_radius=2)
        pri_feat = deep_features(prior_image, sam_encoder, layer=-1)
        pri_feat = channel_mean_image(pri_feat, near_radius=2)

        # Ours
        det_signal = det_feat.reshape(-1, det_feat.shape[2])
        diminish = np.sum(np.abs(det_signal[:, None, :] - center_his), axis=-1)
        std_his_reshape = std_his.reshape(1, -1)
        weighted_diminish = diminish / std_his_reshape
        sort_simi_var = np.partition(weighted_diminish, 1, axis=1)[:, :1]
        anomaly_scores = np.mean(sort_simi_var, axis=1).reshape(det_feat.shape[0], det_feat.shape[1])
        norm_score = (anomaly_scores - np.mean(anomaly_scores)) / np.sqrt(np.var(anomaly_scores))
        our_anomaly = np.nan_to_num(norm_score, nan=0.)
        final_score = (our_anomaly - np.min(our_anomaly)) / (np.max(our_anomaly) - np.min(our_anomaly))
        our_score = resize(final_score, (h, w), order=1, mode='constant', anti_aliasing=False)
        our_score[nan_mask] = 0.

        t_our = optimal_threshold['Ours'][event]
        start = max(0., t_our-0.2)
        end = min(1., t_our)
        thresholds = np.arange(start, end, 0.02)
        for threshold in thresholds:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6))
            # For Reference
            ax1.imshow(det_image)
            # Showing GT Polygon and Detected Regions
            for j, gt_obj in enumerate(gt_objs):
                gt_polygon = Polygon(gt_obj.reshape(-1, 2).tolist())
                xg, yg = gt_polygon.exterior.xy
                ax2.plot(xg, yg, c='red', linewidth=3)

            our_seg = ((our_score > threshold) * 255).astype(np.uint8)
            our_objs = track_objects(our_seg)
            show_det_image = cv2.imread(r'C:\Users\xujia\Desktop\flr_post.jpg')
            ax2.imshow(det_image)
            for our_obj in our_objs:
                x, y = our_obj.exterior.xy
                ax2.plot(x, y, c='blue', linewidth=3)
                print('-----')
                for gt_obj in gt_objs:
                    gt_polygon2 = Polygon(gt_obj.reshape(-1, 2).tolist())
                    print(gt_polygon2.intersection(our_obj).area / (
                            our_obj.area + gt_polygon2.area - gt_polygon2.intersection(our_obj).area))
            info = 'best: ' + str(t_our) + ' current: ' + str(threshold)
            plt.title(info)
            plt.show()
