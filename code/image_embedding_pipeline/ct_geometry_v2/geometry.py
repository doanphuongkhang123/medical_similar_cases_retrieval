"""DICOM CT geometry and HU reconstruction. No model/GPU dependency."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pydicom
from scipy.ndimage import affine_transform


class RejectedSeries(ValueError):
    """A source cannot safely be interpreted as one anatomical CT volume."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def assemble(datasets, *, min_slices=20):
    """Sort by physical position; reject incomplete/irregular/mixed stacks.

    Array axes are slice,row,column; affine maps these indices to RAS mm.
    A constant in-plane displacement (gantry tilt) is retained in the affine.
    Per-frame Enhanced CT is explicitly unsupported, never silently flattened.
    """
    if len(datasets) < min_slices:
        raise RejectedSeries('too_few_slices')
    first = datasets[0]
    if any(str(getattr(d, 'Modality', '')) != 'CT' for d in datasets):
        raise RejectedSeries('non_ct')
    if any(int(getattr(d, 'NumberOfFrames', 1)) != 1 for d in datasets):
        raise RejectedSeries('enhanced_or_multiframe_requires_separate_reader')
    if any(str(getattr(d, 'PhotometricInterpretation', '')) not in ('MONOCHROME1', 'MONOCHROME2')
           or int(getattr(d, 'SamplesPerPixel', 1)) != 1 for d in datasets):
        raise RejectedSeries('color_or_rendered_not_hu_volume')
    image_types = [str(getattr(d, 'ImageType', '')).upper() for d in datasets]
    if any('LOCALIZER' in t or 'SCOUT' in t for t in image_types):
        raise RejectedSeries('localizer')
    try:
        orient = np.asarray(first.ImageOrientationPatient, dtype=float)
        spacing = np.asarray(first.PixelSpacing, dtype=float)
        positions = np.asarray([d.ImagePositionPatient for d in datasets], dtype=float)
        orientations = np.asarray([d.ImageOrientationPatient for d in datasets], dtype=float)
        spacings = np.asarray([d.PixelSpacing for d in datasets], dtype=float)
    except (AttributeError, TypeError, ValueError) as e:
        raise RejectedSeries('missing_geometry') from e
    if orient.shape != (6,) or spacing.shape != (2,) or positions.shape != (len(datasets), 3):
        raise RejectedSeries('invalid_geometry_shape')
    if not all(np.isfinite(x).all() for x in (orient, spacing, positions, orientations, spacings)):
        raise RejectedSeries('nonfinite_geometry')
    if (spacing <= 0).any() or not np.allclose(spacings, spacing, atol=1e-4, rtol=1e-4):
        raise RejectedSeries('inconsistent_pixel_spacing')
    if not np.allclose(orientations, orient, atol=1e-4, rtol=0):
        raise RejectedSeries('mixed_orientations')
    col_direction, row_direction = orient[:3], orient[3:]
    if not np.allclose([np.linalg.norm(col_direction), np.linalg.norm(row_direction)], 1, atol=1e-4):
        raise RejectedSeries('nonunit_orientation')
    if abs(col_direction @ row_direction) > 1e-4:
        raise RejectedSeries('nonorthogonal_orientation')
    normal = np.cross(col_direction, row_direction)
    order = np.argsort(positions @ normal, kind='stable')
    positions = positions[order]
    ordered = [datasets[int(i)] for i in order]
    distances = np.diff(positions @ normal)
    if (distances < 1e-3).any():
        raise RejectedSeries('duplicate_slice_positions_or_mixed_phases')
    z_spacing = float(np.median(distances))
    if not np.allclose(distances, z_spacing, atol=max(.05, .02 * z_spacing), rtol=0):
        raise RejectedSeries('nonuniform_slice_spacing_or_missing_slices')
    delta = (positions[-1] - positions[0]) / (len(positions) - 1)
    fitted = positions[0] + np.arange(len(positions))[:, None] * delta
    residual = np.linalg.norm(positions - fitted, axis=1)
    if residual.max() > max(.1, .02 * z_spacing):
        raise RejectedSeries('nonaffine_slice_positions')
    for key in ('StudyInstanceUID', 'SeriesInstanceUID', 'FrameOfReferenceUID'):
        values = {str(getattr(d, key, '')) for d in ordered}
        if len(values) != 1:
            raise RejectedSeries('mixed_' + key)
    pixels = []
    pixel_hash = hashlib.sha256()
    slopes, intercepts = [], []
    for d in ordered:
        try:
            a = np.asarray(d.pixel_array)
            slope, intercept = float(d.RescaleSlope), float(d.RescaleIntercept)
        except (AttributeError, TypeError, ValueError) as e:
            raise RejectedSeries('missing_hu_transform_or_pixel_decode_error') from e
        if a.ndim != 2 or not np.isfinite(a).all():
            raise RejectedSeries('invalid_pixel_array')
        if not np.isfinite([slope, intercept]).all() or slope == 0:
            raise RejectedSeries('invalid_hu_transform')
        pixel_hash.update(str(a.dtype).encode())
        pixel_hash.update(np.asarray(a.shape, dtype=np.int64).tobytes())
        pixel_hash.update(np.ascontiguousarray(a).tobytes())
        pixels.append(a.astype(np.float32) * slope + intercept)
        slopes.append(slope); intercepts.append(intercept)
    if len({a.shape for a in pixels}) != 1:
        raise RejectedSeries('mixed_pixel_shapes')
    hu = np.stack(pixels)
    if not np.isfinite(hu).all() or float(np.ptp(hu)) == 0:
        raise RejectedSeries('nonfinite_or_constant_hu')
    affine = np.eye(4)
    affine[:3, :3] = np.column_stack((delta, row_direction * spacing[0], col_direction * spacing[1]))
    affine[:3, 3] = positions[0]
    affine = np.diag([-1., -1., 1., 1.]) @ affine  # DICOM LPS -> RAS
    # Translation invariant duplicate identity; includes orientation and voxel scale.
    h = hashlib.sha256(np.asarray(hu.shape, dtype=np.int64).tobytes())
    h.update(hu.tobytes())
    h.update(np.round(affine[:3, :3], 5).tobytes())
    try:
        thickness = float(ordered[0].SliceThickness)
    except (AttributeError, TypeError, ValueError):
        thickness = None
    metadata = {
        'source_shape_dhw': list(hu.shape), 'source_affine_ras': affine.tolist(),
        'physical_z_spacing_mm': z_spacing, 'slice_thickness_mm': thickness,
        'spacing_max_deviation_mm': float(abs(distances-z_spacing).max()),
        'position_fit_max_residual_mm': float(residual.max()),
        'pixel_payload_sha256': pixel_hash.hexdigest(), 'hu_geometry_sha256': h.hexdigest(),
        'hu_min': float(hu.min()), 'hu_max': float(hu.max()),
        'unique_slope_count': len(set(slopes)), 'unique_intercept_count': len(set(intercepts)),
        'sop_order_sha256': hashlib.sha256(canonical_json([str(d.SOPInstanceUID) for d in ordered]).encode()).hexdigest(),
        'body_part': str(getattr(first, 'BodyPartExamined', '')),
        'study_date': str(getattr(first, 'StudyDate', '')),
        'dicom_patient_id': str(getattr(first, 'PatientID', '')),
    }
    return hu, affine, metadata


