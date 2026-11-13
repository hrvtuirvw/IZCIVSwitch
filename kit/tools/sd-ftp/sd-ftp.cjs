#!/usr/bin/env node
'use strict';
// PC-side FTP bridge for the console SD card. Pure Node.js, no third-party dependencies.
//
// FTP commands are mapped onto the engine's root-native-sd-* commands over the memoryControl
// TCP JSON-line endpoint. The engine requires NS2_ALLOW_WRITES=1 for mutations; this bridge is
// read-only unless started with --allow-write (so both gates have to be open).
const net = require('node:net');
const fs = require('node:fs');
const {once} = require('node:events');

const CHUNK = 0x4000;             // IFile Write/Read chunk the engine command accepts
const BUSY = 'Another memory request is active';
const WRITES_DISABLED = 0xE401;   // synthetic engine result for gated mutations

// ---------------------------------------------------------------------------------------------
// memoryControl client: one fresh TCP connection per command (same pattern as _work/sd-probe),
// busy retry 50 ms up to 120 s.
// ---------------------------------------------------------------------------------------------
class EngineClient {
  constructor(endpoint, handle) {
    const match = /^([^:]+):(\d+)$/.exec(String(endpoint ?? '').trim());
    if (!match) throw Error('--socket must be host:port (e.g. 127.0.0.1:4062)');
    this.host = match[1];
    this.port = Number(match[2]);
    this.handle = Number(handle);
    if (!Number.isInteger(this.handle) || this.handle <= 0) throw Error('invalid SD handle');
  }

  command(name, extra = {}) {
    return Object.assign({command: 'root-native-' + name}, extra);
  }

