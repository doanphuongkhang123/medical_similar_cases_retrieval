import io
import tempfile
import unittest
from pathlib import Path
import zipfile

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
from PIL import Image
import server


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        server.RAW_ROOT = Path(self.temporary.name)
        server.CACHE.clear()
        self.item = dict(patient_id='test-patient', metadata=dict(study_uid='1.2.3.4',series_uid='1.2.3.5'), archives=['CT/test.zip'])
        (server.RAW_ROOT/'CT').mkdir()
        with zipfile.ZipFile(server.RAW_ROOT/'CT/test.zip','w') as archive:
            for i in [2,0,1]:
                archive.writestr(f'frame-{i}.dcm',self.dicom(i))
            archive.writestr('wrong-patient.dcm',self.dicom(3,'other-patient'))
            archive.writestr('README.txt',b'not DICOM')

    def tearDown(self):
        self.temporary.cleanup()

    def dicom(self,index,patient='test-patient',multi=False):
        meta=FileMetaDataset()
        meta.TransferSyntaxUID=ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID=SecondaryCaptureImageStorage
        meta.MediaStorageSOPInstanceUID=generate_uid()
        ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
        ds.SOPClassUID=meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID=meta.MediaStorageSOPInstanceUID
        ds.PatientID=patient;ds.StudyInstanceUID='1.2.3.4';ds.SeriesInstanceUID='1.2.3.5'
        ds.Rows=10;ds.Columns=20;ds.SamplesPerPixel=1;ds.PhotometricInterpretation='MONOCHROME2'
        ds.BitsAllocated=16;ds.BitsStored=16;ds.HighBit=15;ds.PixelRepresentation=0
        ds.InstanceNumber=index+1;ds.ImagePositionPatient=[0,0,index];ds.ImageOrientationPatient=[1,0,0,0,1,0]
        ds.RescaleSlope=2;ds.RescaleIntercept=-1000
        array=(np.arange(200).reshape(10,20)+index*200).astype(np.uint16)
        if multi:
            ds.NumberOfFrames=2
            array=np.stack([array,array+200])
        ds.PixelData=array.tobytes()
        output=io.BytesIO();pydicom.dcmwrite(output,ds,enforce_file_format=True)
        return output.getvalue()

    def test_identity_order_and_png(self):
        frames=server.inventory(self.item)
        self.assertEqual(len(frames),3)
        self.assertEqual([f[2] for f in frames],['frame-0.dcm','frame-1.dcm','frame-2.dcm'])
        first=server.png(self.item,'ct',0,{})
        last=server.png(self.item,'ct',2,{})
        self.assertNotEqual(first,last)
        image=Image.open(io.BytesIO(first))
        self.assertEqual(image.size,(20,10))
        self.assertEqual(image.mode,'L')
        self.assertNotEqual(first,server.png(self.item,'ct',0,dict(windowCenter=40,windowWidth=400)))

    def test_multiframe_reads_selected_frame(self):
        with zipfile.ZipFile(server.RAW_ROOT/'CT/test.zip','w') as archive:
            archive.writestr('multi.dcm',self.dicom(0,multi=True))
        frames=server.inventory(self.item)
        self.assertEqual(len(frames),2)
        self.assertNotEqual(server.png(self.item,'ct',0,{}),server.png(self.item,'ct',1,{}))

    def test_rejects_path_escape_wrong_identity_and_invalid_window(self):
        for relative in ['../secret.zip','/tmp/secret.zip']:
            with self.assertRaises(ValueError):server.archive_path(relative)
        wrong={**self.item,'patient_id':'unknown-patient'}
        with self.assertRaises(FileNotFoundError):server.inventory(wrong)
        with self.assertRaises(ValueError):server.png(self.item,'ct',0,dict(windowCenter=40,windowWidth=0))


if __name__=='__main__':unittest.main()
