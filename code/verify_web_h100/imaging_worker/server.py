"""Read selected DICOM frames from existing ZIPs without extracting the archive."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import io
import json
import math
import os
import threading
import zipfile

import numpy as np
from PIL import Image
import pydicom
from pydicom.pixels import pixel_array

RAW_ROOT = Path(os.environ.get('DICOM_ROOT', '/app/dicom')).resolve()
BUNDLE_ROOT = Path(os.environ.get('MODALITY_ROOT', '/app/modalities'))
CACHE = OrderedDict()
LOCK = threading.Lock()
SLOTS = threading.BoundedSemaphore(2)
METHODS = {}
MAX_MEMBER_BYTES = 1024 * 1024 * 1024
TAGS = ['PatientID', 'StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID', 'InstanceNumber', 'ImagePositionPatient', 'ImageOrientationPatient', 'NumberOfFrames', 'Rows', 'Columns', 'SamplesPerPixel', 'PhotometricInterpretation', 'RescaleSlope', 'RescaleIntercept', 'SharedFunctionalGroupsSequence', 'PerFrameFunctionalGroupsSequence']


def archive_path(relative):
    if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Invalid archive locator')
    path = (RAW_ROOT / relative).resolve()
    if not path.is_relative_to(RAW_ROOT) or path.suffix.lower() != '.zip':
        raise ValueError('Archive outside configured root')
    return path


def validate_identity(ds, item):
    return (str(ds.get('PatientID', '')) == item['patient_id'] and
            str(ds.get('StudyInstanceUID', '')) == item['metadata']['study_uid'] and
            str(ds.get('SeriesInstanceUID', '')) == item['metadata']['series_uid'])


def slice_sort_key(ds, member):
    try:
        orientation = np.asarray(ds.ImageOrientationPatient, dtype=float)
        position = np.asarray(ds.ImagePositionPatient, dtype=float)
        location = float(np.dot(np.cross(orientation[:3], orientation[3:]), position))
        if math.isfinite(location):
            return (0, location, float(ds.get('InstanceNumber', 0)), member)
    except (AttributeError, ValueError, TypeError):
        pass
    try:
        return (1, float(ds.get('InstanceNumber', 0)), 0, member)
    except (ValueError, TypeError):
        return (2, 0, 0, member)


def inventory(item):
    archives = [archive_path(value) for value in item.get('archives', [])]
    existing = [path for path in archives if path.is_file()]
    if not existing:
        raise FileNotFoundError('Ảnh DICOM của bộ này chưa có trong kho H100')
    fingerprint = tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in existing)
    key = (item['patient_id'], item['metadata']['study_uid'], item['metadata']['series_uid'], fingerprint)
    with LOCK:
        if key in CACHE:
            CACHE.move_to_end(key)
            return CACHE[key]
    frames = []
    seen = set()
    for archive in existing:
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if len(members) > 20_000:
                raise ValueError('Archive vượt giới hạn kiểm kê')
            for member in members:
                if member.is_dir() or member.file_size > MAX_MEMBER_BYTES or member.filename.startswith('__MACOSX/'):
                    continue
                try:
                    with z.open(member) as handle:
                        ds = pydicom.dcmread(handle, stop_before_pixels=True, specific_tags=TAGS)
                except pydicom.errors.InvalidDicomError:
                    continue
                if not validate_identity(ds, item) or not ds.get('Rows') or not ds.get('Columns'):
                    continue
                rows, columns = int(ds.Rows), int(ds.Columns)
                if max(rows, columns) > 8192 or rows*columns > 32_000_000:
                    raise ValueError('Lát DICOM vượt giới hạn hiển thị')
                count = int(ds.get('NumberOfFrames', 1))
                if not 1 <= count <= 50_000:
                    raise ValueError('Số frame không hợp lệ')
                for index in range(count):
                    identity = (str(ds.get('SOPInstanceUID', member.filename)), index)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    frames.append((slice_sort_key(ds, member.filename), str(archive), member.filename, index, rows, columns))
    frames.sort(key=lambda row: (row[0], row[3]))
    if not frames:
        raise FileNotFoundError('Không tìm thấy ảnh khớp PatientID, StudyUID và SeriesUID')
    if len(frames) > 50_000:
        raise ValueError('Series vượt giới hạn số frame')
    with LOCK:
        CACHE[key] = frames
        CACHE.move_to_end(key)
        while len(CACHE) > 32:
            CACHE.popitem(last=False)
    return frames


def rescale(ds, frame):
    slope, intercept = float(ds.get('RescaleSlope', 1)), float(ds.get('RescaleIntercept', 0))
    for group in [ds.get('SharedFunctionalGroupsSequence'), ds.get('PerFrameFunctionalGroupsSequence')]:
        if group:
            selected = group[frame] if group is ds.get('PerFrameFunctionalGroupsSequence') else group[0]
            transform = selected.get('PixelValueTransformationSequence')
            if transform:
                slope = float(transform[0].get('RescaleSlope', slope))
                intercept = float(transform[0].get('RescaleIntercept', intercept))
    return slope, intercept


def png(item, method, slice_index, options):
    frames = inventory(item)
    index = max(0, min(len(frames)-1, slice_index))
    _, archive, member, frame, _, _ = frames[index]
    with zipfile.ZipFile(archive) as z, z.open(member) as handle:
        ds = pydicom.dcmread(handle, stop_before_pixels=True, specific_tags=TAGS)
        if not validate_identity(ds, item):
            raise ValueError('Image identity changed')
        handle.seek(0)
        pixels = pixel_array(handle, index=frame)
    if pixels.ndim == 3 and pixels.shape[-1] in [3,4]:
        # The review viewer is grayscale; preserve source color as luminance.
        pixels = pixels[...,:3].astype(np.float64) @ np.array([.299,.587,.114])
    if pixels.ndim != 2 or not np.isfinite(pixels).all():
        raise ValueError('Không giải mã được một lát ảnh hợp lệ')
    values = pixels.astype(np.float64)
    if method == 'ct':
        slope, intercept = rescale(ds, frame)
        values = values*slope+intercept
    if not np.isfinite(values).all():
        raise ValueError('Giá trị pixel sau rescale không hữu hạn')
    if options.get('windowCenter') is not None or options.get('windowWidth') is not None:
        center, width = float(options['windowCenter']), float(options['windowWidth'])
        if not math.isfinite(center) or not math.isfinite(width) or width <= 0:
            raise ValueError('Window/level không hợp lệ')
        low, high = center-width/2, center+width/2
    else:
        low, high = (-1000,1000) if method == 'ct' else (float(values.min()),float(values.max()))
    if high <= low:
        high = low+1
    scaled = np.rint(np.clip((values-low)/(high-low),0,1)*255).astype(np.uint8)
    if str(ds.get('PhotometricInterpretation','')) == 'MONOCHROME1':
        scaled = 255-scaled
    image = Image.fromarray(scaled)
    if options.get('resolution') != 'original':
        image.thumbnail((640,640),Image.Resampling.BILINEAR)
    output = io.BytesIO()
    image.save(output,format='PNG')
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if not SLOTS.acquire(blocking=False):
            self.respond(503, b'{"error":"Image worker busy"}', 'application/json')
            return
        try:
            parsed = urlparse(self.path)
            if parsed.path == '/health':
                self.respond(200,b'{"ok":true}','application/json')
                return
            params = {key: values[0] for key,values in parse_qs(parsed.query).items()}
            method = params.get('method','')
            item = METHODS.get(method,{}).get(params.get('item',''))
            if not item:
                raise FileNotFoundError('Không có bộ ảnh trong nhánh retrieval này')
            if parsed.path == '/series':
                frames = inventory(item)
                data = dict(sliceCount=len(frames),shape=[len(frames),frames[0][4],frames[0][5]],label=item['metadata'].get('series_description') or item['id'])
                self.respond(200,json.dumps(data,ensure_ascii=False).encode(),'application/json')
            elif parsed.path == '/png':
                self.respond(200,png(item,method,int(params.get('slice','0')),params),'image/png')
            else:
                raise FileNotFoundError('Unknown image endpoint')
        except FileNotFoundError as error:
            self.respond(404,json.dumps({'error':str(error)},ensure_ascii=False).encode(),'application/json')
        except (ValueError, KeyError, zipfile.BadZipFile):
            self.respond(400,b'{"error":"Invalid DICOM image or parameters"}','application/json')
        except Exception as error:
            print(f'DICOM decoder error: {type(error).__name__}',flush=True)
            self.respond(422,b'{"error":"Unable to decode this DICOM frame"}','application/json')
        finally:
            SLOTS.release()

    def respond(self,status,payload,kind):
        try:
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError,ConnectionResetError):
            pass


def load_methods():
    import hashlib
    manifest=json.loads((BUNDLE_ROOT/'manifest.json').read_text())
    for method in manifest['methods']:
        if method['id'] not in ['ct','mri','xray']:
            continue
        path=BUNDLE_ROOT/method['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == method['sha256']
        data=json.loads(path.read_text())
        METHODS[method['id']]={item['id']:item for item in data['items']}


if __name__ == '__main__':
    load_methods()
    ThreadingHTTPServer(('0.0.0.0',4002),Handler).serve_forever()
