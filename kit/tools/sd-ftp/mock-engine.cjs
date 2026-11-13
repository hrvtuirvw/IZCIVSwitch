#!/usr/bin/env node
'use strict';
// In-memory fake engine for offline testing of the sd-ftp bridge.
//
// Speaks the same memoryControl JSON-line protocol as the console engine:
//   client -> {"command":"root-native-sd-list","handle":N,"path":"/"} \n
//   server -> {"result":0,"canonicalResult":0,"entries":[...]} \n  (then closes the socket)
//
// Only the SD commands used by sd-ftp.cjs are implemented. Mutating commands honour the same
// NS2_ALLOW_WRITES contract (a MockEngine created with allowWrites:false behaves like a bare
// engine process) so the FTP bridge can be tested without a console.
const net = require('node:net');
const crypto = require('node:crypto');

const NOT_FOUND = 0x202;          // FsResult PathNotFound
const NOT_SUPPORTED = 0xE402;     // synthetic: rename unsupported
const WRITES_DISABLED = 0xE401;   // synthetic: engine-side NS2_ALLOW_WRITES gate
const DIR_NOT_EMPTY = 0x202;      // close enough for the mock; sd-ftp maps it to 550

const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function ok(extra = {}) {
  return Object.assign({result: 0, canonicalResult: 0}, extra);
}

function fail(result, error) {
  const reply = {result, canonicalResult: result & 0x3fffff};
  if (error) reply.error = error;
  return reply;
}

// ---------------------------------------------------------------------------------------------
// In-memory file tree
// ---------------------------------------------------------------------------------------------
class MockFs {
  constructor() {
    this.nodes = new Map([['/', {type: 0}]]);
  }

  normalize(path) {
    if (typeof path !== 'string' || path[0] !== '/') throw Error('mock: path must be absolute');
    const parts = [];
    for (const part of path.split('/')) {
      if (!part || part === '.') continue;
      if (part === '..') { parts.pop(); continue; }
      parts.push(part);
    }
    return parts.length ? '/' + parts.join('/') : '/';
  }

  parent(path) {
    const cut = path.lastIndexOf('/');
    return cut <= 0 ? '/' : path.slice(0, cut);
  }

  ensureDir(path) {
    const clean = this.normalize(path);
    if (clean === '/') return;
    const parent = this.parent(clean);
    this.ensureDir(parent);
    const existing = this.nodes.get(clean);
    if (existing) {
      if (existing.type !== 0) throw Error('mock: ' + clean + ' is a file');
      return;
    }
    this.nodes.set(clean, {type: 0});
  }

  setFile(path, bytes) {
    const clean = this.normalize(path);
    this.ensureDir(this.parent(clean));
    this.nodes.set(clean, {type: 1, bytes: Buffer.from(bytes)});
  }

  file(path) {
    const node = this.nodes.get(this.normalize(path));
    return node && node.type === 1 ? node : null;
  }

  dir(path) {
    const node = this.nodes.get(this.normalize(path));
    return node && node.type === 0 ? node : null;
  }

  children(path) {
    const clean = this.normalize(path);
    const prefix = clean === '/' ? '/' : clean + '/';
    const entries = [];
    for (const [nodePath, node] of this.nodes) {
      if (nodePath === clean || !nodePath.startsWith(prefix)) continue;
      const rest = nodePath.slice(prefix.length);
      if (!rest || rest.includes('/')) continue;
      entries.push({name: rest, type: node.type, size: node.type === 0 ? '0' : String(node.bytes.length)});
    }
    entries.sort((a, b) => a.type - b.type || a.name.localeCompare(b.name));
    return entries;
  }

  remove(path) {
    const clean = this.normalize(path);
    if (clean === '/') throw Error('mock: cannot remove /');
    this.nodes.delete(clean);
    const prefix = clean + '/';
    for (const nodePath of [...this.nodes.keys()]) {
      if (nodePath.startsWith(prefix)) this.nodes.delete(nodePath);
    }
  }
}

function seedFs(fs) {
  fs.setFile('/hello.txt', Buffer.from('hello from civswitch\n', 'utf8'));
  fs.ensureDir('/switch');
  fs.ensureDir('/switch/save');
  fs.setFile('/switch/save/data.bin', Buffer.from(Array.from({length: 256}, (_, i) => i)));
  fs.setFile('/switch/save/note.txt', Buffer.from('save slot\n', 'utf8'));
}

