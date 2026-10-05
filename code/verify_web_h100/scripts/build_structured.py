#!/usr/bin/env python3
"""Build compact, visit-scoped web records directly from the canonical workbook."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import datetime
import openpyxl
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument('--workbook', type=Path, required=True)
parser.add_argument('--raw-web-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--preprocessor', type=Path, required=True)
args = parser.parse_args()
def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''): h.update(block)
    return h.hexdigest()
source_sha = sha(args.workbook)
spec = importlib.util.spec_from_file_location('ehr_builder', args.preprocessor)
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
targets = {(file.parent.parent.parent.name, file.parent.parent.name) for file in args.raw_web_root.glob('*/*/EHR/text.json')}
assert len(targets) == 184, 'Unexpected target visit count'
visit_ids = {visit for patient, visit in targets}
workbook = openpyxl.load_workbook(args.workbook, read_only=True, data_only=True)
frames = {}
order_ids = set()
for key in ['visits', 'orders', 'medicines', 'labs', 'procedures']:
    worksheet = workbook[builder.SHEETS[key]]
    rows = worksheet.iter_rows(values_only=True)
    seen = {}; headers = []
    for value in next(rows):
        name = str(value); number = seen.get(name, 0); seen[name] = number+1
        headers.append(name if not number else f'{name}.{number}')
    selector = 'YeuCauChiTiet_Id' if key == 'procedures' else 'sobenhan' if key == 'medicines' else 'SoBenhAn'
    position = headers.index(selector)
    selected = []; source_rows = []
    for source_row, row in enumerate(rows, 2):
        if builder.clean_key(row[position]) in (order_ids if key == 'procedures' else visit_ids):
            selected.append(row); source_rows.append(source_row)
    frames[key] = pd.DataFrame(selected, columns=headers, dtype=object)
    frames[key]['source_row'] = source_rows
    if key == 'orders': order_ids = set(frames[key].YeuCauChiTiet_Id.map(builder.clean_key))
    print(json.dumps({'sheet': worksheet.title, 'selected_source_rows': len(selected)}), flush=True)
workbook.close()
visits, visit_to_patient = builder.build_visits(frames)
actual = set(zip(visits.patient_id, visits.visit_id))
assert actual == targets, 'Workbook patient/visit IDs do not match the web target cohort'
tables = {'visits': visits, 'diagnoses': builder.build_diagnoses(frames, visit_to_patient),
          'medicines': builder.build_medicines(frames, visit_to_patient),
          'procedures': builder.build_procedures(frames, visit_to_patient)}
assert all(set(zip(df.patient_id, df.visit_id)) <= targets for df in tables.values())
for name, identity in [('diagnoses','diagnosis_id'),('medicines','medicine_id'),('procedures','procedure_id')]:
    assert not tables[name][identity].duplicated().any(), f'Duplicate {name} identity'
estimated = sum(len(df.sample(n=min(64,len(df)),random_state=0).to_json(orient='records',date_format='iso',force_ascii=False).encode()) / max(1,min(64,len(df))) * len(df) for df in [*tables.values(),frames['visits'],frames['medicines'],frames['orders'],frames['procedures']])
print(json.dumps({'estimated_json_bytes':round(estimated),'table_rows':{name:len(df) for name,df in tables.items()}}),flush=True)
if estimated > 64*1024*1024: raise SystemExit('Estimated export exceeds 64 MiB; review the design before exporting')
args.output.mkdir(parents=True,exist_ok=True); args.output.chmod(0o700)
(args.output/'tables').mkdir(exist_ok=True); (args.output/'records').mkdir(exist_ok=True)
for name,frame in tables.items(): frame.to_parquet(args.output/'tables'/f'{name}.parquet',index=False)
raw_visits = {builder.clean_key(row['SoBenhAn']):row for row in frames['visits'].to_dict('records')}
exclude = {'LanhDaoKhoa_Id','ThuTruongDonVi_Id','TenFileNew','PathFileNew','HinhVeHoacAnh'}
private = {'TenBenhNhan','ten_benh_nhan','DiaChi','thoihan_the','SoBHYT','BacSi','NguoiLienHe'}
def source_dict(row):
    return {key:builder._json_value(value) for key,value in row.items() if key not in private}
source_medicines = {}
for row in frames['medicines'].to_dict('records'):
    visit = builder.clean_key(row['sobenhan']); patient = visit_to_patient[visit]
    row = source_dict(row); row.update(patient_id=patient,visit_id=visit)
    row['status'] = 'returned' if builder.clean(row.get('LyDoTraThuoc')) else 'prescribed'
    source_medicines.setdefault((patient,visit),[]).append(row)
source_orders = {}
for row in frames['orders'].to_dict('records'):
    identity = builder.clean_key(row['YeuCauChiTiet_Id'])
    if identity in source_orders: assert builder.clean_key(source_orders[identity]['SoBenhAn']) == builder.clean_key(row['SoBenhAn']), 'Ambiguous order/admission linkage'
    source_orders[identity] = source_dict(row)
source_performed = {}
for row in frames['procedures'].to_dict('records'):
    source_performed.setdefault(builder.clean_key(row['YeuCauChiTiet_Id']),[]).append(source_dict(row))
json_tables = {name: json.loads(frame.to_json(orient='records',date_format='iso',force_ascii=False)) for name,frame in tables.items()}
grouped = {}
for name,rows in json_tables.items():
    grouped[name] = {}
    for row in rows:
        if name == 'procedures':
            row['source_fields'] = source_orders.get(row['order_id'],{})
            row['performed_source_fields'] = source_performed.get(row['order_id'],[])
        grouped[name].setdefault((row['patient_id'],row['visit_id']),[]).append(row)
total_bytes = 0
for patient,visit in sorted(targets):
    canonical = {key:builder._json_value(value) for key,value in raw_visits[visit].items() if key not in exclude}
    canonical = {key:value for key,value in canonical.items() if value is not None}
    record = {'patient_id':patient,'visit_id':visit,'demographics':grouped['visits'][(patient,visit)][0],
              'canonical_ehr':canonical, 'source_medicines':source_medicines.get((patient,visit),[]),
              **{name:grouped[name].get((patient,visit),[]) for name in ['diagnoses','medicines','procedures']}}
    directory=args.output/'records'/patient; directory.mkdir(exist_ok=True)
    payload=json.dumps(record,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    total_bytes+=len(payload); (directory/f'{visit}.json').write_bytes(payload)
assert sha(args.workbook)==source_sha, 'Raw workbook changed during preparation'
manifest={'raw_input_path':str(args.workbook.resolve()),'raw_input_sha256':source_sha,
          'builder_path':str(args.preprocessor.resolve()),'builder_sha256':sha(args.preprocessor),
          'script_sha256':sha(Path(__file__)),'output_path':str(args.output.resolve()),
          'patients':len({p for p,v in targets}),'visits':len(targets),
          'estimated_json_bytes':round(estimated),'actual_record_json_bytes':total_bytes,
          'table_rows':{name:len(df) for name,df in tables.items()},
          'source_medicine_rows':sum(map(len,source_medicines.values())),
          'source_performed_rows':sum(map(len,source_performed.values())),
          'omitted_direct_identity_fields':sorted(private | exclude),
          'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'record_files':[{'path':str(p.relative_to(args.output)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted((args.output/'records').rglob('*.json'))]}
(args.output/'targets.json').write_text(json.dumps(sorted(targets)))
(args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({key:value for key,value in manifest.items() if key!='record_files'}),flush=True)
