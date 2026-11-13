#!/usr/bin/env node
// Resolve the SD album (image) filesystem handle from a held run folder.
//
// The held engine keeps a retained memoryControl endpoint (TCP JSON-line protocol) in
// <run>/switch2/current-acquisition.json (+ report.memoryControl.socketPath). This tool only
// uses documented engine commands:
//   1. root-info            -> a promoted-root clone handle (s.handles member)
//   2. root-native-ipc      -> fsp-srv cmd 100 (OpenImageDirectoryFileSystem) with
//                              ImageDirectoryId=1 (SdCard); the reply moves one IFileSystem handle
//   3. root-native-sd-list  -> sanity list of "/" through the moved handle
//
// Usage:
//   node resolve-sd-handle.cjs --run <run folder> [--opener 100] [--hex 01000000]
//   node resolve-sd-handle.cjs --socket 127.0.0.1:PORT
// Prints one JSON line: {"ok":true,"socket":"127.0.0.1:PORT","rootHandle":N,"handle":N,"entries":[...]}
// Exit 0 on success, 1 on failure (the JSON line is still printed with ok:false).
'use strict';

const fs = require('fs');
const path = require('path');
const net = require('net');

function parseArgs(argv) {
  const options = {run: null, socket: null, opener: 100, hex: '01000000'};
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index];
    if (argument === '--help' || argument === '-h') { options.help = true; continue; }
    if (argument === '--run') { options.run = argv[++index]; continue; }
    if (argument === '--socket') { options.socket = argv[++index]; continue; }
    if (argument === '--opener') { options.opener = Number(argv[++index]); continue; }
    if (argument === '--hex') { options.hex = String(argv[++index] || ''); continue; }
    throw new Error('unknown argument: ' + argument);
  }
  return options;
}

const USAGE = 'Usage: node resolve-sd-handle.cjs --run <run folder> | --socket 127.0.0.1:PORT';

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (error) { return null; }
}

function requestOnce(socketPath, command, timeoutMs) {
  return new Promise((resolve, reject) => {
    const match = /^([^:]+):(\d+)$/.exec(socketPath);
    if (!match) { reject(new Error('socket must be host:port: ' + socketPath)); return; }
    const socket = net.createConnection({host: match[1], port: Number(match[2])});
    let buffer = '';
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      callback(value);
    };
    const timer = setTimeout(() => finish(reject, new Error('request timed out after ' + timeoutMs + 'ms')),
      timeoutMs);
    socket.setNoDelay(true);
    socket.on('connect', () => socket.write(JSON.stringify(command) + '\n'));
    socket.on('data', chunk => {
      buffer += chunk.toString('utf8');
      const newline = buffer.indexOf('\n');
      if (newline < 0) return;
      const line = buffer.slice(0, newline).trim();
      if (!line) return;
      let parsed;
      try { parsed = JSON.parse(line); } catch (error) { finish(reject, new Error('bad reply: ' + line.slice(0, 200))); return; }
      finish(resolve, parsed);
    });
    socket.on('error', error => finish(reject, error));
  });
}

async function request(socketPath, command, timeoutMs = 30000) {
  const deadline = Date.now() + 120000;
  for (;;) {
    try {
      return await requestOnce(socketPath, command, timeoutMs);
    } catch (error) {
      const busy = String(error && error.message || error).includes('Another memory request is active');
      if (!busy || Date.now() > deadline) throw error;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  }
}

function findSocket(runDir) {
  const candidates = [];
  const acquisitionPath = path.join(runDir, 'switch2', 'current-acquisition.json');
  const acquisition = readJson(acquisitionPath);
  if (acquisition) {
    if (typeof acquisition.socketPath === 'string') candidates.push(acquisition.socketPath);
    if (typeof acquisition.report === 'string') {
      const report = readJson(acquisition.report);
      if (report && report.memoryControl && typeof report.memoryControl.socketPath === 'string') {
        candidates.push(report.memoryControl.socketPath);
      }
    }
  }
  const current = readJson(path.join(runDir, 'switch2', 'fs-execution-current.json'));
  if (current && current.retainedEndpoint && typeof current.retainedEndpoint.socketPath === 'string') {
    candidates.push(current.retainedEndpoint.socketPath);
  }
  const tcp = candidates.filter(value => /^127\.0\.0\.1:\d+$/.test(String(value)));
  return tcp[0] || null;
}

function pickHandle(reply) {
  const r = reply || {};
  const push = value => typeof value === 'number' && value > 0 ? value : null;
  const clones = r.ownedRoot && r.ownedRoot.clones || r.clones || r.ownedRootClones;
  if (Array.isArray(clones)) {
    for (const clone of clones) { const handle = push(clone); if (handle) return handle; }
  }
  if (typeof r.rootHandle === 'number' && r.rootHandle > 0) return r.rootHandle;
  if (typeof r.handle === 'number' && r.handle > 0) return r.handle;
  if (typeof r.moved === 'number' && r.moved > 0) return r.moved;
  return null;
}

async function pickRootHandle(socketPath, pollMs = 60000) {
  const deadline = Date.now() + pollMs;
  for (;;) {
    const info = await request(socketPath, {command: 'root-native-info'});
    if (info && info.ready === false) throw new Error('retained bridge is not ready yet');
    const reply = await request(socketPath, {command: 'root-info'});
    const handle = pickHandle(reply);
    if (handle) return handle;
    if (Date.now() > deadline) throw new Error('no promoted-root clone handle appeared within ' + pollMs + 'ms');
    await new Promise(resolve => setTimeout(resolve, 500));
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) { console.log(USAGE); return; }
  const output = {ok: false};
  try {
    if (options.run) {
      output.run = path.resolve(options.run);
      if (!fs.existsSync(path.join(output.run, 'switch2'))) throw new Error('not a run folder: ' + output.run);
      output.socket = findSocket(output.run);
      if (!output.socket) throw new Error('no TCP memoryControl socketPath in current-acquisition.json');
    } else if (options.socket) {
      output.socket = options.socket;
    } else {
      throw new Error('missing --run or --socket\n' + USAGE);
    }

    output.rootHandle = await pickRootHandle(output.socket);
    const opened = await request(output.socket, {
      command: 'root-native-ipc', handle: output.rootHandle, id: options.opener, hex: options.hex
    });
    output.opened = {result: opened.result, canonicalResult: opened.canonicalResult,
      moves: opened.moves || [], copies: opened.copies || []};
    const handle = (opened.moves || [])[0];
    if (!handle) throw new Error('cmd ' + options.opener + ' returned no moved handle (result ' + opened.result + ')');
    output.handle = handle;

    const listing = await request(output.socket, {command: 'root-native-sd-list', handle, path: '/'});
    output.listing = {result: listing.result, canonicalResult: listing.canonicalResult,
      entries: (listing.entries || []).slice(0, 16)};
    output.ok = true;
  } catch (error) {
    output.error = String(error && error.message || error);
  }
  console.log(JSON.stringify(output));
  process.exitCode = output.ok ? 0 : 1;
}

main();
