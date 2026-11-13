'use strict';
// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 hrvtuirvw.
const test = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {LANGUAGES, perform, decode, journal} = require('./civ-locale.cjs');
const hex = code => {const b = Buffer.alloc(8); b.write(code, 'ascii'); return b.toString('hex');};

function fixture(options = {}) {
  const current = {region: options.region ?? 1, language: options.language ?? 'ja'};
  const calls = [], writes = [];
  let saved, created = false, lost = false, afterLoss = 0;
  const store = {
    create: async proof => {assert(!created, 'one-use collision'); created = true; saved = structuredClone(proof);},
    save: async proof => {saved = structuredClone(proof);}
  };
  const sm = {session: 'switch2-fixture', report: '/fixture/report',
    program: {result: 0}, export: {handle: 10},
    service: {name: 'pm:shell', result: 0, moves: [20]}};
  const memory = {info: {session: sm.session}, reportFile: sm.report, request: async body => {
    if (lost) afterLoss++;
    calls.push(structuredClone(body));
    if (body.command === 'root-native-info') return {session: sm.session,
      worker: {joined: !options.pendingWorker},
      services: [{name: 'pm:shell', handle: 20, sm: 10}]};
    if (body.command === 'root-native-sm-service') return body.name === 'set' ?
      {result: 0, moves: [100]} : options.denySetter ?
      {result: 0x1015, moves: []} : {result: 0, moves: [101]};
    if (body.command === 'root-native-close-handle') {
      if (options.closeLost) throw Error('close ACK lost');
      return {closed: body.handle};
    }
    assert.equal(body.command, 'root-native-ipc');
    if (body.handle === 100) {
      if (body.id === 0) return {result: 0, hex: hex(current.language)};
      if (body.id === 4) {
        const bytes = Buffer.alloc(4); bytes.writeUInt32LE(current.region);
        return {result: 0, hex: bytes.toString('hex')};
      }
      assert.equal(body.id, 2);
      const index = Buffer.from(body.hex, 'hex').readUInt32LE();
      let code = [...LANGUAGES, 'ja', 'en-US'][index];
      if (options.badIndex === index) code = index === 6 ? 'nl' : 'ko';
      return {result: 0, hex: hex(code)};
    }
    assert.equal(body.handle, 101);
    writes.push([body.id, body.hex]);
    if (body.id === 57) {
      current.region = Buffer.from(body.hex, 'hex').readUInt32LE();
      return {result: 0, hex: ''};
    }
    assert.equal(body.id, 0);
    if (options.rejectLanguage && body.hex === hex(options.rejectLanguage))
      return {result: 0x1234, hex: ''};
    current.language = decode({result: 0, hex: body.hex});
    if (options.loseAck) {lost = true; throw Error('setter acknowledgement lost');}
    return {result: 0, hex: ''};
  }};
  return {memory, sm, store, calls, writes, current, saved: () => saved,
    afterLoss: () => afterLoss};
}

