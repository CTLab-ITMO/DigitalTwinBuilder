from model.model import PretrainedFeatureExtractor, ED, Discriminator
import logging
from typing import List, Optional, Union
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from torchvision import transforms
from scipy.ndimage import gaussian_filter

from detection import (
    ImageData,
    AnomalyDetector,
    AnomalyDetectionResult,
)

import sys
import os
_CKAAD_DIR = os.path.join(os.path.dirname(__file__), 'models', 'CKAAD')
if _CKAAD_DIR not in sys.path:
    sys.path.insert(0, _CKAAD_DIR)


logger = logging.getLogger(__name__)

ImageInput = Union[ImageData, np.ndarray, Image.Image, List[np.ndarray]]


def _extract_image_array(data: ImageInput) -> np.ndarray:
    if isinstance(data, ImageData):
        return data.values
    if isinstance(data, Image.Image):
        return np.array(data)
    if isinstance(data, list):
        if len(data) == 0:
            return np.array([])
        return np.array(data)
    if isinstance(data, np.ndarray):
        return data
    raise ValueError(f"Unsupported image data type: {type(data)}")


def _prepare_ckaad_images(normal_data):
    import numpy as np
    from .ckaad_detector import ImageData
    if isinstance(normal_data, list):
        if isinstance(normal_data[0], ImageData):
            images = [sd.values for sd in normal_data]
        else:
            images = normal_data
    elif isinstance(normal_data, ImageData):
        images = [normal_data.get_image(i) for i in range(normal_data.n_images)]
    elif isinstance(normal_data, np.ndarray):
        if normal_data.ndim == 4:
            images = [normal_data[i] for i in range(normal_data.shape[0])]
        else:
            images = [normal_data]
    else:
        images = [normal_data]
    return images


def _run_ckaad_training_loop(model, images, batch_size, ae_optimizer, d_optimizer,
                             true_label, fake_label):
    import numpy as np
    import torch
    from alive_progress import alive_bar
    n_batches = max(1, len(images) // batch_size)

    with alive_bar(model.epochs, title='CKAAD', bar='smooth', spinner='dots_waves') as pbar:
        for epoch in range(model.epochs):
            model.ae.train()
            model.discriminator.train()
            indices = np.random.permutation(len(images))

            for b in range(n_batches):
                batch_idx = indices[b * batch_size:(b + 1) * batch_size]
                batch_images = [images[i] for i in batch_idx]
                batch_tensor = model._batch_tensor_from_np(batch_images)

                with torch.no_grad():
                    features = model.pfe(batch_tensor)

                outputs = model.ae(features)
                recon_loss = model._cosine_loss(features, outputs)

                ae_optimizer.zero_grad()
                recon_loss.backward()
                torch.nn.utils.clip_grad_norm_(model.ae.parameters(), 1.0)
                ae_optimizer.step()

                if (epoch + 1) % 5 == 0:
                    features_detach = [f.detach() for f in features]
                    outputs_detach = [o.detach() for o in outputs]
                    dis_loss = (model.discriminator.calculate_loss(features_detach, true_label) +
                                model.discriminator.calculate_loss(outputs_detach, fake_label))
                    d_optimizer.zero_grad()
                    dis_loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.discriminator.parameters(), 1.0)
                    d_optimizer.step()

                del batch_tensor, features, outputs

            pbar()


def _calibrate_ckaad_threshold(model, images, batch_size):
    import numpy as np
    import torch
    baseline_scores = []
    with torch.no_grad():
        for i in range(0, len(images), batch_size):
            batch = images[i:i + batch_size]
            batch_tensor = model._batch_tensor_from_np(batch)
            features = model.pfe(batch_tensor)
            reconstructions = model.ae(features)
            scores = model._compute_anomaly_scores(features, reconstructions)
            baseline_scores.extend(scores)

    if baseline_scores:
        baseline_mean = np.mean(baseline_scores)
        baseline_std = np.std(baseline_scores)
        model.threshold = np.percentile(baseline_scores, 95)
        logger.info(f"CKAAD calibrated threshold: {model.threshold:.4f} "
                    f"(baseline mean={baseline_mean:.4f}, std={baseline_std:.4f}, "
                    f"95th percentile={np.percentile(baseline_scores, 95):.4f})")


