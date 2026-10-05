import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { inflateSync } from 'node:zlib';
import { buildSlicePreview, encodePng } from '../src/routes/imaging.js';
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'imaging-test-'));
after(() => fs.rmSync(dir, { recursive: true, force: true }));
function writeNpy(filename, values, shape=[2,2,2]) {
  const header=Buffer.from(`{'descr': '<i2', 'fortran_order': False, 'shape': (${shape.join(',')},), }\n`);
  const prefix=Buffer.from([147,78,85,77,80,89,1,0,0,0]); prefix.writeUInt16LE(header.length,8);
  const data=Buffer.alloc(values.length*2); values.forEach((v,i)=>data.writeInt16LE(v,i*2));
  fs.writeFileSync(filename,Buffer.concat([prefix,header,data]));
}
test('reads the selected slice and applies CT slope/intercept before windowing', () => {
  const npyPath=path.join(dir,'ct.npy'); writeNpy(npyPath,[0,0,0,0,0,500,1000,1500]);
  const preview=buildSlicePreview({npyPath,meta:{Modality:'CT',RescaleSlope:'2',RescaleIntercept:'-1000'}},1);
  assert.deepEqual([...Buffer.from(preview.pixels,'base64')],[0,128,255,255]);
  assert.equal(preview.sliceCount,2);
  const png=encodePng(preview); assert.deepEqual([...png.subarray(0,8)],[137,80,78,71,13,10,26,10]);
  let offset=8; const payload=[];
  while(offset<png.length){const length=png.readUInt32BE(offset);if(png.toString('ascii',offset+4,offset+8)==='IDAT')payload.push(png.subarray(offset+8,offset+8+length));offset+=length+12;}
  assert.deepEqual([...inflateSync(Buffer.concat(payload))],[0,0,128,0,255,255]);
});
test('window changes are reversible from source pixels; already rescaled CT is not rescaled twice', () => {
  const npyPath=path.join(dir,'rescaled.npy'); writeNpy(npyPath,[-1000,0,500,1000], [1,2,2]);
  const source={npyPath,meta:{Modality:'CT',RescaleSlope:'2',RescaleIntercept:'-1000',rescaled:true}};
  assert.deepEqual([...Buffer.from(buildSlicePreview(source,0).pixels,'base64')],[0,128,191,255]);
  assert.deepEqual([...Buffer.from(buildSlicePreview(source,0,{windowCenter:0,windowWidth:1000}).pixels,'base64')],[0,128,255,255]);
});
test('rejects truncated volumes instead of returning uninitialized pixel memory', () => {
  const npyPath=path.join(dir,'truncated.npy');writeNpy(npyPath,[1,2],[2,2,2]);
  assert.throws(()=>buildSlicePreview({npyPath,meta:{}},1),/không khớp/);
});