test('all 20 current-boot mappings are read without opening set:sys', async () => {
  const f = fixture(); const proof = await perform(f.memory, f.sm, f.store, {operation: 'inspect'});
  assert.equal(proof.status, 'READ_ONLY_MAPPING_VERIFIED');
  assert.deepEqual(proof.mapping, [...LANGUAGES, 'ja', 'en-US']);
  assert(!f.calls.some(c => c.name === 'set:sys' || c.command === 'retire'));
  assert.deepEqual(f.calls.filter(c => c.command === 'root-native-close-handle').map(c => c.handle), [100]);
});
for (const code of LANGUAGES.filter(code => code !== 'ja')) {
  test('set ' + code + ' with region1 writes language once; FS stays held', async () => {
    const f = fixture(); const proof = await perform(f.memory, f.sm, f.store,
      {operation: 'set', language: code});
    assert.equal(proof.status, 'LANGUAGE_READBACK_FS_HELD');
    assert.deepEqual(f.writes, [[0, hex(code)]]);
    assert.deepEqual(proof.after, {region: 1, language: code});
    assert.equal(proof.endpointRetireRequested, false);
  });
}
test('region0 changes region before Korean; original is preserved for restore', async () => {
  const f = fixture({region: 0}); const proof = await perform(f.memory, f.sm, f.store,
    {operation: 'set', language: 'ko'});
  assert.deepEqual(f.writes, [[57, '01000000'], [0, hex('ko')]]);
  assert.deepEqual(proof.original, {region: 0, language: 'ja'});
});
for (const options of [{badIndex: 6}, {badIndex: 19}, {pendingWorker: true}]) {
  test('mismatched mapping or unjoined worker refuses before setter ' + JSON.stringify(options), async () => {
    const f = fixture(options);
    await assert.rejects(perform(f.memory, f.sm, f.store, {operation: 'set', language: 'ko'}));
    assert.deepEqual(f.writes, []);
    assert(!f.calls.some(c => c.name === 'set:sys'));
  });
}
test('denied settings service makes no write', async () => {
  const f = fixture({denySetter: true});
  await assert.rejects(perform(f.memory, f.sm, f.store, {operation: 'set', language: 'ko'}));
  assert.deepEqual(f.writes, []);
});
test('lost ACK never retries, rolls back, closes or retires', async () => {
  const f = fixture({loseAck: true});
  await assert.rejects(perform(f.memory, f.sm, f.store, {operation: 'set', language: 'ko'}),
    /setter acknowledgement lost/);
  assert.deepEqual(f.writes, [[0, hex('ko')]]);
  assert.equal(f.afterLoss(), 0);
  assert.equal(f.saved().status, 'CHANGE_UNCERTAIN_NO_REPLAY');
  assert(f.saved().pending && f.saved().handleCloseDeferred);
});
test('acknowledged rejection after region update restores observed original', async () => {
  const f = fixture({region: 0, rejectLanguage: 'ko'});
  await assert.rejects(perform(f.memory, f.sm, f.store, {operation: 'set', language: 'ko'}));
  assert.deepEqual(f.writes, [[57, '01000000'], [0, hex('ko')], [57, '00000000']]);
  assert.deepEqual(f.current, {region: 0, language: 'ja'});
  assert.equal(f.saved().status, 'ABORT_ORIGINAL_SETTINGS_RESTORED');
});
test('same-session restore requires the set receipt and undoes only its values', async () => {
  const f = fixture({region: 1, language: 'ko'});
  const previous = {kind: 'civ7-held-locale', operation: 'set',
    session: f.memory.info.session, report: f.memory.reportFile,
    status: 'LANGUAGE_READBACK_FS_HELD', target: {region: 1, language: 'ko'},
    original: {region: 0, language: 'ja'}};
  const proof = await perform(f.memory, f.sm, f.store, {operation: 'restore', previous});
  assert.deepEqual(f.writes, [[0, hex('ja')], [57, '00000000']]);
  assert.deepEqual(proof.after, {region: 0, language: 'ja'});
  assert(!f.calls.some(c => c.command === 'retire'));
});
test('restore refuses another session or changed settings without writing', async () => {
  for (const changed of [true, false]) {
    const f = fixture({language: changed ? 'fr' : 'ko'});
    const previous = {kind: 'civ7-held-locale', operation: 'set',
      session: changed ? f.memory.info.session : 'other', report: f.memory.reportFile,
      status: 'LANGUAGE_READBACK_FS_HELD', target: {region: 1, language: 'ko'},
      original: {region: 0, language: 'ja'}};
    await assert.rejects(perform(f.memory, f.sm, f.store, {operation: 'restore', previous}));
    assert.deepEqual(f.writes, []);
  }
});
test('journal collision rejects a second setting attempt before endpoint access', async () => {
  const f = fixture(); await perform(f.memory, f.sm, f.store, {operation: 'set', language: 'ko'});
  const before = f.calls.length;
  await assert.rejects(perform(f.memory, f.sm, f.store, {operation: 'set', language: 'fr'}),
    /one-use collision/);
  assert.equal(f.calls.length, before);
});
test('close ambiguity is reported, never full success', async () => {
  const f = fixture({closeLost: true});
  await assert.rejects(perform(f.memory, f.sm, f.store, {operation: 'set', language: 'ko'}),
    /close ACK lost/);
  assert.match(f.saved().status, /HANDLE_RELEASE_UNCERTAIN$/);
});
test('unknown, noncanonical, and unpadded language replies are rejected', () => {
  assert.equal(decode({result: 0, hex: hex('ko')}), 'ko');
  for (const raw of ['ebef000000000000', '6b6f6b6f6b6f6b6f', '7800000000000000',
    '6b6f00deadbeef01', '6b6f0', 'zz'.repeat(8)])
    assert.throws(() => decode({result: 0, hex: raw}));
});
test('CLI outside this CivSwitch runs directory refuses before endpoint import', () => {
  const process = spawnSync(global.process.execPath,
    [require.resolve('./civ-locale.cjs'), 'set', __dirname, '--language', 'ko'],
    {encoding: 'utf8', timeout: 4000});
  assert.equal(process.status, 1);
  assert.match(process.stderr, /Expected one CivSwitch run/);
  assert(!process.stderr.includes('ECONN'));
});
test('--help lists supported targets without opening a run or touching an endpoint', () => {
  const process = spawnSync(global.process.execPath,
    [require.resolve('./civ-locale.cjs'), '--help'],
    {encoding: 'utf8', timeout: 4000});
  assert.equal(process.status, 0, process.stderr);
  assert.match(process.stdout, /Usage: node civ-locale\.cjs inspect RUN/);
  assert.match(process.stdout, /Targets: en-US, fr, de, it, es, ko,/);
  assert.match(process.stdout, /Keep the game and PC launcher running/);
  assert.equal(process.stderr, '');
});
test('real receipt is private, durable and exclusive; duplicate never overwrites it', async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'civ-locale-receipt-'));
  try {
    const store = await journal(path.join(base, 'private'), 'set.json');
    await store.create({status: 'PREFLIGHT'});
    await store.save({status: 'LANGUAGE_READBACK_FS_HELD'});
    assert.equal((await fs.stat(store.file)).mode & 0o777, 0o600);
    assert.equal(JSON.parse(await fs.readFile(store.file)).status, 'LANGUAGE_READBACK_FS_HELD');
    await assert.rejects(store.create({status: 'DUPLICATE'}), {code: 'EEXIST'});
    assert.equal(JSON.parse(await fs.readFile(store.file)).status, 'LANGUAGE_READBACK_FS_HELD');
  } finally {await fs.rm(base, {recursive: true, force: true});}
});
test('stale or unverified run refuses before any endpoint import', async () => {
  const runs = path.join(__dirname, 'kit/port/engine/runs');
  await fs.mkdir(runs, {recursive: true});
  const run = await fs.mkdtemp(path.join(runs, 'switch2-'));
  try {
    await fs.writeFile(path.join(run, 'result.json'), JSON.stringify({verified: false, target: 'civ7'}));
    const result = spawnSync(global.process.execPath,
      [require.resolve('./civ-locale.cjs'), 'set', run, '--language', 'ko'],
      {encoding: 'utf8', timeout: 4000});
    assert.equal(result.status, 1);
    assert.match(result.stderr, /verified, still-held Civ7 FS run/);
    assert(!result.stderr.includes('ECONN'));
    assert.deepEqual(await fs.readdir(run), ['result.json']);
  } finally {await fs.rm(run, {recursive: true, force: true});}
});
test('ordinary CivSwitch CLI inspects, sets, restores and refuses replay with an isolated fake endpoint', async () => {
  const runs = path.join(__dirname, 'kit/port/engine/runs');
  await fs.mkdir(runs, {recursive: true});
  const run = await fs.mkdtemp(path.join(runs, 'switch2-'));
  const session = path.basename(run);
  const mockFile = path.join(run, 'mock-settings.json');
  const report = path.join(run, 'switch2/memory/report.json');
  const script = require.resolve('./civ-locale.cjs');
  try {
    await fs.mkdir(path.dirname(report), {recursive: true});
    await fs.mkdir(path.join(run, 'switch2/ro'), {recursive: true});
    await fs.mkdir(path.join(run, 'switch2/tools'), {recursive: true});
    await fs.writeFile(report, '{}');
    await fs.writeFile(mockFile, JSON.stringify({region: 0, language: 'ja'}));
    await fs.writeFile(path.join(run, 'result.json'), JSON.stringify({verified: true,
      target: 'civ7', fs: {verified: true, restored: true,
        retainedEndpoint: {ready: true, session}, cleanup: {deferred: true}},
      rpc: {mode: 'held', state: 'listening'}}));
    await fs.writeFile(path.join(run, 'switch2/ro', session + '-sm-proof.json'),
      JSON.stringify({session, report, program: {result: 0}, export: {handle: 10},
        service: {name: 'pm:shell', result: 0, moves: [20]}}));
    const fake = `const fs=require('node:fs/promises'),path=require('node:path');
const run=path.resolve(__dirname,'../..'),session=path.basename(run);
const report=path.join(run,'switch2/memory/report.json'),file=path.join(run,'mock-settings.json');
const codes=${JSON.stringify([...LANGUAGES, 'ja', 'en-US'])};
const hex=code=>{let b=Buffer.alloc(8);b.write(code,'ascii');return b.toString('hex');};
exports.connect=async()=>({info:{session},reportFile:report,request:async body=>{
 if(body.command==='root-native-info')return {session,worker:{joined:true},services:[{name:'pm:shell',handle:20,sm:10}]};
 if(body.command==='root-native-sm-service')return {result:0,moves:[body.name==='set'?100:101]};
 if(body.command==='root-native-close-handle')return {closed:body.handle};
 if(body.command!=='root-native-ipc')throw Error('Unexpected hardware command');
 const state=JSON.parse(await fs.readFile(file,'utf8'));
 if(body.handle===100){
  if(body.id===0)return {result:0,hex:hex(state.language)};
  if(body.id===4){let b=Buffer.alloc(4);b.writeUInt32LE(state.region);return {result:0,hex:b.toString('hex')};}
  if(body.id===2)return {result:0,hex:hex(codes[Buffer.from(body.hex,'hex').readUInt32LE()])};
 }
 if(body.handle!==101)throw Error('Unknown settings handle');
 if(body.id===0)state.language=Buffer.from(body.hex,'hex').toString('ascii').replace(/\\0+$/,'');
 else if(body.id===57)state.region=Buffer.from(body.hex,'hex').readUInt32LE();
 else throw Error('Unknown setter');
 await fs.writeFile(file,JSON.stringify(state));return {result:0,hex:''};
}});`;
    await fs.writeFile(path.join(run, 'switch2/tools/fs-memory.cjs'), fake);
    const command = (...args) => {
      const result = spawnSync(global.process.execPath, [script, ...args],
        {encoding: 'utf8', timeout: 5000});
      assert.equal(result.status, 0, result.stderr);
      return JSON.parse(result.stdout);
    };
    assert.equal(command('inspect', run).status, 'READ_ONLY_MAPPING_VERIFIED');
    assert.deepEqual(JSON.parse(await fs.readFile(mockFile)), {region: 0, language: 'ja'});
    assert.equal(command('set', run, '--language', 'ko').status, 'LANGUAGE_READBACK_FS_HELD');
    assert.deepEqual(JSON.parse(await fs.readFile(mockFile)), {region: 1, language: 'ko'});
    const receipt = path.join(run, 'locale', 'set-' + session + '.json');
    assert.equal((await fs.stat(receipt)).mode & 0o777, 0o600);
    assert.equal(command('restore', run, '--journal', receipt).status,
      'ORIGINAL_SETTINGS_RESTORED_FS_HELD');
    assert.deepEqual(JSON.parse(await fs.readFile(mockFile)), {region: 0, language: 'ja'});
    const repeat = spawnSync(global.process.execPath, [script, 'set', run, '--language', 'fr'],
      {encoding: 'utf8', timeout: 5000});
    assert.equal(repeat.status, 1);
    assert.match(repeat.stderr, /EEXIST/);
    assert.deepEqual(JSON.parse(await fs.readFile(mockFile)), {region: 0, language: 'ja'});
  } finally {await fs.rm(run, {recursive: true, force: true});}
});