def read_series(archive: Path, series_uid: str, study_uid: str):
    datasets, member_hashes = [], []
    with zipfile.ZipFile(archive) as z:
        members = [n for n in z.namelist() if n.lower().endswith('.dcm') and Path(n).parent.name == series_uid]
        if not members or len(set(members)) != len(members):
            raise RejectedSeries('missing_series_or_duplicate_zip_member_names')
        for name in members:
            with z.open(name) as stream:
                raw = stream.read()
            member_hashes.append(hashlib.sha256(raw).hexdigest())
            import io
            d = pydicom.dcmread(io.BytesIO(raw), force=False)
            if str(getattr(d, 'SeriesInstanceUID', '')) != series_uid:
                raise RejectedSeries('zip_directory_and_series_uid_disagree')
            if str(getattr(d, 'StudyInstanceUID', '')) != study_uid:
                raise RejectedSeries('unexpected_study_uid')
            datasets.append(d)
    hu, affine, metadata = assemble(datasets)
    metadata['dicom_members_sha256'] = hashlib.sha256(canonical_json(sorted(member_hashes)).encode()).hexdigest()
    return hu, affine, metadata


def resample(hu, affine, target_shape_xyz=(480, 480, 240), target_spacing_xyz=(.75, .75, 1.5)):
    """Sample a centered fixed physical RAS grid without a huge intermediate.

    Clamp HU before linear interpolation, as in the released CT-CLIP transform.
    Output model layout is (z,x,y). Only source pixel centers within the source
    lattice count as supported; a separate coverage mask identifies padding.
    """
    corners = np.array(np.meshgrid(*[(0, n-1) for n in hu.shape], indexing='ij')).reshape(3, -1).T
    world = corners @ affine[:3, :3].T + affine[:3, 3]
    center = (world.min(0) + world.max(0)) / 2
    target = np.eye(4)
    target[:3, :3] = np.diag(target_spacing_xyz)
    target[:3, 3] = center - (np.asarray(target_shape_xyz)-1) * np.asarray(target_spacing_xyz) / 2
    mapping = np.linalg.inv(affine) @ target
    result = affine_transform(np.clip(hu, -1000, 1000), mapping[:3, :3], mapping[:3, 3],
                              output_shape=target_shape_xyz, order=1, mode='constant', cval=-1000,
                              prefilter=False, output=np.float32)
    coverage = affine_transform(np.ones(hu.shape, dtype=np.uint8), mapping[:3, :3], mapping[:3, 3],
                                output_shape=target_shape_xyz, order=0, mode='constant', cval=0,
                                prefilter=False)
    fraction = float(coverage.mean())
    if not fraction or not np.isfinite(result).all() or float(np.ptp(result)) == 0:
        raise RejectedSeries('empty_or_constant_resampled_input')
    volume = np.ascontiguousarray(result.transpose(2, 0, 1) / 1000)
    metadata = {
        'target_affine_ras_xyz': target.tolist(), 'model_shape_zxy': list(volume.shape),
        'padding_fraction': 1-fraction,
        'source_extent_mm_xyz': (world.max(0)-world.min(0)).tolist(),
        'target_extent_mm_xyz': ((np.asarray(target_shape_xyz)-1)*np.asarray(target_spacing_xyz)).tolist(),
        'input_sha256': hashlib.sha256(volume.tobytes()).hexdigest(),
        'input_min': float(volume.min()), 'input_max': float(volume.max()),
        'input_std': float(volume.std()),
    }
    return volume, metadata
