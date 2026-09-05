import sys
import unittest
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from geometry import assemble, resample, RejectedSeries


def slice_at(z, value, instance=1, slope=1, intercept=-1000):
    d=Dataset();d.file_meta=FileMetaDataset();d.file_meta.TransferSyntaxUID=ExplicitVRLittleEndian
    d.Modality='CT';d.PhotometricInterpretation='MONOCHROME2';d.SamplesPerPixel=1
    d.Rows=4;d.Columns=5;d.BitsAllocated=16;d.BitsStored=16;d.HighBit=15;d.PixelRepresentation=0
    d.ImageOrientationPatient=[1,0,0,0,1,0];d.ImagePositionPatient=[0,0,z]
    d.PixelSpacing=[2,3];d.SliceThickness=5;d.InstanceNumber=instance
    d.RescaleSlope=slope;d.RescaleIntercept=intercept
    d.StudyInstanceUID='1.2.3';d.SeriesInstanceUID='1.2.3.4';d.FrameOfReferenceUID='1.2.3.5'
    d.SOPInstanceUID=f'1.2.3.4.{instance}'
    d.PixelData=np.full((4,5),value,dtype=np.uint16).tobytes()
    return d


class GeometryTests(unittest.TestCase):
    def test_physical_sort_ignores_instance_and_thickness(self):
        hu,a,m=assemble([slice_at(1,110,1),slice_at(0,100,3),slice_at(.5,105,2)],min_slices=3)
        np.testing.assert_array_equal(hu[:,0,0],[-900,-895,-890])
        self.assertEqual(m['physical_z_spacing_mm'],.5)
        np.testing.assert_allclose(a[:3,:3],[[0,0,-3],[0,-2,0],[.5,0,0]])

    def test_per_slice_hu(self):
        hu,_,m=assemble([slice_at(0,100),slice_at(1,100,2,slope=2)],min_slices=2)
        np.testing.assert_array_equal(hu[:,0,0],[-900,-800])
        self.assertEqual(m['unique_slope_count'],2)

    def test_duplicate_position_rejected(self):
        with self.assertRaisesRegex(RejectedSeries,'duplicate_slice_positions'):
            assemble([slice_at(0,100),slice_at(0,101,2)],min_slices=2)

    def test_gap_rejected(self):
        with self.assertRaisesRegex(RejectedSeries,'nonuniform'):
            assemble([slice_at(z,100+i,i+1) for i,z in enumerate([0,1,2,4])],min_slices=3)

    def test_missing_geometry_not_guessed(self):
        ds=[slice_at(0,100),slice_at(1,101,2)];del ds[0].ImagePositionPatient
        with self.assertRaisesRegex(RejectedSeries,'missing_geometry'):
            assemble(ds,min_slices=2)

    def test_rgb_rejected(self):
        ds=[slice_at(0,100),slice_at(1,101,2)];ds[0].PhotometricInterpretation='RGB'
        with self.assertRaisesRegex(RejectedSeries,'color_or_rendered'):
            assemble(ds,min_slices=2)

    def test_tilt_preserved(self):
        ds=[slice_at(i,100+i,i+1) for i in range(3)]
        for i,d in enumerate(ds):d.ImagePositionPatient=[i*.2,0,i]
        _,a,_=assemble(ds,min_slices=3)
        np.testing.assert_allclose(a[:3,0],[-.2,0,1])

    def test_uid_does_not_change_duplicate_hash(self):
        ds=[slice_at(0,100),slice_at(1,101,2)]
        _,_,a=assemble(ds,min_slices=2)
        for d in ds:d.SeriesInstanceUID='1.2.9'
        _,_,b=assemble(ds,min_slices=2)
        self.assertEqual(a['hu_geometry_sha256'],b['hu_geometry_sha256'])

    def test_centered_ras_reverses_lps_axes(self):
        hu=np.arange(3*4*5,dtype=np.float32).reshape(3,4,5)
        affine=np.array([[0,0,-3,0],[0,-2,0,0],[1,0,0,0],[0,0,0,1]],float)
        output,m=resample(hu,affine,(5,4,3),(3,2,1))
        np.testing.assert_allclose(output,hu[:,::-1,::-1].transpose(0,2,1)/1000,atol=1e-6)
        self.assertEqual(m['padding_fraction'],0)

    def test_padding_mask_is_not_air_threshold(self):
        hu=np.full((3,3,3),-1000,dtype=np.float32);hu[1,1,1]=100
        a=np.eye(4)
        _,m=resample(hu,a,(5,5,5),(1,1,1))
        self.assertAlmostEqual(m['padding_fraction'],1-27/125)


if __name__=='__main__':unittest.main()