class CKAADAnomalyDetector(AnomalyDetector):

    def __init__(self, detector_id: str = "ckaad",
                 backbone: str = "wide_resnet50_2",
                 layers: List[int] = None,
                 image_size: int = 256,
                 threshold: float = 0.5,
                 topk: int = 100,
                 sigma: int = 4,
                 epochs: int = 20,
                 lr: float = 5e-3,
                 d_lr: float = 1e-4,
                 adv_conf: float = 0.02,
                 device: str = None):
        super().__init__(detector_id, threshold)
        self.backbone = backbone
        self.layers = layers if layers is not None else [1, 2, 3]
        self.image_size = image_size
        self.topk = topk
        self.sigma = sigma
        self.epochs = epochs
        self.lr = lr
        self.d_lr = d_lr
        self.adv_conf = adv_conf
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')

        self.pfe: Optional[PretrainedFeatureExtractor] = None
        self.ae: Optional[ED] = None
        self.discriminator = None
        self.feature_stats = {}

        self.img_transform = transforms.Compose([
            transforms.Resize((self.image_size, self.image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225))
        ])

    def _pil_from_np(self, arr: np.ndarray) -> Image.Image:
        if arr.dtype != np.uint8:
            if arr.max() <= 1.0:
                arr = (arr * 255).astype(np.uint8)
            else:
                arr = arr.astype(np.uint8)
        return Image.fromarray(arr).convert("RGB")

    def _tensor_from_np(self, arr: np.ndarray) -> torch.Tensor:
        pil = self._pil_from_np(arr)
        return self.img_transform(pil).unsqueeze(0).to(self.device)

    def _batch_tensor_from_np(self, images: List[np.ndarray]) -> torch.Tensor:
        tensors = [self.img_transform(self._pil_from_np(img)) for img in images]
        return torch.stack(tensors).to(self.device)

    def fit(self, normal_data: Union[List[ImageData], ImageData, np.ndarray,
                                     List[np.ndarray]], progress_callback=None) -> bool:
        try:
            images = _prepare_ckaad_images(normal_data)
            if len(images) == 0:
                logger.error("No images to train on")
                return False

            max_images = 100
            if len(images) > max_images:
                indices = np.random.choice(len(images), max_images, replace=False)
                images = [images[i] for i in indices]

            device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            self.device = device
            logger.info(f"CKAAD running on {device} ({self.backbone})")

            self.pfe = PretrainedFeatureExtractor(
                backbone=self.backbone,
                layers=self.layers,
                image_size=self.image_size
            ).to(device)
            self.pfe.eval()
            for param in self.pfe.parameters():
                param.requires_grad_(False)

            self.ae = ED(
                backbone=self.backbone,
                input_channels=self.pfe.output_channels
            ).to(device)

            self.discriminator = Discriminator(
                input_sizes=self.pfe.output_sizes,
                input_channels=self.pfe.output_channels,
                expansion=self.pfe.expansion
            ).to(device)

            ae_optimizer = torch.optim.Adam(self.ae.parameters(), lr=self.lr, betas=(0.5, 0.999))
            d_optimizer = torch.optim.Adam(self.discriminator.parameters(), lr=self.d_lr, betas=(0.5, 0.999))

            true_label = 0
            fake_label = 1
            batch_size = min(16, len(images))

            logger.info(f"Training CKAAD on {len(images)} images, "
                        f"backbone={self.backbone}, layers={self.layers}, "
                        f"epochs={self.epochs}, device={self.device}")

            _run_ckaad_training_loop(self, images, batch_size, ae_optimizer, d_optimizer,
                                     true_label, fake_label)
            self.ae.eval()

            _calibrate_ckaad_threshold(self, images, batch_size)
            self.is_trained = True
            return True

        except Exception as e:
            logger.error(f"Error training CKAAD: {str(e)}", exc_info=True)
            return False

    def _cosine_loss(self, features: List[torch.Tensor],
                     reconstructions: List[torch.Tensor]) -> torch.Tensor:
        loss = 0.0
        for feat, recon in zip(features, reconstructions):
            feat_flat = feat.view(feat.shape[0], -1)
            recon_flat = recon.view(recon.shape[0], -1)
            cos_sim = F.cosine_similarity(feat_flat, recon_flat, dim=1)
            loss += torch.mean(1 - cos_sim)
        return loss / len(features)

    def _compute_anomaly_map(self, features: List[torch.Tensor],
                             reconstructions: List[torch.Tensor]) -> np.ndarray:
        batch_size = features[0].size(0)
        out_size = self.image_size

        anomaly_map = np.zeros((batch_size, 1, out_size, out_size), dtype=np.float32)

        for feat, recon in zip(features, reconstructions):
            cos_sim = F.cosine_similarity(
                feat, recon, dim=1
            )
            a_map = 1 - cos_sim
            a_map = a_map.unsqueeze(1)
            a_map = F.interpolate(a_map, size=out_size, mode='bilinear', align_corners=True)
            anomaly_map += a_map.cpu().numpy()

        anomaly_map = anomaly_map.mean(axis=0)
        anomaly_map = anomaly_map.squeeze(0)

        anomaly_map = gaussian_filter(anomaly_map, sigma=self.sigma)

        return anomaly_map

    def _compute_anomaly_scores(self, features: List[torch.Tensor],
                                reconstructions: List[torch.Tensor]) -> List[float]:
        anomaly_map = self._compute_anomaly_map(features, reconstructions)
        flat_map = anomaly_map.reshape(-1)
        topk = min(self.topk, len(flat_map))
        topk_values = np.sort(flat_map)[-topk:]
        score = float(np.mean(topk_values))
        return [score]

    def detect(self, data: ImageInput) -> AnomalyDetectionResult:
        if not self.is_trained or self.pfe is None or self.ae is None:
            return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)

        try:
            img = _extract_image_array(data)
            if img.ndim == 4:
                img = img[0]

            img_tensor = self._tensor_from_np(img)

            with torch.no_grad():
                features = self.pfe(img_tensor)
                reconstructions = self.ae(features)

                anomaly_map = self._compute_anomaly_map(features, reconstructions)

                amap_min = anomaly_map.min()
                amap_max = anomaly_map.max()
                if amap_max > amap_min:
                    anomaly_map_norm = (anomaly_map - amap_min) / (amap_max - amap_min)
                else:
                    anomaly_map_norm = np.zeros_like(anomaly_map)

                flat_map = anomaly_map.reshape(-1)
                topk = min(self.topk, len(flat_map))
                topk_values = np.sort(flat_map)[-topk:]
                anomaly_score = float(np.mean(topk_values))

                anomaly_score = min(anomaly_score, 1.0)

                is_anomaly = anomaly_score > self.threshold

                return AnomalyDetectionResult(
                    is_anomaly=is_anomaly,
                    anomaly_score=anomaly_score,
                    anomaly_type="ckaad_feature_deviation" if is_anomaly else None,
                    details={
                        "anomaly_map": anomaly_map_norm,
                        "anomaly_map_raw": anomaly_map,
                        "mean_score": float(np.mean(anomaly_map)),
                        "max_score": float(np.max(anomaly_map)),
                        "topk_score": anomaly_score
                    }
                )

        except Exception as e:
            logger.error(f"Error during CKAAD detection: {str(e)}", exc_info=True)
            return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)

    def detect_batch(self, images: List[np.ndarray]) -> List[AnomalyDetectionResult]:
        if not self.is_trained or self.pfe is None or self.ae is None:
            return [AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)
                    for _ in images]

        try:
            batch_tensor = self._batch_tensor_from_np(images)
            batch_size = batch_tensor.size(0)

            with torch.no_grad():
                features = self.pfe(batch_tensor)
                reconstructions = self.ae(features)

                all_anomaly_maps = []

                for b in range(batch_size):
                    batch_features = [f[b:b+1] for f in features]
                    batch_recons = [r[b:b+1] for r in reconstructions]
                    amap = self._compute_anomaly_map(batch_features, batch_recons)
                    all_anomaly_maps.append(amap)

            results = []
            for i in range(batch_size):
                anomaly_map = all_anomaly_maps[i]

                amap_min = anomaly_map.min()
                amap_max = anomaly_map.max()
                if amap_max > amap_min:
                    anomaly_map_norm = (anomaly_map - amap_min) / (amap_max - amap_min)
                else:
                    anomaly_map_norm = np.zeros_like(anomaly_map)

                flat_map = anomaly_map.reshape(-1)
                topk = min(self.topk, len(flat_map))
                topk_values = np.sort(flat_map)[-topk:]
                anomaly_score = min(float(np.mean(topk_values)), 1.0)
                is_anomaly = anomaly_score > self.threshold

                results.append(AnomalyDetectionResult(
                    is_anomaly=is_anomaly,
                    anomaly_score=anomaly_score,
                    anomaly_type="ckaad_feature_deviation" if is_anomaly else None,
                    details={
                        "anomaly_map": anomaly_map_norm,
                        "anomaly_map_raw": anomaly_map,
                        "mean_score": float(np.mean(anomaly_map)),
                        "max_score": float(np.max(anomaly_map)),
                        "topk_score": anomaly_score
                    }
                ))

            return results

        except Exception as e:
            logger.error(f"Error during CKAAD batch detection: {str(e)}", exc_info=True)
            return [AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)
                    for _ in images]

    def update(self, data: ImageInput, is_normal: bool = True) -> None:
        pass


