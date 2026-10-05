import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { spawnSync } from 'node:child_process';
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'db-test-'));
after(()=>fs.rmSync(dir,{recursive:true,force:true}));
const database=new URL('../src/data/database.js',import.meta.url).href;
function run(source,root=dir){return spawnSync(process.execPath,['--input-type=module','-e',source],{env:{...process.env,DATA_DIR:root},encoding:'utf8'});}
test('migration preserves legacy stores, commits review history and survives restart without reimport',()=>{
  const legacy=JSON.stringify({'q:c':{status:'similar',reviewer:'legacy'}});
  fs.writeFileSync(path.join(dir,'verifications.json'),legacy);
  let r=run(`import {db,readDocument,saveDocument} from ${JSON.stringify(database)};
    if(readDocument('reviews','q:c').status!=='similar')process.exit(1);
    saveDocument('reviews','q:c',{overall_similarity:3,reviewer:'doctor1'},true);
    saveDocument('reviews','q:c',{overall_similarity:4,reviewer:'doctor2'},true);
    if(db.prepare('SELECT count(*) n FROM review_history').get().n!==3)process.exit(2);
    if(db.prepare('PRAGMA integrity_check').get().integrity_check!=='ok')process.exit(3);`);
  assert.equal(r.status,0,r.stderr);
  r=run(`import {db,readDocument} from ${JSON.stringify(database)};
    if(readDocument('reviews','q:c').overall_similarity!==4)process.exit(1);
    if(db.prepare('SELECT count(*) n FROM review_history').get().n!==3)process.exit(2);`);
  assert.equal(r.status,0,r.stderr);
  assert.equal(fs.readFileSync(path.join(dir,'verifications.json'),'utf8'),legacy);
});
test('malformed legacy review file fails instead of silently resetting reviews',()=>{
  const broken=path.join(dir,'broken');fs.mkdirSync(broken);
  fs.writeFileSync(path.join(broken,'verifications.json'),'{invalid');
  assert.notEqual(run(`await import(${JSON.stringify(database)})`,broken).status,0);
});
