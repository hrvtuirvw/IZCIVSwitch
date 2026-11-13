#!/usr/bin/env node
'use strict';
// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 hrvtuirvw.
// CivSwitch/Civilization VII retained-FS settings helper. This never acquires
// FS, drives console buttons, touches save files, or retires the FS endpoint.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

// FW 23.0.1 conversion-table codes; verify *all* entries on this boot before
// opening set:sys. The separate legacy compatibility table has other indices.
const LANGUAGES = Object.freeze([
  'ja', 'en-US', 'fr', 'de', 'it', 'es', 'ko', 'nl', 'pt', 'ru',
  'en-GB', 'fr-CA', 'es-419', 'zh-Hans', 'zh-Hant', 'pt-BR', 'pl', 'th'
]);
const EXPECTED = [...LANGUAGES, 'ja', 'en-US'];
const assert = (condition, reason) => { if (!condition) throw Error(reason); };
const encoded = code => {
  assert(LANGUAGES.includes(code), 'Unsupported language: ' + String(code));
  const bytes = Buffer.alloc(8);
  bytes.write(code, 'ascii');
  return bytes.toString('hex');
};
const decode = reply => {
  assert(reply && !reply.transport && reply.result === 0 &&
    typeof reply.hex === 'string' && /^[0-9a-f]{16,}$/i.test(reply.hex),
  'Invalid LanguageCode response');
  const bytes = Buffer.from(reply.hex.slice(0, 16), 'hex');
  const end = bytes.indexOf(0);
  assert(end > 0 && end < 8 && bytes.subarray(end).every(byte => byte === 0),
    'Noncanonical language bytes');
  const code = bytes.subarray(0, end).toString('ascii');
  assert(LANGUAGES.includes(code) && encoded(code) === bytes.toString('hex'),
    'Unrecognized language');
  return code;
};
const decodeRegion = reply => {
  assert(reply && !reply.transport && reply.result === 0 &&
    typeof reply.hex === 'string' && /^[0-9a-f]{8,}$/i.test(reply.hex),
  'Invalid RegionCode response');
  const value = Buffer.from(reply.hex.slice(0, 8), 'hex').readUInt32LE();
  assert(value === 0 || value === 1, 'Unsupported region; no writes');
  return value;
};

