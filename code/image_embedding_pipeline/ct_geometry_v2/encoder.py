"""Full CT-CLIP v2 visual weights + learned projection, frozen inference."""
from __future__ import annotations

import importlib.metadata
import sys
import types
from pathlib import Path

import numpy as np
import torch

from geometry import sha256


class Encoder:
    def __init__(self, checkpoint: Path, repo: Path, device='cuda'):
        self.device = torch.device(device)
        if self.device.type != 'cuda':
            raise ValueError('Released CTViT source requires CUDA for attention tensors')
        root = repo / 'transformer_maskgit'
        package = types.ModuleType('transformer_maskgit')
        package.__path__ = [str(root / 'transformer_maskgit')]
        sys.modules['transformer_maskgit'] = package
        sys.path.insert(0, str(root))
        from transformer_maskgit.ctvit import CTViT
        self.model = CTViT(dim=512, codebook_size=8192, image_size=480, patch_size=20,
                           temporal_patch_size=10, spatial_depth=4, temporal_depth=4, dim_head=32, heads=8)
        state = torch.load(checkpoint, map_location='cpu', weights_only=True, mmap=True)
        visual = {k.removeprefix('visual_transformer.'): v for k, v in state.items() if k.startswith('visual_transformer.')}
        missing, unexpected = self.model.load_state_dict(visual, strict=False)
        # Newer vector-quantize adds this EMA-training-only buffer. No learned
        # encoder/projection weight is allowed to be absent or unexpected.
        allowed = {'vq._codebook.embed_avg'}
        if set(missing) - allowed or unexpected:
            raise ValueError(f'Checkpoint mismatch: missing={missing}, unexpected={unexpected}')
        weight = state['to_visual_latent.weight']
        if tuple(weight.shape) != (512, 24*24*512):
            raise ValueError(f'Unexpected projection shape: {tuple(weight.shape)}')
        self.projection = torch.nn.Linear(24*24*512, 512, bias=False)
        self.projection.load_state_dict({'weight': weight}, strict=True)
        self.model.to(self.device).eval()
        self.projection.to(self.device).eval()
        self.model.requires_grad_(False); self.projection.requires_grad_(False)
        self.manifest = {
            'model': 'CT-CLIP_v2 full visual_transformer + to_visual_latent',
            'checkpoint_path': str(checkpoint.resolve()), 'checkpoint_sha256': sha256(checkpoint),
            'repo_path': str(repo.resolve()),
            'source_sha256': {str(p.relative_to(repo)): sha256(p) for p in sorted(root.rglob('*.py'))},
            'missing_training_only_buffers': missing,
            'torch': torch.__version__, 'vector_quantize_pytorch': importlib.metadata.version('vector-quantize-pytorch'),
            'precision': 'float32 parameters, CUDA autocast float16; float32 VQ and pooling/projection',
            'pooling': 'mean depth tokens -> flatten 24x24 spatial grid -> learned projection',
            'embedding_dim': 512, 'normalized': False,
        }

    @torch.inference_mode()
    def __call__(self, volume, check_vq=False):
        if volume.shape != (240, 480, 480):
            raise ValueError(f'Unexpected CT input: {volume.shape}')
        torch.cuda.reset_peak_memory_stats()
        x = torch.from_numpy(volume)[None, None].to(self.device)
        with torch.autocast('cuda', dtype=torch.float16):
            tokens = self.model.encode(self.model.to_patch_emb(x))
        if tuple(tokens.shape) != (1, 24, 24, 24, 512):
            raise ValueError(f'Unexpected token shape: {tokens.shape}')
        flat = tokens.float().reshape(1, -1, 512)
        # Call the installed VQ itself, in bounded chunks. Unlike manual dot-product
        # replacements this preserves its cosine normalization/codebook semantics.
        quantized = []
        for chunk in flat.split(256, dim=1):
            quantized.append(self.model.vq(chunk)[0])
        quantized = torch.cat(quantized, dim=1)
        equivalence = None
        if check_vq:
            expected = self.model.vq(flat[:, :512])[0]
            equivalence = float((expected-quantized[:, :512]).abs().max())
            if equivalence > 1e-6:
                raise ValueError(f'Chunked VQ differs from reference: {equivalence}')
        pooled = quantized.reshape(1, 24, 24, 24, 512).mean(1).flatten(1)
        vector = self.projection(pooled)[0].float().cpu().numpy()
        if vector.shape != (512,) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
            raise ValueError('Invalid CT projected embedding')
        diagnostics = {'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                       'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
                       'vq_chunk_reference_max_error': equivalence,
                       'embedding_norm': float(np.linalg.norm(vector)),
                       'embedding_min': float(vector.min()), 'embedding_max': float(vector.max())}
        return vector, diagnostics
