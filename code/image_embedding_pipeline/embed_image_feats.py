#!/usr/bin/env python3
"""Create one image embedding per source image/volume.

The command is deliberately idempotent: an output is reused only when the
manifest says that its model and preprocessing version match the current run.
It never writes inside ``source_root``.

The default encoder mapping is:
    CR/DX -> google/medsiglip-448
    MG    -> Mammo-FM (Batmanlab checkpoint)
    CT    -> CT-FM
    MR    -> MARS

RAD-DINO is selected with ``--encoder-set rad_dino`` and is intended only for
the separate CR/DX comparison set.  CT-CLIP is selected with
``--encoder-set ct_clip`` and writes a separate CT output set.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib
import os
import sys
import tempfile
import types
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


CODE_VERSION = "image-embeddings-v2"
PREPROCESSING = {
    "medsiglip": "medsiglip_processor_rgb_448_v1",
    "rad_dino": "rad_dino_image_processor_cls_v1",
    "mammo_fm": "mammo_fm_resize_1520x912_gray3_norm_v1",
    "ct_fm": "ctfm_spl_spacing_3x1x1_crop_scale_sliding_window_v1",
    "mars": "mars_ras_nonzero_norm_center_crop_96_v1",
    "ct_clip": "ctclip_nii_spacing_1p5x0p75x0p75_center_crop_240x480x480_v1",
}

DEFAULT_MODELS = {
    "CR": "medsiglip",
    "DX": "medsiglip",
    "MG": "mammo_fm",
    "CT": "ct_fm",
    "MR": "mars",
}
RAD_MODELS = {"CR": "rad_dino", "DX": "rad_dino"}
CT_CLIP_MODELS = {"CT": "ct_clip"}

MANIFEST_COLUMNS = [
    "source_relative_path",
    "output_relative_path",
    "modality",
    "model_id",
    "model_revision",
    "preprocessing_version",
    "embedding_dim",
    "dtype",
    "normalized",
    "source_size",
    "source_mtime",
    "status",
    "error_type",
    "created_at",
    "code_version",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def _move_batch_to_device(batch: Mapping[str, Any], device: torch.device) -> dict[str, Any]:
    return {
        key: value.to(device) if hasattr(value, "to") else value
        for key, value in batch.items()
    }


def _autocast(device: torch.device, enabled: bool):
    if device.type == "cuda":
        return torch.autocast(device_type="cuda", dtype=torch.float16, enabled=enabled)
    return torch.autocast(device_type="cpu", dtype=torch.bfloat16, enabled=False)


def _ensure_vector(value: Any) -> torch.Tensor:
    """Return a finite, one-dimensional float32 tensor."""
    if isinstance(value, (tuple, list)):
        value = value[0]
    if hasattr(value, "pooler_output"):
        value = value.pooler_output
    if hasattr(value, "last_hidden_state"):
        value = value.last_hidden_state[:, 0]
    if not isinstance(value, torch.Tensor):
        value = torch.as_tensor(value)
    value = value.detach().float().cpu()
    if value.ndim == 2 and value.shape[0] == 1:
        value = value[0]
    if value.ndim != 1:
        raise ValueError(f"encoder returned shape {tuple(value.shape)}, expected one vector")
    if not torch.isfinite(value).all():
        raise ValueError("encoder returned NaN or Inf")
    return value.contiguous()


class Encoder:
    model_id: str
    model_revision: str
    preprocessing_key: str

    def __init__(self, device: torch.device, amp: bool) -> None:
        self.device = device
        self.amp = amp

    def encode(self, path: Path) -> torch.Tensor:
        raise NotImplementedError


class HFImageEncoder(Encoder):
    def __init__(
        self,
        kind: str,
        model_id: str,
        load_id: str | Path,
        cache_dir: Path,
        device: torch.device,
        amp: bool,
    ) -> None:
        super().__init__(device, amp)
        from transformers import AutoImageProcessor, AutoModel, AutoProcessor

        self.model_id = model_id
        self.model_revision = "main"
        self.preprocessing_key = PREPROCESSING[kind]
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        model_kwargs: dict[str, Any] = {}
        if device.type == "cuda" and amp:
            # Loading MedSigLIP in fp32 needs more than the free VRAM available
            # on the shared GPU.  The final saved vector is converted back to
            # float32 by _ensure_vector.
            model_kwargs["torch_dtype"] = torch.float16
        if kind == "medsiglip":
            self.processor = AutoProcessor.from_pretrained(
                str(load_id),
                cache_dir=str(cache_dir),
                local_files_only=True,
                token=token,
            )
        else:
            self.processor = AutoImageProcessor.from_pretrained(
                str(load_id),
                cache_dir=str(cache_dir),
                local_files_only=True,
                token=token,
            )
        self.model = AutoModel.from_pretrained(
            str(load_id),
            cache_dir=str(cache_dir),
            local_files_only=True,
            token=token,
            **model_kwargs,
        ).to(device).eval()
        self.kind = kind

    def encode(self, path: Path) -> torch.Tensor:
        with Image.open(path) as image:
            image = image.convert("RGB")
            batch = self.processor(images=image, return_tensors="pt")
        batch = _move_batch_to_device(batch, self.device)
        with torch.inference_mode(), _autocast(self.device, self.amp):
            if self.kind == "medsiglip":
                output = self.model.get_image_features(**batch)
                if hasattr(output, "pooler_output"):
                    output = output.pooler_output
            else:
                output = self.model(**batch)
                output = output.last_hidden_state[:, 0]
        return _ensure_vector(output)


class CTCLIPEncoder(Encoder):
    """Run the official CT-CLIP vision encoder and image projection.

    The CT-CLIP checkpoint also contains a text encoder.  SCR only needs the
    image side, so this class loads the official CTViT weights and the learned
    image projection without constructing the text model.  The output is the
    unnormalized 512-dimensional image projection.
    """

    def __init__(
        self,
        checkpoint: Path,
        official_repo: Path,
        device: torch.device,
        amp: bool,
    ) -> None:
        super().__init__(device, amp)
        self.model_id = "ibrahimethemhamamci/CT-CLIP"
        self.model_revision = f"checkpoint-sha256:{_sha256(checkpoint)}"
        self.preprocessing_key = PREPROCESSING["ct_clip"]
        self.input_dtype = torch.float16 if device.type == "cuda" and amp else torch.float32

        transformer_root = Path(official_repo) / "transformer_maskgit"
        package_root = transformer_root / "transformer_maskgit"
        if not package_root.is_dir():
            raise RuntimeError(f"CT-CLIP source is missing: {transformer_root}")
        if str(transformer_root) not in sys.path:
            sys.path.insert(0, str(transformer_root))
        # Avoid importing the official package __init__, which imports the
        # training/data stack.  Only CTViT and its inference dependencies are
        # needed for image embeddings.
        if "transformer_maskgit" not in sys.modules:
            package = types.ModuleType("transformer_maskgit")
            package.__path__ = [str(package_root)]
            sys.modules["transformer_maskgit"] = package
        from transformer_maskgit.ctvit import CTViT

        self.model = CTViT(
            dim=512,
            codebook_size=8192,
            image_size=480,
            patch_size=20,
            temporal_patch_size=10,
            spatial_depth=4,
            temporal_depth=4,
            dim_head=32,
            heads=8,
        )
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        visual_state = {
            key[len("visual_transformer.") :]: value
            for key, value in state.items()
            if key.startswith("visual_transformer.")
        }
        missing, _unexpected = self.model.load_state_dict(visual_state, strict=False)
        if len(missing) > 1:
            raise RuntimeError(f"CT-CLIP vision weights incomplete: missing={missing[:5]}")
        projection = torch.nn.Linear(294912, 512, bias=False)
        projection.load_state_dict({"weight": state["to_visual_latent.weight"]})
        del state, visual_state
        if self.input_dtype == torch.float16:
            self.model = self.model.half()
            projection = projection.half()
        self.model = self.model.to(device).eval()
        self.projection = projection.to(device).eval()

    @staticmethod
    def _load_volume(path: Path) -> torch.Tensor:
        import nibabel as nib

        image = nib.as_closest_canonical(nib.load(str(path)))
        data = np.asarray(image.dataobj, dtype=np.float32)
        if data.ndim != 3:
            raise ValueError(f"CT-CLIP expects a 3D volume, got ndim={data.ndim}")
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
        # CT-CLIP's released inference transform targets (z, x, y) spacing
        # (1.5, 0.75, 0.75), then center-crops/pads to (240, 480, 480).
        zooms = tuple(float(value) for value in image.header.get_zooms()[:3])
        current_spacing = (zooms[2], zooms[0], zooms[1])
        target_spacing = (1.5, 0.75, 0.75)
        volume = torch.from_numpy(data).permute(2, 0, 1).unsqueeze(0).unsqueeze(0)
        resized_shape = tuple(
            max(1, int(round(size * current / target)))
            for size, current, target in zip(volume.shape[-3:], current_spacing, target_spacing)
        )
        volume = F.interpolate(volume, size=resized_shape, mode="trilinear", align_corners=False)
        volume = volume[0, 0].permute(1, 2, 0)  # (x, y, z)
        volume = volume.clamp(-1000.0, 1000.0).div(1000.0)
        target_shape = (480, 480, 240)
        starts = [max(0, (int(size) - target) // 2) for size, target in zip(volume.shape, target_shape)]
        volume = volume[
            starts[0] : starts[0] + target_shape[0],
            starts[1] : starts[1] + target_shape[1],
            starts[2] : starts[2] + target_shape[2],
        ]
        pad = []
        for size, target in zip(reversed(volume.shape), reversed(target_shape)):
            missing = max(0, target - int(size))
            pad.extend([missing // 2, missing - missing // 2])
        if any(pad):
            volume = F.pad(volume, tuple(pad), value=-1.0)
        return volume.permute(2, 0, 1).unsqueeze(0).unsqueeze(0).contiguous()

    def encode(self, path: Path) -> torch.Tensor:
        volume = self._load_volume(path).to(self.device, dtype=self.input_dtype)
        with torch.inference_mode(), _autocast(self.device, self.amp):
            # The upstream VQ implementation materializes a [tokens,
            # codebook_size] one-hot matrix even in eval mode.  That matrix
            # OOMs on the shared GPU.  Cosine VQ in eval mode is equivalent to
            # argmax over the codebook followed by gather, without one-hot.
            tokens = self.model.to_patch_emb(volume)
            token_shape = tokens.shape
            tokens = self.model.encode(tokens)
            flat_tokens = tokens.flatten(1, 3)
            codebook = self.model.vq.codebook
            if codebook.ndim == 3:
                codebook = codebook[0]
            indices = torch.einsum("bnd,cd->bnc", flat_tokens, codebook).argmax(dim=-1)
            tokens = codebook[indices].reshape(token_shape)
            pooled = tokens.mean(dim=1).flatten(start_dim=1)
            vector = self.projection(pooled)
        return _ensure_vector(vector)


class MammoFMEncoder(Encoder):
    """Load the official Mammo-FM image encoder and projection head.

    The official checkpoint contains its model configuration and uses the
    Batmanlab EfficientNet implementation.  Only the projected image vector
    is returned; it is not L2-normalized, matching the requested raw output.
    """

    def __init__(
        self,
        checkpoint: Path,
        official_source: Path,
        device: torch.device,
        amp: bool,
    ) -> None:
        super().__init__(device, amp)
        self.model_id = "batmanlab/Mammo-FM_BatmanlabTrained_CLIP"
        self.model_revision = f"checkpoint-sha256:{_sha256(checkpoint)}"
        self.preprocessing_key = PREPROCESSING["mammo_fm"]
        source = Path(official_source)
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        try:
            # The official breastclip/__init__.py imports the whole training
            # stack (including optional omegaconf dependencies).  Construct
            # lightweight namespace packages so only the model modules load.
            package_root = source / "breastclip"
            if "breastclip" not in sys.modules:
                breastclip = types.ModuleType("breastclip")
                breastclip.__path__ = [str(package_root)]
                sys.modules["breastclip"] = breastclip
            model_root = package_root / "model"
            if "breastclip.model" not in sys.modules:
                model_package = types.ModuleType("breastclip.model")
                model_package.__path__ = [str(model_root)]
                sys.modules["breastclip.model"] = model_package
            modules = importlib.import_module("breastclip.model.modules")
        except ImportError as exc:
            raise RuntimeError(
                "Mammo-FM official source is missing; clone batmanlab/Mammo-FM "
                "and pass --mammo-source pointing to its src/codebase"
            ) from exc

        checkpoint_obj = torch.load(checkpoint, map_location="cpu", weights_only=False)
        model_config = checkpoint_obj["config"]["model"]
        image_config = model_config["image_encoder"]
        self.image_encoder = modules.load_image_encoder(image_config)
        image_weights = {
            key[len("image_encoder.") :]: value
            for key, value in checkpoint_obj["model"].items()
            if key.startswith("image_encoder.")
        }
        self.image_encoder.load_state_dict(image_weights, strict=True)
        projection_config = model_config.get("projection_head")
        if projection_config:
            self.projection = modules.load_projection_head(
                embedding_dim=self.image_encoder.out_dim,
                config_projection_head=projection_config,
            )
            projection_weights = {
                key[len("image_projection.") :]: value
                for key, value in checkpoint_obj["model"].items()
                if key.startswith("image_projection.")
            }
            self.projection.load_state_dict(projection_weights, strict=True)
        else:
            self.projection = torch.nn.Identity()
        self.image_encoder = self.image_encoder.to(device).eval()
        self.projection = self.projection.to(device).eval()
        del checkpoint_obj

    def _preprocess(self, path: Path) -> torch.Tensor:
        # Mammo-FM's official validation size and training statistics are in
        # src/codebase/configs/pre_train_b5_clip.yaml.
        image = Image.open(path).convert("RGB")
        image = image.resize((912, 1520), Image.Resampling.BILINEAR)
        array = np.asarray(image, dtype=np.float32) / 255.0
        array = (array - 0.3089279) / 0.25053555408335154
        return torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)

    def encode(self, path: Path) -> torch.Tensor:
        image = self._preprocess(path).to(self.device)
        with torch.inference_mode(), _autocast(self.device, self.amp):
            features = self.image_encoder(image)
            features = self.projection(features)
        return _ensure_vector(features)


class CTFMEncoder(Encoder):
    def __init__(
        self,
        checkpoint: Path,
        device: torch.device,
        amp: bool,
        patch_batch_size: int,
    ) -> None:
        super().__init__(device, amp)
        from monai.inferers import SlidingWindowSplitter
        from monai.networks.nets.segresnet_ds import SegResEncoder

        self.model_id = "project-lighter/ct_fm_feature_extractor"
        self.model_revision = f"checkpoint-sha256:{_sha256(checkpoint)}"
        self.preprocessing_key = PREPROCESSING["ct_fm"]
        self.patch_batch_size = patch_batch_size
        self.splitter_cls = SlidingWindowSplitter
        if checkpoint.suffix == ".safetensors":
            from safetensors.torch import load_file

            state = load_file(str(checkpoint), device="cpu")
        else:
            state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if isinstance(state, Mapping) and "state_dict" in state:
            state = state["state_dict"]
        state = {
            key.removeprefix("encoder."): value
            for key, value in state.items()
        }
        self.model = SegResEncoder(
            blocks_down=(1, 2, 2, 4, 4),
            head_module=lambda x: F.adaptive_avg_pool3d(x[-1], 1).flatten(start_dim=1),
        )
        self.model.load_state_dict(state, strict=False)
        self.model = self.model.to(device).eval()

    def _load_volume(self, path: Path) -> torch.Tensor:
        from monai.transforms import (
            Compose,
            CropForeground,
            EnsureType,
            LoadImage,
            Orientation,
            ScaleIntensityRange,
            Spacing,
        )

        image, _ = LoadImage(image_only=False, ensure_channel_first=True)(str(path))
        transform = Compose(
            [
                EnsureType(),
                Orientation(axcodes="SPL"),
                Spacing(pixdim=(3, 1, 1), mode="bilinear"),
                CropForeground(),
                ScaleIntensityRange(a_min=-1024, a_max=2048, b_min=0, b_max=1, clip=True),
            ]
        )
        image = transform(image)
        if image.ndim != 4:
            raise ValueError(f"CT volume has unexpected shape {tuple(image.shape)}")
        return image.float()

    def encode(self, path: Path) -> torch.Tensor:
        volume = self._load_volume(path)
        splitter = self.splitter_cls((24, 128, 128), 0.0)
        patches = []
        for patch, _location in splitter(volume.unsqueeze(0)):
            patches.append(patch)
        if not patches:
            raise ValueError("CT volume produced no patches")
        features = []
        with torch.inference_mode():
            for start in range(0, len(patches), self.patch_batch_size):
                batch = torch.cat(patches[start : start + self.patch_batch_size], dim=0)
                batch = batch.to(self.device)
                with _autocast(self.device, self.amp):
                    features.append(self.model(batch).float().cpu())
        return _ensure_vector(torch.cat(features, dim=0).mean(dim=0))


class MARSFeatureBackbone(Encoder):
    """MARS Swin-T backbone, returning the pooled latent feature (768 dims)."""

    def __init__(self, checkpoint: Path, device: torch.device, amp: bool) -> None:
        super().__init__(device, amp)
        from monai.networks.nets.swin_unetr import SwinTransformer

        self.model_id = "zqiuak/MARS"
        self.model_revision = f"checkpoint-sha256:{_sha256(checkpoint)}"
        self.preprocessing_key = PREPROCESSING["mars"]
        self.model = SwinTransformer(
            in_chans=1,
            embed_dim=48,
            window_size=(7, 7, 7),
            patch_size=(2, 2, 2),
            depths=(2, 2, 2, 2),
            num_heads=(3, 6, 12, 24),
            mlp_ratio=4.0,
            qkv_bias=True,
            norm_layer=torch.nn.LayerNorm,
            use_checkpoint=False,
            spatial_dims=3,
            use_v2=True,
        )
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if isinstance(state, Mapping) and "state_dict" in state:
            state = state["state_dict"]
        selected: dict[str, Any] = {}
        for key, value in state.items():
            if "swinViT." in key:
                selected[key.split("swinViT.", 1)[1]] = value
        current = self.model.state_dict()
        matched = {
            key: value
            for key, value in selected.items()
            if key in current and tuple(value.shape) == tuple(current[key].shape)
        }
        if not matched:
            # Some MARS checkpoints use the backbone keys without a prefix.
            matched = {
                key: value
                for key, value in state.items()
                if key in current and tuple(value.shape) == tuple(current[key].shape)
            }
        if not matched:
            raise RuntimeError("could not match MARS SwinTransformer weights")
        missing, _unexpected = self.model.load_state_dict(matched, strict=False)
        if len(matched) < int(0.95 * len(current)):
            raise RuntimeError(
                f"only matched {len(matched)}/{len(current)} MARS backbone tensors; "
                "refusing to run with an incomplete checkpoint"
            )
        self.model = self.model.to(device).eval()

    @staticmethod
    def _prepare_volume(array: np.ndarray) -> torch.Tensor:
        array = np.nan_to_num(array.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        nonzero = array[np.abs(array) > 1e-6]
        if nonzero.size:
            array = (array - float(nonzero.mean())) / max(float(nonzero.std()), 1e-6)
        tensor = torch.from_numpy(array).unsqueeze(0).unsqueeze(0)
        spatial = tensor.shape[-3:]
        pad = [max(0, 96 - int(size)) for size in spatial]
        if any(pad):
            tensor = F.pad(
                tensor,
                (pad[2] // 2, pad[2] - pad[2] // 2,
                 pad[1] // 2, pad[1] - pad[1] // 2,
                 pad[0] // 2, pad[0] - pad[0] // 2),
            )
        spatial = tensor.shape[-3:]
        starts = [max(0, (int(size) - 96) // 2) for size in spatial]
        tensor = tensor[
            :, :, starts[0] : starts[0] + 96,
            starts[1] : starts[1] + 96,
            starts[2] : starts[2] + 96,
        ]
        return tensor

    def encode(self, path: Path) -> torch.Tensor:
        import nibabel as nib

        image = nib.as_closest_canonical(nib.load(str(path)))
        data = np.asarray(image.dataobj)
        if data.ndim not in (3, 4):
            raise ValueError(f"MR volume has unexpected ndim={data.ndim}")
        volumes = [data] if data.ndim == 3 else [data[..., idx] for idx in range(data.shape[-1])]
        vectors = []
        with torch.inference_mode():
            for volume in volumes:
                tensor = self._prepare_volume(volume).to(self.device)
                with _autocast(self.device, self.amp):
                    hidden = self.model(tensor, normalize=True)[4]
                    vector = F.adaptive_avg_pool3d(hidden, 1).flatten(1)
                vectors.append(vector.float().cpu())
        return _ensure_vector(torch.cat(vectors, dim=0).mean(dim=0))


def discover_files(source_root: Path, modality: str) -> list[Path]:
    folder = source_root / modality
    if not folder.is_dir():
        return []
    suffixes = {"CR": {".jpg", ".jpeg"}, "DX": {".jpg", ".jpeg"}, "MG": {".jpg", ".jpeg"}}[modality] if modality in {"CR", "DX", "MG"} else {".nii.gz"}
    files: list[Path] = []
    for path in folder.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if modality in {"CR", "DX", "MG"}:
            if path.suffix.lower() in suffixes:
                files.append(path)
        elif path.name.lower().endswith(".nii.gz"):
            files.append(path)
    return sorted(files)


def _load_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="") as handle:
        return {row["source_relative_path"]: row for row in csv.DictReader(handle)}


def _write_manifest(path: Path, rows: Mapping[str, Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
            writer.writeheader()
            for key in sorted(rows):
                writer.writerow({column: rows[key].get(column, "") for column in MANIFEST_COLUMNS})
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _atomic_save_tensor(path: Path, tensor: torch.Tensor) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        torch.save(tensor, tmp_path)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _valid_output(path: Path, expected_dim: str | None) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        value = torch.load(path, map_location="cpu", weights_only=True)
        tensor = _ensure_vector(value)
        return expected_dim in (None, "", str(tensor.numel()))
    except Exception:
        return False


def _checkpoint_for(model_key: str, args: argparse.Namespace) -> Path:
    overrides = {
        "medsiglip": args.medsiglip_dir,
        "rad_dino": args.rad_dino_dir,
        "mammo_fm": args.mammo_checkpoint,
        "ct_fm": args.ctfm_checkpoint,
        "mars": args.mars_checkpoint,
        "ct_clip": args.ct_clip_checkpoint,
    }
    value = overrides[model_key]
    if value:
        return Path(value)
    defaults = {
        "mammo_fm": args.checkpoint_root / "Mammo-FM" / "Mammo-FM_BatmanlabTrained_CLIP.tar",
        "ct_fm": args.checkpoint_root / "ct_fm_feature_extractor" / "model.safetensors",
        "mars": args.checkpoint_root / "MARS" / "mars_pretrained.pt",
        "ct_clip": args.checkpoint_root / "ct_clip" / "models" / "CT-CLIP-Related" / "CT-CLIP_v2.pt",
    }
    if model_key in defaults:
        return defaults[model_key]
    return Path(".")


def _build_encoder(model_key: str, args: argparse.Namespace, device: torch.device) -> Encoder:
    if model_key == "medsiglip":
        load_id = args.medsiglip_dir or args.checkpoint_root / "medsiglip-448"
        return HFImageEncoder("medsiglip", "google/medsiglip-448", load_id, args.hf_cache, device, args.amp)
    if model_key == "rad_dino":
        load_id = args.rad_dino_dir or args.checkpoint_root / "rad_dino"
        return HFImageEncoder("rad_dino", "microsoft/rad-dino", load_id, args.hf_cache, device, args.amp)
    checkpoint = _checkpoint_for(model_key, args)
    if not checkpoint.exists():
        raise FileNotFoundError(f"missing checkpoint for {model_key}: {checkpoint}")
    if model_key == "mammo_fm":
        return MammoFMEncoder(checkpoint, args.mammo_source, device, args.amp)
    if model_key == "ct_fm":
        return CTFMEncoder(checkpoint, device, args.amp, args.ct_patch_batch_size)
    if model_key == "mars":
        return MARSFeatureBackbone(checkpoint, device, args.amp)
    if model_key == "ct_clip":
        return CTCLIPEncoder(checkpoint, args.ct_clip_repo, device, args.amp)
    raise KeyError(model_key)


def _release_encoder(encoder: Encoder) -> None:
    """Release model references and CUDA allocator blocks between modalities."""
    del encoder
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, default=Path("/mnt/disk1/khangdp/ckpt/encoders"))
    parser.add_argument("--hf-cache", type=Path, default=Path("/mnt/disk1/khangdp/hf_cache"))
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--encoder-set", choices=["default", "rad_dino", "ct_clip"], default="default")
    parser.add_argument("--modalities", nargs="+", choices=["CR", "DX", "MG", "CT", "MR"], default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--amp", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--ct-patch-batch-size", type=int, default=4)
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--mammo-source", type=Path, default=Path("/mnt/disk1/khangdp/third_party/Mammo-FM/src/codebase"))
    parser.add_argument("--medsiglip-dir", type=Path, default=None)
    parser.add_argument("--rad-dino-dir", type=Path, default=None)
    parser.add_argument("--mammo-checkpoint", type=Path, default=None)
    parser.add_argument("--ctfm-checkpoint", type=Path, default=None)
    parser.add_argument("--mars-checkpoint", type=Path, default=None)
    parser.add_argument(
        "--ct-clip-repo",
        type=Path,
        default=Path("/mnt/disk1/khangdp/third_party/CT-CLIP"),
    )
    parser.add_argument("--ct-clip-checkpoint", type=Path, default=None)
    parser.add_argument(
        "--disable-cudnn",
        action="store_true",
        help="Disable cuDNN for shared-GPU inference when cuDNN cannot initialize.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.source_root = args.source_root.resolve()
    args.output_root = args.output_root.resolve()
    args.checkpoint_root = args.checkpoint_root.resolve()
    args.hf_cache = args.hf_cache.resolve()
    args.ct_clip_repo = args.ct_clip_repo.resolve()
    args.hf_cache.mkdir(parents=True, exist_ok=True)
    args.amp = bool(args.amp and args.device.startswith("cuda"))
    if args.disable_cudnn:
        torch.backends.cudnn.enabled = False
    if args.manifest is None:
        manifest_name = {
            "rad_dino": "manifest_rad_dino.csv",
            "ct_clip": "manifest_ct_clip.csv",
        }.get(args.encoder_set, "manifest.csv")
        args.manifest = args.output_root / manifest_name
    args.manifest = args.manifest.resolve()
    if args.encoder_set == "rad_dino":
        mapping = RAD_MODELS
    elif args.encoder_set == "ct_clip":
        mapping = CT_CLIP_MODELS
    else:
        mapping = DEFAULT_MODELS
    modalities = args.modalities or list(mapping)
    device = torch.device(args.device if torch.cuda.is_available() or args.device == "cpu" else "cpu")
    print(
        f"device={device} encoder_set={args.encoder_set} modalities={','.join(modalities)} "
        f"amp={args.amp} cudnn={torch.backends.cudnn.enabled}"
    )
    print(f"source_root={args.source_root} output_root={args.output_root}")

    rows = _load_manifest(args.manifest)
    encoders: dict[str, Encoder] = {}
    total = 0
    for modality in modalities:
        files = discover_files(args.source_root, modality)
        if args.max_files is not None:
            files = files[: args.max_files]
        print(f"modality={modality} files={len(files)}")
        model_key = mapping[modality]
        try:
            if model_key not in encoders:
                encoders[model_key] = _build_encoder(model_key, args, device)
            encoder = encoders[model_key]
        except Exception as exc:
            print(f"modality={modality} model_load_failed={type(exc).__name__}")
            for source in files:
                relative = source.relative_to(args.source_root).as_posix()
                rows[relative] = {
                    "source_relative_path": relative,
                    "output_relative_path": "",
                    "modality": modality,
                    "model_id": model_key,
                    "model_revision": "",
                    "preprocessing_version": PREPROCESSING[model_key],
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "created_at": _now(),
                    "code_version": CODE_VERSION,
                }
            _write_manifest(args.manifest, rows)
            continue

        for index, source in enumerate(files, start=1):
            relative = source.relative_to(args.source_root).as_posix()
            output_relative = f"{relative}.pt"
            output = args.output_root / output_relative
            prior = rows.get(relative, {})
            if (
                prior.get("model_id") == encoder.model_id
                and prior.get("model_revision") == encoder.model_revision
                and prior.get("preprocessing_version") == encoder.preprocessing_key
                and prior.get("status") in {"success", "skipped"}
                and _valid_output(output, prior.get("embedding_dim"))
            ):
                prior = dict(prior)
                prior["status"] = "skipped"
                rows[relative] = prior
                continue
            try:
                vector = encoder.encode(source)
                vector = _ensure_vector(vector)
                _atomic_save_tensor(output, vector)
                stat = source.stat()
                rows[relative] = {
                    "source_relative_path": relative,
                    "output_relative_path": output_relative,
                    "modality": modality,
                    "model_id": encoder.model_id,
                    "model_revision": encoder.model_revision,
                    "preprocessing_version": encoder.preprocessing_key,
                    "embedding_dim": str(vector.numel()),
                    "dtype": str(vector.dtype).replace("torch.", ""),
                    "normalized": "false",
                    "source_size": str(stat.st_size),
                    "source_mtime": str(stat.st_mtime),
                    "status": "success",
                    "error_type": "",
                    "created_at": _now(),
                    "code_version": CODE_VERSION,
                }
                total += 1
                if index == 1 or index % 10 == 0:
                    print(f"modality={modality} completed={index}/{len(files)} dim={vector.numel()}")
            except Exception as exc:
                rows[relative] = {
                    "source_relative_path": relative,
                    "output_relative_path": output_relative,
                    "modality": modality,
                    "model_id": encoder.model_id,
                    "model_revision": encoder.model_revision,
                    "preprocessing_version": encoder.preprocessing_key,
                    "embedding_dim": "",
                    "dtype": "",
                    "normalized": "false",
                    "source_size": str(source.stat().st_size),
                    "source_mtime": str(source.stat().st_mtime),
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "created_at": _now(),
                    "code_version": CODE_VERSION,
                }
                detail = " ".join(str(exc).split())[:240]
                print(
                    f"modality={modality} failed={index}/{len(files)} "
                    f"error={type(exc).__name__} detail={detail}"
                )
                if "out of memory" in str(exc).lower() and torch.cuda.is_available():
                    torch.cuda.empty_cache()
            finally:
                _write_manifest(args.manifest, rows)
        if not any(mapping.get(future) == model_key for future in modalities[modalities.index(modality) + 1 :]):
            encoder_to_release = encoders.pop(model_key, None)
            if encoder_to_release is not None:
                _release_encoder(encoder_to_release)
    print(f"new_success={total} manifest={args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