async function perform(memory, sm, store, {operation, language, previous} = {}) {
  assert(['inspect', 'set', 'restore'].includes(operation), 'Unknown operation');
  if (operation === 'set') assert(LANGUAGES.includes(language) && language !== 'ja',
    'Choose one of the 17 non-Japanese targets');
  const proof = {kind: 'civ7-held-locale', operation, language: operation === 'set' ? language : undefined,
    session: memory.info.session, report: memory.reportFile, started: new Date().toISOString(),
    status: 'PREFLIGHT', actions: [], writeAttempts: [], pending: false,
    regionWriteAdmitted: false, languageWriteAdmitted: false, endpointRetireRequested: false};
  // An existing one-use receipt refuses the entire operation before IPC.
  await store.create(proof);
  let getter = 0, setter = 0, transportUncertain = false;
  const request = async body => {
    const row = {request: body, possiblyAdmitted: true, at: new Date().toISOString()};
    proof.actions.push(row); proof.pending = true; await store.save(proof);
    try {
      const response = await memory.request(body);
      row.response = response; proof.pending = false; await store.save(proof);
      return response;
    } catch (error) {
      transportUncertain = true; row.error = error.message; await store.save(proof);
      throw error;
    }
  };
  const ipc = (handle, id, hex = '') => request({command: 'root-native-ipc', handle, id, hex});
  const getLanguage = async () => decode(await ipc(getter, 0));
  const getRegion = async () => decodeRegion(await ipc(getter, 4));
  const stable = async () => {
    const first = {region: await getRegion(), language: await getLanguage()};
    const second = {region: await getRegion(), language: await getLanguage()};
    assert(first.region === second.region && first.language === second.language,
      'Mutable settings changed between reads; no write');
    return first;
  };
  const service = async name => {
    const result = await request({command: 'root-native-sm-service', handle: sm.export.handle, name});
    assert(!result.transport && result.result === 0 && result.moves?.length === 1 &&
      Number.isInteger(result.moves[0]) && result.moves[0] > 0, name + ' unavailable');
    return result.moves[0];
  };
  const setRegion = async (value, phase = 'target') => {
    const label = phase + '-region';
    assert(!proof.writeAttempts.includes(label), 'Region setter may not be replayed');
    proof.writeAttempts.push(label); proof.regionWriteAdmitted = true; await store.save(proof);
    const bytes = Buffer.alloc(4); bytes.writeUInt32LE(value);
    const result = await ipc(setter, 57, bytes.toString('hex'));
    assert(!result.transport && result.result === 0, 'Region setter rejected');
    assert(await getRegion() === value, 'Region readback differs');
  };
  const setLanguage = async (value, phase = 'target') => {
    const label = phase + '-language';
    assert(!proof.writeAttempts.includes(label), 'Language setter may not be replayed');
    proof.writeAttempts.push(label); proof.languageWriteAdmitted = true; await store.save(proof);
    const result = await ipc(setter, 0, encoded(value));
    assert(!result.transport && result.result === 0, 'Language setter rejected');
    assert(await getLanguage() === value, 'Language readback differs');
  };
  try {
    assert(sm.session === proof.session && sm.report === proof.report &&
      sm.program?.result === 0 && sm.service?.name === 'pm:shell' &&
      sm.service?.result === 0 && sm.service.moves?.length === 1 && sm.export?.handle,
    'Current Civ7 FS-context SM proof missing');
    const info = await request({command: 'root-native-info'});
    assert(info.session === proof.session && (!info.worker || info.worker.joined) &&
      info.services?.some(entry => entry.name === 'pm:shell' &&
        entry.handle === sm.service.moves[0] && entry.sm === sm.export.handle),
    'Current SM owner or worker state differs');
    getter = await service('set');
    proof.original = await stable(); await store.save(proof);
    proof.mapping = [];
    for (let index = 0; index < 20; index++) {
      const bytes = Buffer.alloc(4); bytes.writeUInt32LE(index);
      const code = decode(await ipc(getter, 2, bytes.toString('hex')));
      proof.mapping.push(code);
      assert(code === EXPECTED[index], 'This boot has an unverified language mapping at index ' + index);
    }
    if (operation === 'inspect') {
      proof.status = 'READ_ONLY_MAPPING_VERIFIED'; await store.save(proof);
      return proof;
    }
    if (operation === 'set') {
      proof.target = {region: 1, language};
    } else {
      assert(previous && previous.kind === proof.kind && previous.operation === 'set' &&
        previous.session === proof.session && previous.report === proof.report &&
        previous.status === 'LANGUAGE_READBACK_FS_HELD' && previous.target && previous.original,
      'Restore requires a successful same-session set receipt');
      assert(proof.original.region === previous.target.region &&
        proof.original.language === previous.target.language,
      'Current settings differ from our set receipt; no overwrite');
      assert([0, 1].includes(previous.original.region) &&
        LANGUAGES.includes(previous.original.language), 'Invalid original settings in receipt');
      proof.target = previous.original;
    }
    await store.save(proof);
    const before = await stable();
    assert(before.region === proof.original.region && before.language === proof.original.language,
      'Pre-write settings changed');
    if (before.region === proof.target.region && before.language === proof.target.language) {
      proof.noWriteNeeded = true;
    } else {
      setter = await service('set:sys');
      if (proof.target.region === 0) {
        if (before.language !== proof.target.language) await setLanguage(proof.target.language);
        if (before.region !== proof.target.region) await setRegion(proof.target.region);
      } else {
        if (before.region !== proof.target.region) await setRegion(proof.target.region);
        if (before.language !== proof.target.language) await setLanguage(proof.target.language);
      }
    }
    proof.after = await stable();
    assert(proof.after.region === proof.target.region && proof.after.language === proof.target.language,
      'Final setting readback differs');
    proof.status = operation === 'set' ? 'LANGUAGE_READBACK_FS_HELD' : 'ORIGINAL_SETTINGS_RESTORED_FS_HELD';
    await store.save(proof);
    return proof;
  } catch (error) {
    proof.error = error.stack;
    proof.status = proof.regionWriteAdmitted || proof.languageWriteAdmitted ?
      'CHANGE_UNCERTAIN_NO_REPLAY' : 'PREFLIGHT_FAILED_NO_WRITE';
    // Only an acknowledged transport and known original/target allow a
    // distinct, readback-gated compensation. Timeout/unknown ACK: no IPC.
    if (operation === 'set' && !transportUncertain && proof.original &&
      (proof.regionWriteAdmitted || proof.languageWriteAdmitted)) {
      try {
        const now = await stable();
        assert([proof.original.region, 1].includes(now.region) &&
          [proof.original.language, language].includes(now.language),
        'External setting change; preserve it');
        proof.rollbackObserved = now; await store.save(proof);
        if (now.language !== proof.original.language) await setLanguage(proof.original.language, 'rollback');
        if (now.region !== proof.original.region) await setRegion(proof.original.region, 'rollback');
        const restored = await stable();
        assert(restored.language === proof.original.language && restored.region === proof.original.region,
          'Rollback readback differs');
        proof.rollbackReadback = restored;
        proof.status = 'ABORT_ORIGINAL_SETTINGS_RESTORED';
      } catch (rollbackError) {proof.rollbackError = rollbackError.stack;}
    }
    await store.save(proof);
    throw error;
  } finally {
    if (!transportUncertain) {
      for (const handle of [setter, getter].filter(Boolean)) {
        try {
          const closed = await request({command: 'root-native-close-handle', handle});
          assert(closed.closed === handle, 'Handle close not acknowledged');
        } catch (error) {
          proof.closeError = error.message; proof.status += '_HANDLE_RELEASE_UNCERTAIN';
          break;
        }
      }
    } else proof.handleCloseDeferred = true;
    proof.finished = new Date().toISOString(); await store.save(proof);
    if (proof.closeError) throw Error(proof.closeError);
  }
}