// ---------------------------------------------------------------------------------------------
// Command handlers
// ---------------------------------------------------------------------------------------------
function createEngine(options = {}) {
  const fs = options.fs || new MockFs();
  if (!options.fs) seedFs(fs);
  const allowWrites = options.allowWrites !== false;
  const failRename = options.failRename === true;
  const state = {
    allowWrites,
    handle: Number(options.handle || 77398408),
    requests: [],
    writes: 0,
    renames: 0,
    commits: 0
  };

  function dispatch(request) {
    if (!request || typeof request !== 'object') return fail(NOT_FOUND, 'mock: bad request');
    const command = String(request.command || '');
    if (!command.startsWith('root-native-')) return fail(NOT_FOUND, 'mock: unknown command ' + command);
    const name = command.slice('root-native-'.length);
    state.requests.push({command: name, request});
    if (allowWrites === false && ['sd-create', 'sd-mkdir', 'sd-delete', 'sd-delete-dir',
      'sd-rename', 'sd-write', 'sd-commit'].includes(name)) {
      return fail(WRITES_DISABLED, 'writes disabled (set NS2_ALLOW_WRITES=1)');
    }
    try {
      return handle(fs, state, name, request);
    } catch (error) {
      return fail(NOT_FOUND, 'mock: ' + error.message);
    }
  }

  return {fs, state, dispatch};
}

function handle(fs, state, name, request) {
  const path = request.path;
  switch (name) {
    case 'sd-list': {
      const clean = fs.normalize(path ?? '/');
      if (!fs.dir(clean)) return fail(NOT_FOUND, 'no such directory: ' + clean);
      return ok({path: clean, entries: fs.children(clean)});
    }
    case 'sd-read': {
      const clean = fs.normalize(path);
      const node = fs.file(clean);
      if (!node) return fail(NOT_FOUND, 'no such file: ' + clean);
      const offset = Math.max(0, Number(request.offset ?? 0));
      const limit = Number(request.length ?? 0x4000);
      const available = Math.max(0, node.bytes.length - offset);
      const length = Math.min(available, Math.max(0, limit));
      const bytes = node.bytes.subarray(offset, offset + length);
      return ok({path: clean, size: node.bytes.length, offset, length,
        sha256: hash(bytes), hex: bytes.toString('hex')});
    }
    case 'sd-write': {
      const clean = fs.normalize(path);
      const hex = String(request.hex ?? '');
      if (!/^[0-9a-fA-F]*$/.test(hex) || hex.length % 2) {
        return fail(NOT_FOUND, 'mock: hex payload is invalid');
      }
      const bytes = Buffer.from(hex, 'hex');
      let node = fs.file(clean);
      if (request.truncate && node) node.bytes = Buffer.alloc(0);
      if (!node) {
        const preallocate = Math.max(0, Number(request.size ?? 0));
        fs.setFile(clean, Buffer.alloc(preallocate));
        node = fs.file(clean);
      }
      const offset = Math.max(0, Number(request.offset ?? 0));
      const end = offset + bytes.length;
      if (node.bytes.length < end) {
        const grown = Buffer.alloc(end);
        node.bytes.copy(grown, 0);
        node.bytes = grown;
      }
      bytes.copy(node.bytes, offset);
      state.writes++;
      return ok({path: clean, offset, written: bytes.length, size: node.bytes.length,
        sha256: hash(node.bytes)});
    }
    case 'sd-create': {
      const clean = fs.normalize(path);
      if (fs.nodes.has(clean)) return fail(NOT_FOUND, 'already exists: ' + clean);
      if (!fs.dir(fs.parent(clean))) return fail(NOT_FOUND, 'no such directory: ' + fs.parent(clean));
      const size = Math.max(0, Number(request.size ?? 0));
      fs.setFile(clean, Buffer.alloc(size));
      return ok({path: clean, size, sha256: hash(fs.file(clean).bytes)});
    }
    case 'sd-mkdir': {
      const clean = fs.normalize(path);
      if (fs.nodes.has(clean)) return fail(NOT_FOUND, 'already exists: ' + clean);
      if (!fs.dir(fs.parent(clean))) return fail(NOT_FOUND, 'no such directory: ' + fs.parent(clean));
      fs.nodes.set(clean, {type: 0});
      return ok({path: clean});
    }
    case 'sd-delete': {
      const clean = fs.normalize(path);
      const node = fs.nodes.get(clean);
      if (!node) return fail(NOT_FOUND, 'no such file: ' + clean);
      if (node.type !== 1) return fail(NOT_FOUND, 'not a file: ' + clean);
      fs.nodes.delete(clean);
      return ok({path: clean, deleted: true});
    }
    case 'sd-delete-dir': {
      const clean = fs.normalize(path);
      const node = fs.nodes.get(clean);
      if (!node || node.type !== 0) return fail(NOT_FOUND, 'no such directory: ' + clean);
      if (clean === '/') return fail(NOT_FOUND, 'cannot remove /');
      if (request.recursive !== true && fs.children(clean).length) {
        return fail(DIR_NOT_EMPTY, 'directory not empty: ' + clean);
      }
      fs.remove(clean);
      return ok({path: clean, recursive: request.recursive === true, deleted: true});
    }
    case 'sd-rename': {
      const from = fs.normalize(path);
      const to = fs.normalize(request.path2);
      if (failRename) return fail(NOT_SUPPORTED, 'mock: rename disabled by option');
      if (!fs.nodes.has(from)) return fail(NOT_FOUND, 'no such file: ' + from);
      if (fs.nodes.has(to)) return fail(NOT_FOUND, 'destination exists: ' + to);
      const node = fs.nodes.get(from);
      if (node.type === 0) {
        for (const [nodePath, child] of [...fs.nodes]) {
          if (nodePath === from) continue;
          if (nodePath.startsWith(from + '/')) {
            fs.nodes.set(to + nodePath.slice(from.length), child);
            fs.nodes.delete(nodePath);
          }
        }
      }
      fs.nodes.set(to, node);
      fs.nodes.delete(from);
      state.renames++;
      return ok({path: from, path2: to, directory: node.type === 0});
    }
    case 'sd-commit':
      state.commits++;
      return ok({committed: true});
    default:
      return fail(NOT_FOUND, 'mock: unsupported command ' + name);
  }
}