  async request(command) {
    const deadline = Date.now() + 120000;
    let busy = 0;
    for (;;) {
      try { return await this.once(command); }
      catch (error) {
        if (!String(error.message).includes(BUSY)) throw error;
        busy++;
        if (Date.now() + 50 > deadline) {
          throw Error('memory socket stayed busy for 120 s (' + busy + ' retries)');
        }
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
  }

  once(command) {
    return new Promise((resolve, reject) => {
      const socket = net.createConnection({host: this.host, port: this.port});
      let buffer = '', settled = false;
      const finish = (fn, value) => {
        if (settled) return;
        settled = true;
        socket.destroy();
        fn(value);
      };
      socket.setEncoding('utf8');
      socket.on('connect', () => socket.write(JSON.stringify(command) + '\n'));
      socket.on('data', chunk => { buffer += chunk; });
      socket.on('end', () => {
        const text = buffer.trim();
        if (!text) return finish(reject, Error('engine closed the socket without a reply'));
        let reply;
        try { reply = JSON.parse(text); }
        catch (error) { return finish(reject, Error('engine reply is not JSON: ' + text.slice(0, 200))); }
        if (reply && reply.error) {
          const error = Error(String(reply.error));
          error.reply = reply;
          return finish(reject, error);
        }
        finish(resolve, reply);
      });
      socket.on('error', error => finish(reject, error));
      socket.setTimeout(120000, () => finish(reject, Error('engine request timed out')));
    });
  }

  list(path) { return this.request(this.command('sd-list', {handle: this.handle, path})); }
  read(path, offset, length) {
    return this.request(this.command('sd-read', {handle: this.handle, path, offset, length}));
  }
  write(path, offset, hex, truncate = false, size = 0) {
    return this.request(this.command('sd-write',
      {handle: this.handle, path, offset, hex, truncate, size}));
  }
  create(path, size = 0) {
    return this.request(this.command('sd-create', {handle: this.handle, path, size}));
  }
  mkdir(path) { return this.request(this.command('sd-mkdir', {handle: this.handle, path})); }
  delete(path) { return this.request(this.command('sd-delete', {handle: this.handle, path})); }
  deleteDir(path, recursive) {
    return this.request(this.command('sd-delete-dir',
      {handle: this.handle, path, recursive: recursive === true}));
  }
  rename(path, path2, directory = false) {
    return this.request(this.command('sd-rename',
      {handle: this.handle, path, path2, directory: directory === true}));
  }
  commit() { return this.request(this.command('sd-commit', {handle: this.handle})); }
}

// ---------------------------------------------------------------------------------------------
// Virtual path bookkeeping: FTP clients always see a rooted tree; --root maps it onto the SD
// path the engine talks to (e.g. --root /switch means FTP / == SD /switch).
// ---------------------------------------------------------------------------------------------
function normalizeVirtual(input) {
  const parts = [];
  for (const part of String(input ?? '').replace(/\\/g, '/').split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') { parts.pop(); continue; }
    parts.push(part);
  }
  return '/' + parts.join('/');
}

function resolveVirtual(cwd, argument) {
  const text = String(argument ?? '').replace(/\\/g, '/').trim();
  return normalizeVirtual(text.startsWith('/') ? text : cwd + '/' + text);
}

class SdPaths {
  constructor(root = '/') {
    this.root = normalizeVirtual(root);
  }
  toSd(virtualPath) {
    const clean = normalizeVirtual(virtualPath);
    if (clean === '/') return this.root;
    return (this.root === '/' ? '' : this.root) + clean;
  }
}

// ---------------------------------------------------------------------------------------------
// Unix-style LIST lines (Windows Explorer / FileZilla parse these). The engine does not expose
// mtimes, so every entry is stamped with the current local time.
// ---------------------------------------------------------------------------------------------
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function listTimestamp(date = new Date()) {
  const day = String(date.getDate()).padStart(2, ' ');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return MONTHS[date.getMonth()] + ' ' + day + ' ' + hour + ':' + minute;
}

function listEntry(entry, name) {
  const directory = Number(entry.type) === 0;
  const mode = directory ? 'drwxr-xr-x' : '-rw-r--r--';
  const size = String(Number(entry.size ?? 0)).padStart(16);
  return mode + '    1 ftp      ftp      ' + size + ' ' + listTimestamp() + ' ' + name;
}

// ---------------------------------------------------------------------------------------------
// FTP session
// ---------------------------------------------------------------------------------------------
class FtpSession {
  constructor(context) {
    this.context = context;
    this.control = null;
    this.buffer = '';
    this.chain = Promise.resolve();
    this.user = null;
    this.authed = false;
    this.cwd = '/';
    this.type = 'I';
    this.pasv = null;
    this.dataSockets = [];
    this.dataWaiter = null;
    this.renameFrom = null;
    this.closed = false;
  }

  attach(socket) {
    this.control = socket;
    socket.setEncoding('utf8');
    socket.setNoDelay(true);
    socket.setTimeout(300000);
    socket.on('data', chunk => {
      this.buffer += chunk;
      let index;
      while ((index = this.buffer.indexOf('\n')) >= 0) {
        const line = this.buffer.slice(0, index).replace(/\r$/, '');
        this.buffer = this.buffer.slice(index + 1);
        if (!line.trim()) continue;
        const command = line.trim();
        this.chain = this.chain
          .then(() => this.handle(command))
          .catch(error => {
            this.context.log('command failed: ' + command + ' -> ' + error.message);
            this.reply(500, 'Command failed: ' + error.message);
          });
      }
    });
    socket.on('timeout', () => this.close());
    socket.on('error', () => this.close());
    socket.on('close', () => this.close());
    this.reply(220, 'CivSwitch SD FTP ready');
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.closePassive();
    if (this.control && !this.control.destroyed) this.control.destroy();
  }

  reply(code, text) {
    if (!this.control || this.control.destroyed) return;
    this.control.write(String(code) + ' ' + text + '\r\n');
  }

  multi(code, lines, end) {
    if (!this.control || this.control.destroyed) return;
    this.control.write(String(code) + '-Features:\r\n');
    for (const line of lines) this.control.write(' ' + line + '\r\n');
    this.control.write(String(code) + ' ' + end + '\r\n');
  }

  // ---- engine helpers ----
  get engine() { return this.context.engine; }
  get paths() { return this.context.paths; }

  check(reply) {
    if (!reply || reply.result === undefined) return reply;
    if (reply.result) {
      if (reply.result === WRITES_DISABLED || reply.canonicalResult === 0x401) {
        throw Error('engine writes disabled (set NS2_ALLOW_WRITES=1 in the engine process)');
      }
      throw Error('engine error 0x' + Number(reply.result).toString(16) +
        (reply.canonicalResult ? ' (fs 0x' + Number(reply.canonicalResult).toString(16) + ')' : ''));
    }
    return reply;
  }

  async stat(virtual) {
    const clean = normalizeVirtual(virtual);
    if (clean === '/') return {name: '/', type: 0, size: '0'};
    const sd = this.paths.toSd(clean);
    const cut = sd.lastIndexOf('/');
    const parent = cut <= 0 ? '/' : sd.slice(0, cut);
    const name = sd.slice(cut + 1);
    let reply;
    try { reply = await this.engine.list(parent); }
    catch (error) { return null; }
    if (reply.result) return null;
    return (reply.entries || []).find(entry => entry.name === name) || null;
  }

  // ---- data connection ----
  openPassive() {
    this.closePassive();
    return new Promise((resolve, reject) => {
      const host = this.control && this.control.localAddress &&
        !this.control.localAddress.includes(':') ? this.control.localAddress : '127.0.0.1';
      const server = net.createServer(socket => {
        socket.setNoDelay(true);
        socket.on('error', () => {});
        if (this.dataWaiter) {
          const waiter = this.dataWaiter;
          this.dataWaiter = null;
          waiter.resolve(socket);
        } else {
          this.dataSockets.push(socket);
        }
      });
      server.on('error', reject);
      server.listen(0, host, () => {
        this.pasv = server;
        this.pasvHost = host;
        resolve(server.address().port);
      });
    });
  }

  closePassive() {
    if (this.pasv) {
      try { this.pasv.close(); } catch (error) { /* already closed */ }
      this.pasv = null;
    }
    for (const socket of this.dataSockets) socket.destroy();
    this.dataSockets = [];
    if (this.dataWaiter) {
      const waiter = this.dataWaiter;
      this.dataWaiter = null;
      waiter.reject(Error('passive data listener closed'));
    }
  }

  takeData(timeout = 15000) {
    if (this.dataSockets.length) return Promise.resolve(this.dataSockets.shift());
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.dataWaiter = null;
        reject(Error('timed out waiting for the data connection (did the client use PASV/EPSV?)'));
      }, timeout);
      this.dataWaiter = {
        resolve: socket => { clearTimeout(timer); resolve(socket); },
        reject: error => { clearTimeout(timer); reject(error); }
      };
    });
  }

  async sendBuffer(buffer) {
    const socket = await this.takeData();
    try {
      if (buffer.length) socket.write(buffer);
      socket.end();
      await once(socket, 'close');
    } catch (error) {
      socket.destroy();
      throw error;
    }
  }

  // ---- command dispatch ----
  async handle(line) {
    const index = line.indexOf(' ');
    const verb = (index < 0 ? line : line.slice(0, index)).toUpperCase();
    const argument = index < 0 ? '' : line.slice(index + 1);
    const publicCommands = ['USER', 'PASS', 'QUIT', 'NOOP', 'SYST', 'FEAT', 'OPTS',
      'TYPE', 'MODE', 'STRU', 'AUTH', 'PBSZ', 'PROT'];
    if (!this.authed && !publicCommands.includes(verb)) {
      return this.reply(530, 'Please log in with USER and PASS');
    }
    switch (verb) {
      case 'USER': return this.cmdUser(argument);
      case 'PASS': return this.cmdPass(argument);
      case 'SYST': return this.reply(215, 'UNIX Type: L8');
      case 'FEAT': return this.multi(211,
        ['SIZE', 'UTF8', 'EPSV', 'PASV', 'TVFS'], 'End');
      case 'OPTS': return this.cmdOpts(argument);
      case 'TYPE': return this.cmdType(argument);
      case 'MODE': return this.reply(200, 'Only stream mode is supported');
      case 'STRU': return this.reply(200, 'Only file structure is supported');
      case 'AUTH': return this.reply(502, 'AUTH is not supported');
      case 'PBSZ': return this.reply(502, 'PBSZ is not supported');
      case 'PROT': return this.reply(502, 'PROT is not supported');
      case 'PWD': return this.cmdPwd();
      case 'CWD': return this.cmdCwd(argument);
      case 'CDUP': return this.cmdCwd('..');
      case 'NOOP': return this.reply(200, 'NOOP');
      case 'QUIT': this.reply(221, 'Bye'); this.close(); return;
      case 'PASV': return this.cmdPasv(argument);
      case 'EPSV': return this.cmdEpsv(argument);
      case 'PORT': return this.reply(502, 'PORT is not supported; use PASV or EPSV');
      case 'LIST': return this.cmdList(argument, true);
      case 'NLST': return this.cmdList(argument, false);
      case 'RETR': return this.cmdRetr(argument);
      case 'STOR': return this.cmdStor(argument);
      case 'DELE': return this.cmdDele(argument);
      case 'MKD': return this.cmdMkd(argument);
      case 'RMD': return this.cmdRmd(argument);
      case 'RNFR': return this.cmdRnfr(argument);
      case 'RNTO': return this.cmdRnto(argument);
      case 'SIZE': return this.cmdSize(argument);
      case 'HELP': return this.reply(214, 'Commands: USER PASS SYST FEAT OPTS TYPE PWD CWD '
        + 'CDUP NOOP QUIT PASV EPSV LIST NLST RETR STOR DELE MKD RMD RNFR RNTO SIZE');
      default: return this.reply(502, 'Command not implemented: ' + verb);
    }
  }

  // ---- login ----
  cmdUser(argument) {
    this.user = argument.trim();
    return this.reply(331, 'User ' + this.user + ' ok, password required');
  }

  cmdPass(argument) {
    const options = this.context;
    if (options.user && options.user !== this.user) {
      return this.reply(530, 'Login incorrect');
    }
    if (options.user && options.pass !== undefined && options.pass !== argument) {
      return this.reply(530, 'Login incorrect');
    }
    this.authed = true;
    return this.reply(230, 'Login successful');
  }

  cmdOpts(argument) {
    if (/^utf8\s+on$/i.test(argument.trim())) return this.reply(200, 'UTF8 enabled');
    return this.reply(501, 'Unsupported OPTS argument');
  }

  cmdType(argument) {
    if (!/^[AI]$/i.test(argument.trim())) return this.reply(504, 'Only TYPE I/A is supported');
    this.type = argument.trim().toUpperCase();
    return this.reply(200, 'Type set to ' + this.type);
  }

  cmdPwd() {
    return this.reply(257, '"' + this.cwd + '" is the current directory');
  }

  async cmdCwd(argument) {
    const target = resolveVirtual(this.cwd, argument || '/');
    const entry = await this.stat(target);
    if (!entry) return this.reply(550, 'No such directory: ' + target);
    if (Number(entry.type) !== 0) return this.reply(550, target + ' is not a directory');
    this.cwd = target;
    return this.reply(250, 'Directory changed to ' + target);
  }

  async cmdPasv() {
    const port = await this.openPassive();
    const octets = this.pasvHost.split('.').map(Number);
    return this.reply(227, 'Entering Passive Mode (' +
      [octets[0], octets[1], octets[2], octets[3], port >> 8, port & 0xff].join(',') + ')');
  }

  async cmdEpsv(argument) {
    const port = await this.openPassive();
    if (/^all$/i.test(argument.trim())) return this.reply(200, 'EPSV ALL ok');
    return this.reply(229, 'Entering Extended Passive Mode (|||' + port + '|)');
  }

  // ---- listing ----
  async cmdList(argument, verbose) {
    const tokens = argument.split(/\s+/).filter(Boolean);
    const path = tokens.filter(token => !token.startsWith('-')).pop() ?? this.cwd;
    const target = resolveVirtual(this.cwd, path);
    const entry = await this.stat(target);
    if (!entry) return this.reply(550, 'No such file or directory: ' + target);
    let lines;
    if (Number(entry.type) !== 0) {
      lines = [verbose ? listEntry(entry, target.slice(target.lastIndexOf('/') + 1)) : target.slice(target.lastIndexOf('/') + 1)];
    } else {
      let reply;
      try { reply = await this.engine.list(this.paths.toSd(target)); }
      catch (error) { return this.reply(451, 'Listing failed: ' + error.message); }
      if (reply.result) return this.reply(451, 'Listing failed: engine 0x' + Number(reply.result).toString(16));
      const entries = reply.entries || [];
      lines = verbose ? entries.map(item => listEntry(item, item.name))
        : entries.map(item => item.name);
    }
    this.reply(150, 'Opening ' + (verbose ? 'ASCII' : 'ASCII') + ' mode data connection');
    try {
      await this.sendBuffer(Buffer.from(lines.length ? lines.join('\r\n') + '\r\n' : '', 'utf8'));
      return this.reply(226, 'Transfer complete');
    } catch (error) {
      return this.reply(425, 'Data connection failed: ' + error.message);
    } finally {
      this.closePassive();
    }
  }

  // ---- download ----
  async cmdRetr(argument) {
    const target = resolveVirtual(this.cwd, argument);
    const entry = await this.stat(target);
    if (!entry) return this.reply(550, 'No such file: ' + target);
    if (Number(entry.type) === 0) return this.reply(550, target + ' is a directory');
    const sd = this.paths.toSd(target);
    const size = Number(entry.size ?? 0);
    this.reply(150, 'Opening BINARY mode data connection (' + size + ' bytes)');
    try {
      const socket = await this.takeData();
      let offset = 0;
      try {
        while (offset < size) {
          const length = Math.min(CHUNK, size - offset);
          const reply = this.check(await this.engine.read(sd, offset, length));
          const bytes = Buffer.from(String(reply.hex ?? ''), 'hex');
          if (!bytes.length) throw Error('engine returned an empty read at offset ' + offset);
          if (!socket.write(bytes)) await once(socket, 'drain');
          offset += bytes.length;
        }
        socket.end();
        await once(socket, 'close');
      } catch (error) {
        socket.destroy();
        throw error;
      }
      return this.reply(226, 'Transfer complete (' + offset + ' bytes)');
    } catch (error) {
      return this.reply(426, 'Transfer aborted: ' + error.message);
    } finally {
      this.closePassive();
    }
  }

  // ---- upload ----
  async cmdStor(argument) {
    if (!this.context.allowWrite) {
      return this.reply(550, 'read-only bridge: start sd-ftp with --allow-write to store files');
    }
    const target = resolveVirtual(this.cwd, argument);
    const sd = this.paths.toSd(target);
    const parent = this.cwd;
    const parentEntry = await this.stat(parent);
    if (!parentEntry) return this.reply(550, 'No such directory: ' + parent);
    this.reply(150, 'Opening BINARY mode data connection');
    try {
      const socket = await this.takeData();
      let pending = Buffer.alloc(0), offset = 0, first = true;
      try {
        for await (const chunk of socket) {
          pending = pending.length ? Buffer.concat([pending, chunk]) : chunk;
          while (pending.length >= CHUNK) {
            const part = pending.subarray(0, CHUNK);
            pending = pending.subarray(CHUNK);
            await this.storeChunk(sd, offset, part, first);
            first = false;
            offset += part.length;
          }
        }
        if (pending.length) {
          await this.storeChunk(sd, offset, pending, first);
          first = false;
          offset += pending.length;
        }
        if (first) await this.storeEmpty(sd);
        this.check(await this.engine.commit());
        return this.reply(226, 'Transfer complete (' + offset + ' bytes)');
      } catch (error) {
        socket.destroy();
        throw error;
      }
    } catch (error) {
      return this.reply(451, 'Transfer aborted: ' + error.message);
    } finally {
      this.closePassive();
    }
  }

  async storeChunk(sd, offset, bytes, truncate) {
    this.check(await this.engine.write(sd, offset, bytes.toString('hex'), truncate, 0));
  }

  async storeEmpty(sd) {
    const existing = await this.engine.delete(sd).catch(() => null);
    if (existing && existing.result && existing.canonicalResult !== 0x202) {
      this.check(existing);
    }
    const created = await this.engine.create(sd, 0);
    if (created.result) this.check(created);
  }

  // ---- mutations ----
  async cmdDele(argument) {
    if (!this.context.allowWrite) return this.reply(550, 'read-only bridge: --allow-write required');
    const target = resolveVirtual(this.cwd, argument);
    const entry = await this.stat(target);
    if (!entry) return this.reply(550, 'No such file: ' + target);
    if (Number(entry.type) === 0) return this.reply(550, target + ' is a directory (use RMD)');
    try {
      this.check(await this.engine.delete(this.paths.toSd(target)));
      return this.reply(250, 'File deleted');
    } catch (error) {
      return this.reply(550, 'Delete failed: ' + error.message);
    }
  }

  async cmdMkd(argument) {
    if (!this.context.allowWrite) return this.reply(550, 'read-only bridge: --allow-write required');
    const target = resolveVirtual(this.cwd, argument);
    try {
      const reply = await this.engine.mkdir(this.paths.toSd(target));
      if (reply.result) throw Error('engine 0x' + Number(reply.result).toString(16));
      return this.reply(257, '"' + target + '" created');
    } catch (error) {
      return this.reply(550, 'Create directory failed: ' + error.message);
    }
  }

  async cmdRmd(argument) {
    if (!this.context.allowWrite) return this.reply(550, 'read-only bridge: --allow-write required');
    const target = resolveVirtual(this.cwd, argument);
    if (target === '/') return this.reply(550, 'refusing to remove the FTP root');
    const entry = await this.stat(target);
    if (!entry) return this.reply(550, 'No such directory: ' + target);
    if (Number(entry.type) !== 0) return this.reply(550, target + ' is not a directory');
    try {
      this.check(await this.engine.deleteDir(this.paths.toSd(target), false));
      return this.reply(250, 'Directory removed');
    } catch (error) {
      return this.reply(550, 'Remove directory failed: ' + error.message);
    }
  }

  async cmdRnfr(argument) {
    if (!this.context.allowWrite) return this.reply(550, 'read-only bridge: --allow-write required');
    const target = resolveVirtual(this.cwd, argument);
    const entry = await this.stat(target);
    if (!entry) return this.reply(550, 'No such file or directory: ' + target);
    this.renameFrom = {path: target, entry};
    return this.reply(350, 'File exists, ready for destination name');
  }

  async cmdRnto(argument) {
    if (!this.context.allowWrite) return this.reply(550, 'read-only bridge: --allow-write required');
    if (!this.renameFrom) return this.reply(503, 'RNFR required first');
    const from = this.renameFrom;
    this.renameFrom = null;
    const target = resolveVirtual(this.cwd, argument);
    const directory = Number(from.entry.type) === 0;
    let reply = null;
    try { reply = await this.engine.rename(this.paths.toSd(from.path), this.paths.toSd(target), directory); }
    catch (error) { reply = null; }
    if (reply && !reply.result) return this.reply(250, 'Rename successful');
    if (directory) {
      return this.reply(550, 'engine rename failed for a directory (best-effort command; no fallback)');
    }
    // Fallback for files: read -> create/truncate -> write -> delete the old name.
    try {
      const entry = await this.stat(from.path);
      const size = Number(entry.size ?? 0);
      let offset = 0, first = true;
      while (offset < size) {
        const length = Math.min(CHUNK, size - offset);
        const chunk = this.check(await this.engine.read(this.paths.toSd(from.path), offset, length));
        const bytes = Buffer.from(String(chunk.hex ?? ''), 'hex');
        if (!bytes.length) throw Error('empty read at offset ' + offset);
        await this.storeChunk(this.paths.toSd(target), offset, bytes, first);
        first = false;
        offset += bytes.length;
      }
      if (first) await this.storeEmpty(this.paths.toSd(target));
      this.check(await this.engine.delete(this.paths.toSd(from.path)));
      this.check(await this.engine.commit());
      return this.reply(250, 'Rename successful (copy fallback)');
    } catch (error) {
      return this.reply(550, 'Rename failed: ' + error.message);
    }
  }

  async cmdSize(argument) {
    const target = resolveVirtual(this.cwd, argument);
    const entry = await this.stat(target);
    if (!entry) return this.reply(550, 'No such file: ' + target);
    if (Number(entry.type) !== 1) return this.reply(550, 'Not a regular file');
    return this.reply(213, String(Number(entry.size ?? 0)));
  }
}

