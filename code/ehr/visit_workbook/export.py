"""Full, lossless visit-level XLSX built directly from raw EHR; run on Vaipe."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import sqlite3
import sys
import zlib

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

RAW = Path('/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx')
MAIN = 'thông tin bệnh án'
ORDERS = 'chỉ định DVKT'
MEDS = 'Thuốc'
RESULTS = 'KQCLS'
SURGERY = 'Phẫu thuật thủ thuật'
SHEETS = [MAIN, ORDERS, MEDS, RESULTS, SURGERY]
LIMIT = 30000  # UTF-16 code units; safely below Excel's 32767 limit.
LIST_NAMES = {ORDERS: 'ChiDinhDVKT_json', MEDS: 'Thuoc_json', SURGERY: 'PhauThuatThuThuat_json'}
EXTRA = ['TenBenhNhan', 'NamSinh', 'GioiTinh_ma_DVKT', 'GioiTinh_Thuoc',
         'NhanKhauNhieuGiaTri_json', 'SoChiDinhDVKT', 'SoDongThuoc', 'SoKetQuaKQCLS',
         'SoPhauThuatThuThuat', 'SoDongNguonBenhAn']


def dumps(v):
    return json.dumps(v, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def save_json(p, v):
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def encode(v):
    if isinstance(v, (datetime, date, time)):
        return {'__type__': type(v).__name__, 'value': v.isoformat()}
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError('Nonfinite source number; refusing silent conversion')
    return v


def decode(v):
    if isinstance(v, dict) and '__type__' in v:
        return {'datetime': datetime, 'date': date, 'time': time}[v['__type__']].fromisoformat(v['value'])
    return v


def key(v):
    if v is None:
        return ''
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if float(v).is_integer():
            return str(int(v))
    s = str(v).strip()
    if s.casefold() in ('', 'null', 'none', 'nan'):
        return ''
    return re.sub(r'^(\d+)\.0$', r'\1', s)


def unique_headers(headers):
    seen = Counter()
    result = []
    for i, h in enumerate(headers, 1):
        name = str(h) if h is not None else f'Cot_{i}'
        seen[name] += 1
        result.append(name if seen[name] == 1 else f'{name}::__cot_{seen[name]}')
    assert len(result) == len(set(result)), 'Header occurrence collision'
    return result


def utf16len(s):
    return len(s.encode('utf-16-le')) // 2


def split_text(s, limit=LIMIT):
    parts, start, units = [], 0, 0
    for i, ch in enumerate(s):
        cost = 2 if ord(ch) > 0xffff else 1
        if units + cost > limit:
            parts.append(s[start:i])
            start, units = i, 0
        units += cost
    parts.append(s[start:])
    return parts


def part_name(h, n):
    return h if n == 0 else f'{h}::__phan_{n+1}'


def logical_group(sheet, vals, schemas):
    if sheet == RESULTS:
        label = vals[schemas[sheet]['unique_headers'].index('TEN_CHI_SO')]
        return 'KQCLS::' + (str(label) if label is not None else '(trống)')
    return LIST_NAMES[sheet]


def resolve_link(sheet, visit, order_id, order_map, cohort):
    candidates = []
    if sheet == SURGERY:
        candidates = sorted(order_map.get(order_id, set())) if order_id else []
        visit = candidates[0] if len(candidates) == 1 else ''
        reason = 'ma_chi_dinh_khong_duy_nhat' if len(candidates) > 1 else ('khong_noi_duoc_ma_chi_dinh' if not visit else '')
    else:
        reason = '' if visit else 'thieu_ma_benh_an'
    if not reason and visit not in cohort:
        reason = 'benh_an_ngoai_bang_chinh'
    return visit, reason, candidates


def rows(db, visit=None, exceptions=False):
    if exceptions:
        return db.execute('SELECT sheet,source_row,payload,reason,candidates FROM source WHERE reason<>? ORDER BY sheet,source_row', ('',))
    return db.execute('SELECT sheet,source_row,payload FROM source WHERE visit=? AND reason=? ORDER BY sheet,source_row', (visit, ''))


def build_row(db, visit, schemas):
    source = list(rows(db, visit))
    main = [(n, json.loads(p)) for s, n, p in source if s == MAIN]
    assert len(main) == 1, 'Main source visit must be unique'
    source_row, values = main[0]
    row = dict(zip(schemas[MAIN]['unique_headers'], (decode(v) for v in values)))
    # IDs are deliberately stored as text; original values remain in the snapshot.
    row['SoBenhAn'] = visit
    row['SoVaoVien'] = key(row['SoVaoVien'])
    row['SoDongNguonBenhAn'] = source_row
    groups, demo, counts = defaultdict(list), defaultdict(dict), Counter()
    patient = row['SoVaoVien']
    for sheet, n, p in source:
        if sheet == MAIN:
            continue
        vals = json.loads(p)
        counts[sheet] += 1
        groups[logical_group(sheet, vals, schemas)].append([n] + vals)
        heads = schemas[sheet]['unique_headers']
        if sheet in (ORDERS, MEDS):
            lookup = dict(zip(heads, vals))
            if sheet == ORDERS and key(lookup.get('SoVaoVien')) not in ('', patient):
                continue
            for field in ['TenBenhNhan', 'NamSinh', 'GioiTinh']:
                if field not in lookup or key(lookup[field]) == '':
                    continue
                target = field if field != 'GioiTinh' else ('GioiTinh_ma_DVKT' if sheet == ORDERS else 'GioiTinh_Thuoc')
                demo[target][dumps(lookup[field])] = lookup[field]
    conflicts = {}
    for field in EXTRA[:4]:
        candidates = list(demo[field].values())
        row[field] = decode(candidates[0]) if len(candidates) == 1 else None
        if len(candidates) > 1:
            conflicts[field] = candidates
    row['NhanKhauNhieuGiaTri_json'] = dumps(conflicts) if conflicts else None
    for s, h in [(ORDERS, 'SoChiDinhDVKT'), (MEDS, 'SoDongThuoc'), (RESULTS, 'SoKetQuaKQCLS'), (SURGERY, 'SoPhauThuatThuThuat')]:
        row[h] = counts[s]
    row.update({h: dumps(records) for h, records in groups.items()})
    return row


def physical(row, logical, parts):
    out = []
    for h in logical:
        v = row.get(h)
        chunks = split_text(v) if isinstance(v, str) else [v]
        assert len(chunks) <= parts[h], 'Column plan insufficient'
        out.extend(chunks + [None] * (parts[h] - len(chunks)))
    return out


def prepare(run, raw):
    run.mkdir(parents=True, exist_ok=False)
    structured = run / 'structured'
    structured.mkdir()
    raw_hash = sha(raw)
    db = sqlite3.connect(structured / 'source.sqlite')
    db.execute('CREATE TABLE source(sheet TEXT,source_row INTEGER,visit TEXT,order_id TEXT,payload TEXT,reason TEXT,candidates TEXT,PRIMARY KEY(sheet,source_row))')
    schemas, counts, formula_count = {}, {}, 0
    wb = load_workbook(raw, read_only=True, data_only=False)
    assert wb.sheetnames == SHEETS, 'Unexpected source sheet contract'
    visits = []
    for sheet in SHEETS:
        print(dumps({'phase': 'read_raw', 'sheet': sheet}), flush=True)
        it = wb[sheet].iter_rows()
        header_cells = next(it)
        original_headers = [c.value for c in header_cells]
        heads = unique_headers(original_headers)
        schemas[sheet] = {'original_headers': original_headers, 'unique_headers': heads,
                          'list_fields': ['source_row'] + heads}
        count = 0
        for n, cells in enumerate(it, 2):
            vals = [encode(c.value) for c in cells]
            if all(v is None for v in vals):
                continue
            formula_count += sum(c.data_type == 'f' for c in cells)
            lookup = dict(zip(heads, vals))
            visit = key(lookup.get('SoBenhAn', lookup.get('sobenhan')))
            order_id = key(lookup.get('YeuCauChiTiet_Id'))
            reason = ''
            if sheet == MAIN:
                assert visit and visit not in visits, 'Missing/duplicate main visit ID'
                visits.append(visit)
            db.execute('INSERT INTO source VALUES(?,?,?,?,?,?,?)', (sheet, n, visit, order_id, dumps(vals), reason, '[]'))
            count += 1
            if count % 10000 == 0:
                db.commit()
        db.commit()
        counts[sheet] = count
        print(dumps({'phase': 'raw_sheet_saved', 'sheet': sheet, 'rows': count}), flush=True)
    wb.close()
    db.execute('CREATE INDEX by_visit ON source(visit,reason)')
    db.execute('CREATE INDEX by_order ON source(order_id,sheet)')
    cohort = set(visits)
    order_map = defaultdict(set)
    for s, v, oid in db.execute('SELECT sheet,visit,order_id FROM source WHERE sheet IN (?,?)', (ORDERS, RESULTS)):
        if oid and v:
            order_map[oid].add(v)
    statuses = Counter()
    updates = []
    for s, n, v, oid in db.execute('SELECT sheet,source_row,visit,order_id FROM source'):
        v, reason, candidates = resolve_link(s, v, oid, order_map, cohort)
        statuses[(s, reason or 'linked')] += 1
        updates.append((v, reason, dumps(candidates), s, n))
    db.executemany('UPDATE source SET visit=?,reason=?,candidates=? WHERE sheet=? AND source_row=?', updates)
    db.commit()
    save_json(structured / 'schema.json', schemas)
    main_heads = schemas[MAIN]['unique_headers']
    leading = ['SoBenhAn', 'SoVaoVien'] + EXTRA
    assert not set(EXTRA) & set(main_heads), 'Derived/main header collision'
    result_heads = set()
    for p, in db.execute('SELECT payload FROM source WHERE sheet=? AND reason=?', (RESULTS, '')):
        result_heads.add(logical_group(RESULTS, json.loads(p), schemas))
    logical = leading + [h for h in main_heads if h not in leading] + [LIST_NAMES[ORDERS], LIST_NAMES[MEDS], LIST_NAMES[SURGERY]] + sorted(result_heads)
    assert len(logical) == len(set(logical)), 'Column collision'
    parts = dict.fromkeys(logical, 1)
    sample_ids = set(sorted(visits, key=lambda v: hashlib.sha256(v.encode()).digest())[:200])
    sample_sizes, largest = [], 0
    for i, v in enumerate(visits, 1):
        row = build_row(db, v, schemas)
        for h, value in row.items():
            if isinstance(value, str):
                parts[h] = max(parts[h], len(split_text(value)))
        if v in sample_ids:
            sample_sizes.append(len(zlib.compress(dumps([encode(row.get(h)) for h in logical]).encode())))
        largest = max(largest, sum(utf16len(x) for x in row.values() if isinstance(x, str)))
        if i % 500 == 0:
            print(dumps({'phase': 'plan_columns', 'visits': i}), flush=True)
    ncolumns = sum(parts.values())
    assert ncolumns <= 16384
    plan = {'visits': visits, 'logical_columns': logical, 'parts': parts}
    save_json(run / 'column_plan.json', plan)
    estimate = math.ceil(sum(sample_sizes) / len(sample_sizes) * len(visits) * 1.8)
    exception_count = sum(n for (s, status), n in statuses.items() if status != 'linked')
    # Account for orphan source payload using compressed snapshot records.
    exception_bytes = sum(len(zlib.compress(p.encode())) for p, in db.execute('SELECT payload FROM source WHERE reason<>?', ('',)))
    preflight = {'planned_visits': len(visits), 'planned_columns': ncolumns, 'logical_columns': len(logical),
                 'sample_visits': len(sample_ids), 'estimated_xlsx_bytes': estimate + exception_bytes * 2,
                 'exceptions': exception_count, 'largest_visit_text_utf16_units': largest,
                 'source_rows': counts, 'source_formula_cells': formula_count,
                 'linkage_counts': [{'sheet': s, 'status': st, 'rows': n} for (s, st), n in statuses.items()]}
    save_json(run / 'preflight.json', preflight)
    db.close()
    assert sha(raw) == raw_hash, 'Raw source changed'
    save_json(run / 'source_manifest.json', {'host': socket.gethostname(), 'raw_input_path': str(raw),
        'raw_input_sha256': raw_hash, 'source_rows': counts,
        'snapshot_sha256': sha(structured / 'source.sqlite'), 'schema_sha256': sha(structured / 'schema.json'),
        'created_utc': datetime.now(timezone.utc).isoformat(), 'script_sha256': sha(__file__)})
    print(dumps(preflight), flush=True)


def cell(ws, v, h=''):
    if v is None:
        return None
    c = WriteOnlyCell(ws, v)
    if isinstance(v, str):
        assert utf16len(v) <= LIMIT
        c.data_type = 's'  # Source strings starting '=' remain literal.
        if h in ('SoBenhAn', 'SoVaoVien'):
            c.number_format = '@'
    elif isinstance(v, datetime):
        c.number_format = 'dd/mm/yyyy hh:mm:ss'
    elif isinstance(v, date):
        c.number_format = 'dd/mm/yyyy'
    elif isinstance(v, time):
        c.number_format = 'hh:mm:ss'
    return c


def configure(ws, headers, row_count, freeze='C2'):
    ws.freeze_panes = freeze
    ws.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{row_count+1}'
    ws.row_dimensions[1].height = 45
    for i, h in enumerate(headers, 1):
        width = 20
        if h == 'TenBenhNhan':
            width = 30
        elif 'json' in h or h.startswith('KQCLS::'):
            width = 48
        elif h in ('NgayVaoVien', 'NgayRaVien'):
            width = 23
        ws.column_dimensions[get_column_letter(i)].width = width
    cells = [cell(ws, h) for h in headers]
    for c in cells:
        c.alignment = Alignment(wrap_text=True, vertical='top')
    ws.append(cells)


def canonical(values):
    # Excel numeric storage can represent an integral float as an integer.
    return dumps([encode(v) for v in values])


def equivalent(actual, expected):
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if isinstance(expected, datetime):
        return actual == expected
    if isinstance(expected, date):
        return (actual.date() if isinstance(actual, datetime) else actual) == expected
    return actual == expected


def export(run, max_bytes):
    manifest = json.loads((run / 'source_manifest.json').read_text())
    preflight = json.loads((run / 'preflight.json').read_text())
    assert preflight['estimated_xlsx_bytes'] <= max_bytes, 'Preflight exceeds reviewed output budget'
    raw = Path(manifest['raw_input_path'])
    assert sha(raw) == manifest['raw_input_sha256']
    dbpath = run / 'structured/source.sqlite'
    assert sha(dbpath) == manifest['snapshot_sha256']
    assert sha(run / 'structured/schema.json') == manifest['schema_sha256']
    db = sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True)
    schemas = json.loads((run / 'structured/schema.json').read_text())
    plan = json.loads((run / 'column_plan.json').read_text())
    logical, parts, visits = plan['logical_columns'], plan['parts'], plan['visits']
    headers = [part_name(h, n) for h in logical for n in range(parts[h])]
    assert len(headers) == len(set(headers))
    target = run / 'benh_an_day_du_moi_visit.xlsx'
    assert not target.exists(), 'Refusing overwrite'
    temporary = target.with_suffix('.partial.xlsx')
    wb = Workbook(write_only=True)
    ws = wb.create_sheet('Visits')
    configure(ws, headers, len(visits))
    for i, v in enumerate(visits, 1):
        vals = physical(build_row(db, v, schemas), logical, parts)
        ws.append([cell(ws, value, h) for h, value in zip(headers, vals)])
        if i % 500 == 0:
            print(dumps({'phase': 'write_visits', 'rows': i}), flush=True)
    exception_rows = list(rows(db, exceptions=True))
    exception_parts = max([1] + [len(split_text(dumps([n] + json.loads(p)))) for s, n, p, reason, candidates in exception_rows])
    exc_headers = ['BangNguon', 'DongExcelNguon', 'LyDo', 'VisitUngVien_json'] + [part_name('DuLieuNguon_json', n) for n in range(exception_parts)]
    if exception_rows:
        exc = wb.create_sheet('Ngoai_le')
        configure(exc, exc_headers, len(exception_rows), 'C2')
        for s, n, p, reason, candidates in exception_rows:
            chunks = split_text(dumps([n] + json.loads(p)))
            vals = [s, n, reason, candidates] + chunks + [None] * (exception_parts - len(chunks))
            exc.append([cell(exc, value) for value in vals])
    guide = wb.create_sheet('Cau_truc')
    guide.column_dimensions['A'].width = 33
    guide.column_dimensions['B'].width = 32
    guide.column_dimensions['C'].width = 100
    guide.freeze_panes = 'A2'
    guide_rows = [
        ['Nội dung', 'Vị trí', 'Giải thích'],
        ['Đơn vị', 'Visits', 'Mỗi dòng là một SoBenhAn. SoVaoVien là mã bệnh nhân.'],
        ['Danh sách', 'Các cột _json và KQCLS::', 'JSON gồm các mảng bản ghi. Phần tử đầu tiên là số dòng Excel nguồn, các phần tử sau theo thứ tự trường dưới đây.'],
        ['Ô dài', '::__phan_2, ::__phan_3...', 'Nối với cột gốc theo thứ tự số phần trước khi đọc JSON. Không bỏ hoặc lấy trung bình các lần lặp.'],
        ['Ngày trong danh sách', 'Đối tượng __type__, value', 'Ngày/giờ giữ dạng ISO và loại gốc datetime/date/time. Null JSON là ô nguồn trống; chuỗi NULL nguyên bản vẫn là chuỗi.'],
        ['Ngoại lệ', 'Ngoai_le nếu có', 'Dòng thiếu mã bệnh án, ngoài bảng chính hoặc không nối được phẫu thuật được giữ đủ, không tự gán sang visit khác. Không có tab này khi tất cả dòng đều nối được.'],
        ['Phẫu thuật', 'PhauThuatThuThuat_json', 'Chỉ nối bằng YeuCauChiTiet_Id khi toàn bộ bằng chứng chỉ định/kết quả trả về duy nhất một visit trong bảng chính.'],
        ['Nhân khẩu', 'Các cột đầu', 'Chỉ hiển thị giá trị duy nhất. Mâu thuẫn giữ trong NhanKhauNhieuGiaTri_json và bản ghi nguồn. Mã/nhãn giới tính từ hai nguồn tách riêng.'],
        ['Cột nguồn trùng tên', '::__cot_2...', 'Giữ riêng từng cột theo thứ tự gốc; không ghi đè hai cột cùng tên.'],
        ['Nguồn', str(raw), manifest['raw_input_sha256']],
    ]
    for sheet in SHEETS:
        prefix = 'Cột thông tin bệnh án' if sheet == MAIN else ('KQCLS::<TEN_CHI_SO>' if sheet == RESULTS else LIST_NAMES[sheet])
        if sheet != MAIN:
            guide_rows.append([sheet, prefix, 'Phần tử 0: source_row'])
        for i, (original, unique) in enumerate(zip(schemas[sheet]['original_headers'], schemas[sheet]['unique_headers']), 1):
            guide_rows.append([sheet, str(i), f'{original} => {unique}'])
    for row_index, vals in enumerate(guide_rows, 1):
        guide_cells = [cell(guide, v) for v in vals]
        for c in guide_cells:
            c.alignment = Alignment(wrap_text=True, vertical='top')
        guide.row_dimensions[row_index].height = 45 if row_index <= 10 else 30
        guide.append(guide_cells)
    print(dumps({'phase': 'save_xlsx'}), flush=True)
    wb.save(temporary)
    assert temporary.stat().st_size <= max_bytes, 'Output exceeds reviewed budget; partial retained'
    print(dumps({'phase': 'verify_saved_xlsx'}), flush=True)
    checked = load_workbook(temporary, read_only=True, data_only=False)
    assert checked.sheetnames == ['Visits'] + (['Ngoai_le'] if exception_rows else []) + ['Cau_truc']
    it = checked['Visits'].iter_rows(max_col=len(headers), values_only=True)
    assert list(next(it)) == headers
    seen, membership, checked_cells = set(), Counter(), 0
    for i, actual in enumerate(it):
        assert i < len(visits)
        v = visits[i]
        expected_row = build_row(db, v, schemas)
        expected = physical(expected_row, logical, parts)
        assert all(equivalent(a, e) for a, e in zip(actual, expected)), f'Content mismatch at output row {i+2}'
        assert actual[0] == v and v not in seen
        seen.add(v)
        checked_cells += len(actual)
        offset = 0
        restored = {}
        for h in logical:
            chunk = actual[offset:offset+parts[h]]
            restored[h] = ''.join(x or '' for x in chunk) if isinstance(expected_row.get(h), str) else chunk[0]
            offset += parts[h]
        output_members = Counter()
        for h in logical:
            sheet = RESULTS if h.startswith('KQCLS::') else next((s for s, name in LIST_NAMES.items() if h == name), None)
            if sheet and restored[h]:
                for record in json.loads(restored[h]):
                    output_members[(sheet, record[0], dumps(record[1:]))] += 1
        expected_members = Counter((s, n, p) for s, n, p in rows(db, v) if s != MAIN)
        assert output_members == expected_members, 'Source row membership/content mismatch'
        membership.update(s for s, n, p in expected_members.elements())
        membership[MAIN] += 1
        if (i+1) % 500 == 0:
            print(dumps({'phase': 'verified_visits', 'rows': i+1}), flush=True)
    assert len(seen) == len(visits)
    exc_count = 0
    if exception_rows:
        eit = checked['Ngoai_le'].iter_rows(max_col=len(exc_headers), values_only=True)
        assert list(next(eit)) == exc_headers
        for actual in eit:
            s, n, p, reason, candidates = exception_rows[exc_count]
            assert list(actual[:4]) == [s, n, reason, candidates]
            assert json.loads(''.join(x or '' for x in actual[4:])) == [n] + json.loads(p)
            membership[s] += 1
            exc_count += 1
    assert exc_count == len(exception_rows)
    assert dict(membership) == manifest['source_rows'], 'Not every raw row is represented exactly once'
    assert [list(r) for r in checked['Cau_truc'].iter_rows(max_col=3, values_only=True)] == guide_rows
    checked.close()
    db.close()
    assert sha(raw) == manifest['raw_input_sha256'], 'Raw workbook changed'
    temporary.rename(target)
    result = {**manifest, 'output_path': str(target), 'output_bytes': target.stat().st_size,
              'output_sha256': sha(target), 'rows': len(visits), 'columns': len(headers),
              'exception_rows': exc_count, 'source_membership_verified': dict(membership),
              'sheets': ['Visits'] + (['Ngoai_le'] if exception_rows else []) + ['Cau_truc'],
              'checked_cells': checked_cells, 'all_cells_and_source_rows_verified': True,
              'unique_visit_ids': True, 'raw_unchanged': True, 'identifiers_as_text': True,
              'no_generated_formulas': True, 'script_sha256': sha(__file__),
              'command': sys.argv, 'completed_utc': datetime.now(timezone.utc).isoformat()}
    save_json(run / 'manifest.json', result)
    print(dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'export'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--raw', type=Path, default=RAW)
    parser.add_argument('--max-bytes', type=int, default=150000000)
    args = parser.parse_args()
    if args.phase == 'prepare':
        prepare(args.output, args.raw)
    else:
        export(args.output, args.max_bytes)