// ---------------------------------------------------------------------------------------------
// TCP server
// ---------------------------------------------------------------------------------------------
function createMockEngine(options = {}) {
  const engine = createEngine(options);
  let busy = Math.max(0, Number(options.busyReplies ?? 0));
  const sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    socket.on('error', () => {});
    socket.setEncoding('utf8');
    let buffer = '';
    socket.on('data', chunk => {
      buffer += chunk;
      let index;
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index).trim();
        buffer = buffer.slice(index + 1);
        if (!line) continue;
        let reply;
        if (busy > 0) {
          busy--;
          reply = {error: 'Another memory request is active'};
        } else {
          let request;
          try { request = JSON.parse(line); }
          catch (error) { reply = fail(NOT_FOUND, 'mock: bad JSON'); }
          reply = reply || engine.dispatch(request);
        }
        socket.write(JSON.stringify(reply) + '\n');
      }
      socket.end();
    });
  });
  return {
    server,
    fs: engine.fs,
    state: engine.state,
    dispatch: engine.dispatch,
    listen(port = 0, host = '127.0.0.1') {
      return new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, host, () => {
          server.removeListener('error', reject);
          resolve(server.address());
        });
      });
    },
    close() {
      for (const socket of sockets) socket.destroy();
      sockets.clear();
      return new Promise(resolve => server.close(() => resolve()));
    }
  };
}

if (require.main === module) {
  const port = Number(process.env.MOCK_PORT || 0);
  const mock = createMockEngine({allowWrites: process.env.MOCK_ALLOW_WRITES !== '0'});
  mock.listen(port).then(address => {
    console.log('[mock-engine] listening on 127.0.0.1:' + address.port +
      ' handle=' + mock.state.handle + ' allowWrites=' + mock.state.allowWrites);
    const shutdown = () => mock.close().then(() => process.exit(0));
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
  }).catch(error => {
    console.error('[mock-engine] ' + error.message);
    process.exit(1);
  });
}

module.exports = {MockFs, seedFs, createEngine, createMockEngine,
  NOT_FOUND, NOT_SUPPORTED, WRITES_DISABLED, DIR_NOT_EMPTY};