// ---------------------------------------------------------------------------------------------
// Server factory
// ---------------------------------------------------------------------------------------------
function createFtpServer(options = {}) {
  const engine = new EngineClient(options.socket, options.handle);
  const paths = new SdPaths(options.root ?? '/');
  const context = {
    engine,
    paths,
    allowWrite: options.allowWrite === true,
    user: options.user ?? null,
    pass: options.pass ?? null,
    log: typeof options.log === 'function' ? options.log : () => {}
  };
  const sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket);
    const session = new FtpSession(context);
    socket.on('close', () => sockets.delete(socket));
    session.attach(socket);
  });
  return {
    server,
    engine,
    paths,
    context,
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

// ---------------------------------------------------------------------------------------------
// Probe / acquisition helpers
// ---------------------------------------------------------------------------------------------
function resolveProbeHandle(probePath, mountKey) {
  let probe;
  try { probe = JSON.parse(fs.readFileSync(probePath, 'utf8')); }
  catch (error) { throw Error('cannot read probe JSON ' + probePath + ': ' + error.message); }
  const sd = probe.sd || {};
  const openers = sd.openers || {};
  const mountProbes = sd.mountProbes || {};
  let handle = null;
  if (mountKey) {
    if (openers[mountKey] && openers[mountKey].handle) handle = openers[mountKey].handle;
    if (!handle && (mountKey === 'sd' || mountKey === 'cmd18') && sd.handle) handle = sd.handle;
    if (!handle) {
      const keys = Object.keys(mountProbes);
      const hit = keys.find(key => key === mountKey)
        || keys.find(key => key.split(/\s+/)[0] === mountKey)
        || keys.find(key => key.includes(mountKey));
      if (hit && mountProbes[hit].handle) handle = mountProbes[hit].handle;
    }
  } else if (sd.handle) {
    handle = sd.handle;
  }
  if (!handle) {
    const available = ['cmd18 (sd.handle)', ...Object.keys(openers), ...Object.keys(mountProbes).map(key => 'mount:' + key)];
    throw Error('cannot resolve an SD handle; pass --mount <key>. Available: ' + available.join(', '));
  }
  return {handle: Number(handle), socket: probe.socketPath || null, probe};
}

function readAcquisitionSocket(acquisitionPath) {
  const acquisition = JSON.parse(fs.readFileSync(acquisitionPath, 'utf8'));
  if (!acquisition.report) throw Error('current-acquisition.json has no "report" field');
  const report = JSON.parse(fs.readFileSync(acquisition.report, 'utf8'));
  const socketPath = report && report.memoryControl && report.memoryControl.socketPath;
  if (!socketPath) throw Error('report JSON has no memoryControl.socketPath');
  return {socket: String(socketPath), reportPath: acquisition.report};
}

// ---------------------------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------------------------
const USAGE = `CivSwitch SD FTP bridge

Usage: node sd-ftp.cjs --socket 127.0.0.1:PORT (--handle N | --probe <json> --mount <key>)
                       [--port 2121] [--root /] [--host 127.0.0.1]
                       [--user U --pass P] [--allow-write]

  --socket host:port  engine memoryControl endpoint (from current-acquisition.json -> report)
  --acquisition <json> read current-acquisition.json and take the socket from its report
  --handle N          SD IFileSystem handle (from a probe JSON: sd.handle or sd.openers.<key>.handle)
  --probe <json>      sd-probe result JSON; the handle is resolved from it
  --mount <key>       opener / mountProbes key inside --probe (default: cmd18 = sd.handle)
  --port N            FTP control port (default 2121)
  --root /            SD path that the FTP root maps to (e.g. --root /switch)
  --host 127.0.0.1    FTP control listen address
  --user/--pass       require these credentials (default: anonymous, any password)
  --allow-write       forward STOR/DELE/MKD/RMD/RNFR/RNTO (engine still needs NS2_ALLOW_WRITES=1)
`;

function parseArgs(argv) {
  const options = {socket: null, port: 2121, root: '/', handle: null, probe: null,
    acquisition: null, mount: null, user: null, pass: null, host: '127.0.0.1', allowWrite: false};
  const valued = {'--socket': 'socket', '--port': 'port', '--root': 'root', '--handle': 'handle',
    '--probe': 'probe', '--acquisition': 'acquisition', '--mount': 'mount', '--user': 'user',
    '--pass': 'pass', '--host': 'host'};
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index];
    if (argument === '--help' || argument === '-h') { console.log(USAGE); process.exit(0); }
    if (argument === '--allow-write') { options.allowWrite = true; continue; }
    if (argument === '--read-only') { options.allowWrite = false; continue; }
    const key = valued[argument];
    if (!key) throw Error('unknown argument: ' + argument + '\n\n' + USAGE);
    const value = argv[++index];
    if (value === undefined) throw Error('missing value for ' + argument);
    options[key] = value;
  }
  options.port = Number(options.port);
  if (!Number.isInteger(options.port) || options.port < 1 || options.port > 65535) {
    throw Error('--port must be 1..65535');
  }
  if (options.handle !== null) {
    options.handle = Number(options.handle);
    if (!Number.isInteger(options.handle) || options.handle <= 0) throw Error('--handle must be a positive integer');
  }
  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.acquisition) {
    const resolved = readAcquisitionSocket(options.acquisition);
    if (!options.socket) options.socket = resolved.socket;
  }
  if (options.probe) {
    const resolved = resolveProbeHandle(options.probe, options.mount);
    if (!options.handle) options.handle = resolved.handle;
    if (!options.socket && resolved.socket) options.socket = resolved.socket;
    if (!options.mount) options.mount = 'cmd18';
  }
  if (!options.socket) throw Error('missing --socket (engine memoryControl endpoint)');
  if (!options.handle) throw Error('missing --handle or --probe/--mount');
  const ftp = createFtpServer({
    socket: options.socket,
    handle: options.handle,
    root: options.root,
    user: options.user,
    pass: options.pass,
    allowWrite: options.allowWrite,
    log: message => console.error('[sd-ftp] ' + message)
  });
  const address = await ftp.listen(options.port, options.host);
  console.log('[sd-ftp] listening on ftp://' + options.host + ':' + address.port);
  console.log('[sd-ftp] engine=' + options.socket + ' handle=' + options.handle +
    ' root=' + ftp.paths.root + (options.allowWrite ? ' mode=read-write' : ' mode=read-only (use --allow-write)'));
  console.log('[sd-ftp] engine-side mutations also require NS2_ALLOW_WRITES=1 in the console engine process');
  const shutdown = () => { ftp.close().finally(() => process.exit(0)); };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

if (require.main === module) {
  main().catch(error => {
    console.error('[sd-ftp] ' + error.message);
    process.exit(1);
  });
}

module.exports = {EngineClient, SdPaths, resolveVirtual, normalizeVirtual, listEntry,
  createFtpServer, resolveProbeHandle, readAcquisitionSocket, parseArgs};