class AnomalyCLIPDetector(AnomalyDetector):

    def __init__(self, detector_id: str = "anomalyclip",
                 checkpoint_path: Optional[str] = None,
                 image_size: int = 518,
                 features_list: List[int] = None,
                 feature_map_layer: List[int] = None,
                 n_ctx: int = 12,
                 depth: int = 9,
                 t_n_ctx: int = 4,
                 sigma: int = 4,
                 threshold: float = 0.5,
                 device: str = None):
        super().__init__(detector_id, threshold)
        self.checkpoint_path = checkpoint_path
        self.image_size = image_size
        self.features_list = features_list or [6, 12, 18, 24]
        self.feature_map_layer = feature_map_layer or [0, 1, 2, 3]
        self.n_ctx = n_ctx
        self.depth = depth
        self.t_n_ctx = t_n_ctx
        self.sigma = sigma
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')

        self.model = None
        self.prompt_learner = None
        self.text_features = None
        self.preprocess = None

        if self.checkpoint_path is None:
            possible_paths = [
                os.path.join(os.path.dirname(__file__), 'models', 'AnomalyCLIP', 'checkpoints',
                             '9_12_4_multiscale', 'epoch_15.pth'),
                os.path.join(os.path.dirname(__file__), 'models', 'AnomalyCLIP', 'checkpoints',
                             '9_12_4_multiscale_visa', 'epoch_15.pth'),
            ]
            for p in possible_paths:
                if os.path.exists(p):
                    self.checkpoint_path = p
                    break
            if self.checkpoint_path is None:
                self.checkpoint_path = possible_paths[0]
                logger.warning(f"Checkpoint not found at default paths, using: {self.checkpoint_path}")

    def _setup_model(self):
        anomalyclip_dir = os.path.join(os.path.dirname(__file__), 'models', 'AnomalyCLIP')
        if anomalyclip_dir not in sys.path:
            sys.path.insert(0, anomalyclip_dir)

        import AnomalyCLIP_lib
        from prompt_ensemble import AnomalyCLIP_PromptLearner

        class Args:
            def __init__(self, image_size, n_ctx, depth, t_n_ctx):
                self.image_size = image_size
                self.n_ctx = n_ctx
                self.depth = depth
                self.t_n_ctx = t_n_ctx

        design_details = {
            "Prompt_length": self.n_ctx,
            "learnabel_text_embedding_depth": self.depth,
            "learnabel_text_embedding_length": self.t_n_ctx
        }

        self.model, self.preprocess = AnomalyCLIP_lib.load(
            "ViT-L/14@336px", device=self.device, design_details=design_details
        )
        self.model.eval()

        self.model.visual.DAPM_replace(DPAM_layer=20)

        self.prompt_learner = AnomalyCLIP_PromptLearner(self.model.to("cpu"), design_details)

        if os.path.exists(self.checkpoint_path):
            checkpoint = torch.load(self.checkpoint_path, map_location=self.device)
            if "prompt_learner" in checkpoint:
                self.prompt_learner.load_state_dict(checkpoint["prompt_learner"])
            else:
                self.prompt_learner.load_state_dict(checkpoint)
            logger.info(f"Loaded AnomalyCLIP checkpoint from {self.checkpoint_path}")
        else:
            logger.warning(f"Checkpoint not found at {self.checkpoint_path}, using zero-shot prompts")

        self.prompt_learner.to(self.device)
        self.model.to(self.device)

        with torch.no_grad():
            prompts, tokenized_prompts, compound_prompts_text = self.prompt_learner(cls_id=None)
            text_features = self.model.encode_text_learn(
                prompts, tokenized_prompts, compound_prompts_text
            ).float()
            text_features = torch.stack(
                torch.chunk(text_features, dim=0, chunks=2), dim=1
            )
            self.text_features = text_features / text_features.norm(dim=-1, keepdim=True)

        logger.info(f"AnomalyCLIP text features computed, shape: {self.text_features.shape}")

    def _pil_from_np(self, arr: np.ndarray) -> Image.Image:
        if arr.dtype != np.uint8:
            if arr.max() <= 1.0:
                arr = (arr * 255).astype(np.uint8)
            else:
                arr = arr.astype(np.uint8)
        return Image.fromarray(arr).convert("RGB")

    def _preprocess_image(self, arr: np.ndarray) -> torch.Tensor:
        pil = self._pil_from_np(arr)
        return self.preprocess(pil)

    def fit(self, normal_data: Union[List[ImageData], ImageData, np.ndarray, List[np.ndarray]]) -> bool:
        try:
            self._setup_model()
            self.is_trained = True
            logger.info("AnomalyCLIP initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Error initializing AnomalyCLIP: {str(e)}", exc_info=True)
            return False

    def _compute_anomaly_map(self, image_tensor: torch.Tensor) -> torch.Tensor:
        import AnomalyCLIP_lib

        with torch.no_grad():
            image_features, patch_features = self.model.encode_image(
                image_tensor, self.features_list, DPAM_layer=20
            )
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

            text_probs = image_features @ self.text_features.permute(0, 2, 1)
            text_probs = (text_probs / 0.07).softmax(-1)
            image_score = text_probs[:, 0, 1].item()

            anomaly_map_list = []
            for idx, patch_feature in enumerate(patch_features):
                if idx >= self.feature_map_layer[0]:
                    patch_feature = patch_feature / patch_feature.norm(dim=-1, keepdim=True)
                    similarity, _ = AnomalyCLIP_lib.compute_similarity(
                        patch_feature, self.text_features[0]
                    )
                    similarity_map = AnomalyCLIP_lib.get_similarity_map(
                        similarity[:, 1:, :], self.image_size
                    )
                    anomaly_map = (similarity_map[..., 1] + 1 - similarity_map[..., 0]) / 2.0
                    anomaly_map_list.append(anomaly_map)

            anomaly_map = torch.stack(anomaly_map_list)
            anomaly_map = anomaly_map.sum(dim=0)

            anomaly_map = torch.stack([
                torch.from_numpy(gaussian_filter(i.cpu().numpy(), sigma=self.sigma))
                for i in anomaly_map
            ], dim=0)

            return anomaly_map[0], image_score

    def detect(self, data: ImageInput) -> AnomalyDetectionResult:
        if not self.is_trained or self.model is None:
            return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)

        try:
            img = _extract_image_array(data)
            if img.ndim == 4:
                img = img[0]

            img_tensor = self._preprocess_image(img).unsqueeze(0).to(self.device)

            anomaly_map, image_score = self._compute_anomaly_map(img_tensor)

            amap_np = anomaly_map.cpu().numpy()
            amap_min = amap_np.min()
            amap_max = amap_np.max()
            if amap_max > amap_min:
                anomaly_map_norm = (amap_np - amap_min) / (amap_max - amap_min)
            else:
                anomaly_map_norm = np.zeros_like(amap_np)

            anomaly_score = float(image_score)
            anomaly_score = min(max(anomaly_score, 0.0), 1.0)
            is_anomaly = anomaly_score > self.threshold

            return AnomalyDetectionResult(
                is_anomaly=is_anomaly,
                anomaly_score=anomaly_score,
                anomaly_type="anomalyclip_vl_similarity" if is_anomaly else None,
                details={
                    "anomaly_map": anomaly_map_norm,
                    "anomaly_map_raw": amap_np,
                    "mean_score": float(np.mean(amap_np)),
                    "max_score": float(np.max(amap_np)),
                    "image_score": anomaly_score
                }
            )

        except Exception as e:
            logger.error(f"Error during AnomalyCLIP detection: {str(e)}", exc_info=True)
            return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)

    def detect_batch(self, images: List[np.ndarray]) -> List[AnomalyDetectionResult]:
        return [self.detect(img) for img in images]

    def update(self, data: ImageInput, is_normal: bool = True) -> None:
        pass