async function journal(directory, name) {
  await fs.mkdir(directory, {recursive: true, mode: 0o700});
  assert((await fs.lstat(directory)).isDirectory() && !(await fs.lstat(directory)).isSymbolicLink(),
    'Journal directory must not be a symlink');
  const destination = path.join(directory, name);
  const persist = async (value, exclusive) => {
    const file = exclusive ? destination : destination + '.tmp.' + process.pid;
    const handle = await fs.open(file, 'wx', 0o600);
    try {await handle.writeFile(JSON.stringify(value, null, 2) + '\n'); await handle.sync();}
    finally {await handle.close();}
    if (!exclusive) await fs.rename(file, destination);
    const dir = await fs.open(directory, 'r');
    try {await dir.sync();} finally {await dir.close();}
  };
  return {file: destination, create: value => persist(value, true), save: value => persist(value, false)};
}

async function main(argv = process.argv.slice(2)) {
  const usage = 'Usage: node civ-locale.cjs inspect RUN | set RUN --language CODE | restore RUN --journal SET_RECEIPT';
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) {
    console.log(usage + '\nTargets: ' + LANGUAGES.filter(code => code !== 'ja').join(', ') +
      '\nRequires a verified FS endpoint held by the same Civ7 run. Keep the game and PC launcher running.');
    return;
  }
  const [operation, runArg, option, value] = argv;
  assert(argv.length >= 2 && argv.length <= 4 && ['inspect', 'set', 'restore'].includes(operation), usage);
  assert((operation === 'inspect' && argv.length === 2) ||
    (operation === 'set' && argv.length === 4 && option === '--language' &&
      LANGUAGES.includes(value) && value !== 'ja') ||
    (operation === 'restore' && argv.length === 4 && option === '--journal'), usage);
  const runs = path.resolve(__dirname, 'kit/port/engine/runs');
  const run = await fs.realpath(runArg);
  assert(path.dirname(run) === runs && /^switch2-[A-Za-z0-9]+$/.test(path.basename(run)),
    'Expected one CivSwitch run directly under kit/port/engine/runs');
  const result = JSON.parse(await fs.readFile(path.join(run, 'result.json')));
  assert(result.verified === true && result.target === 'civ7' &&
    result.fs?.verified === true && result.fs?.restored === true &&
    result.fs?.retainedEndpoint?.ready === true && result.fs?.cleanup?.deferred === true &&
    result.rpc?.mode === 'held' && result.rpc?.state === 'listening' &&
    result.fs.retainedEndpoint.session === path.basename(run),
  'A verified, still-held Civ7 FS run is required');
  const dir = path.join(run, 'locale');
  const name = operation === 'inspect' ?
    'inspect-' + crypto.randomBytes(8).toString('hex') + '.json' :
    operation + '-' + path.basename(run) + '.json';
  let previous;
  if (operation === 'restore') {
    const expected = path.join(dir, 'set-' + path.basename(run) + '.json');
    assert(path.resolve(value) === expected && await fs.realpath(value) === expected,
      'Restore needs this run’s own set receipt');
    previous = JSON.parse(await fs.readFile(expected));
  }
  const store = await journal(dir, name);
  // Use the run's immutable engine snapshot, not a later checkout or a
  // SmileBASIC runner. Connecting checks the live retained session.
  process.env.NS2_TARGET = 'civ7';
  const {connect} = require(path.join(run, 'switch2/tools/fs-memory.cjs'));
  const memory = await connect();
  assert(path.dirname(await fs.realpath(memory.reportFile)).startsWith(run + path.sep) &&
    memory.info.session === path.basename(run), 'Retained report belongs to another run');
  const smPath = path.join(run, 'switch2/ro', memory.info.session + '-sm-proof.json');
  const sm = JSON.parse(await fs.readFile(smPath));
  const proof = await perform(memory, sm, store, {operation, language: value, previous});
  console.log(JSON.stringify({status: proof.status, original: proof.original,
    target: proof.target, after: proof.after, receipt: store.file,
    endpointRetireRequested: false}));
}

module.exports = {LANGUAGES, perform, decode, decodeRegion, main, journal};
if (require.main === module) main().catch(error => {console.error(error.stack); process.exitCode = 1;});
