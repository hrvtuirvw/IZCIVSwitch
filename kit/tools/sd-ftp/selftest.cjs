#!/usr/bin/env node
'use strict';
// Offline self-test for the CivSwitch SD FTP bridge.
//
// Starts mock-engine.cjs (in-memory fake console engine) plus sd-ftp.cjs and drives the FTP
// server with a hand-written FTP client. No console, no real engine, no network beyond localhost.
//
//   node selftest.cjs
//
// Prints PASS/FAIL per case and exits 0 only when everything passed.
const net = require('node:net');
const {once} = require('node:events');
const {createMockEngine} = require('./mock-engine.cjs');
const {createFtpServer, EngineClient} = require('./sd-ftp.cjs');

const HANDLE = 77398408;
const HELLO = Buffer.from('hello from civswitch\n', 'utf8');
const DATA_BIN = Buffer.from(Array.from({length: 256}, (_, i) => i));
const UPLOAD = Buffer.alloc(40000);
for (let i = 0; i < UPLOAD.length; i++) UPLOAD[i] = (i * 31 + 7) & 0xff;

const results = [];

function record(name, ok, message) {
  results.push({name, ok, message});
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok || !message ? '' : ' -> ' + message));
}

async function test(name, fn) {
  try {
    await fn();
    record(name, true);
  } catch (error) {
    record(name, false, error && error.message ? error.message : String(error));
  }
}

function assert(condition, message) {
  if (!condition) throw Error(message);
}

function assertCode(reply, expected, label) {
  assert(reply && reply.code === expected,
    (label || 'reply') + ': expected ' + expected + ', got ' + (reply && reply.code) +
    ' [' + (reply ? reply.lines.join(' | ') : 'no reply') + ']');
}

function assertText(text, needle, label) {
  assert(String(text).includes(needle), (label || 'text') + ': expected to contain "' + needle + '", got "' + text + '"');
}

async function assertRejects(fn, pattern, label) {
  let error = null;
  try { await fn(); } catch (caught) { error = caught; }
  assert(error, (label || 'call') + ': expected a rejection');
  if (pattern) assert(pattern.test(error.message), (label || 'call') + ': unexpected error "' + error.message + '"');
}

async function readAll(socket) {
  const chunks = [];
  socket.on('data', chunk => chunks.push(chunk));
  socket.on('error', () => {});
  await new Promise(resolve => {
    socket.once('end', resolve);
    socket.once('close', resolve);
  });
  return Buffer.concat(chunks);
}

// ---------------------------------------------------------------------------------------------
// Minimal FTP client
// ---------------------------------------------------------------------------------------------
class FtpClient {
  constructor(socket) {
    this.socket = socket;
    this.buffer = '';
    this.lines = [];
    this.waiters = [];
    this.closed = false;
    this.welcome = null;
    socket.setEncoding('utf8');
    socket.on('data', chunk => {
      this.buffer += chunk;
      let index;
      while ((index = this.buffer.indexOf('\n')) >= 0) {
        const line = this.buffer.slice(0, index).replace(/\r$/, '');
        this.buffer = this.buffer.slice(index + 1);
        const waiter = this.waiters.shift();
        if (waiter) waiter(line); else this.lines.push(line);
      }
    });
    socket.on('error', () => {});
    socket.on('close', () => {
      this.closed = true;
      while (this.waiters.length) this.waiters.shift()(null);
      this.waiters = [];
    });
  }

  static async connect(port, host = '127.0.0.1') {
    const socket = net.createConnection({host, port});
    await once(socket, 'connect');
    const client = new FtpClient(socket);
    client.welcome = await client.reply();
    return client;
  }

  line(timeout = 15000) {
    if (this.lines.length) return Promise.resolve(this.lines.shift());
    if (this.closed) return Promise.reject(Error('FTP connection closed'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('timed out waiting for a control reply')), timeout);
      this.waiters.push(line => {
        clearTimeout(timer);
        if (line === null) reject(Error('FTP connection closed'));
        else resolve(line);
      });
    });
  }

  async reply() {
    const first = await this.line();
    const match = /^(\d{3})([ -])(.*)$/.exec(first);
    if (!match) throw Error('malformed FTP reply: ' + first);
    const code = Number(match[1]);
    const lines = [match[3]];
    if (match[2] === '-') {
      for (;;) {
        const next = await this.line();
        const inner = /^(\d{3})([ -])(.*)$/.exec(next);
        if (inner && Number(inner[1]) === code && inner[2] === ' ') {
          lines.push(inner[3]);
          break;
        }
        lines.push(next);
      }
    }
    return {code, lines, text: lines.join('\n')};
  }

  async send(command) {
    this.socket.write(command + '\r\n');
    return this.reply();
  }

  async login(user = 'anonymous', pass = 'selftest@civswitch') {
    const userReply = await this.send('USER ' + user);
    const passReply = await this.send('PASS ' + pass);
    return {user: userReply, pass: passReply};
  }

  async pasv() {
    const reply = await this.send('PASV');
    assertCode(reply, 227, 'PASV');
    const match = /\((\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\)/.exec(reply.text);
    assert(match, 'PASV reply has no address: ' + reply.text);
    const host = [1, 2, 3, 4].map(index => Number(match[index])).join('.');
    const port = Number(match[5]) * 256 + Number(match[6]);
    const socket = net.createConnection({host, port});
    await once(socket, 'connect');
    return socket;
  }

  async epsv() {
    const reply = await this.send('EPSV');
    assertCode(reply, 229, 'EPSV');
    const match = /\(\|\|\|(\d+)\|\)/.exec(reply.text);
    assert(match, 'EPSV reply has no port: ' + reply.text);
    const socket = net.createConnection({host: '127.0.0.1', port: Number(match[1])});
    await once(socket, 'connect');
    return socket;
  }

  async listing(path, passive) {
    const data = await passive();
    const collected = readAll(data);
    const first = await this.send(('LIST ' + (path || '')).trim());
    if (first.code !== 150) {
      data.destroy();
      await collected.catch(() => {});
      return {first, final: first, lines: []};
    }
    const raw = (await collected).toString('utf8');
    const final = await this.reply();
    return {first, final, lines: raw.split('\r\n').filter(Boolean)};
  }

  list(path = '') { return this.listing(path, () => this.pasv()); }
  listEpsv(path = '') { return this.listing(path, () => this.epsv()); }

  async nlst(path = '') {
    const data = await this.pasv();
    const collected = readAll(data);
    const first = await this.send(('NLST ' + (path || '')).trim());
    if (first.code !== 150) {
      data.destroy();
      await collected.catch(() => {});
      return {first, final: first, names: []};
    }
    const raw = (await collected).toString('utf8');
    const final = await this.reply();
    return {first, final, names: raw.split('\r\n').filter(Boolean)};
  }

  async retr(path) {
    const data = await this.pasv();
    const collected = readAll(data);
    const first = await this.send('RETR ' + path);
    if (first.code !== 150) {
      data.destroy();
      await collected.catch(() => {});
      return {first, final: first, data: Buffer.alloc(0)};
    }
    const bytes = await collected;
    const final = await this.reply();
    return {first, final, data: bytes};
  }

  async stor(path, payload) {
    const data = await this.pasv();
    data.on('error', () => {});
    const first = await this.send('STOR ' + path);
    if (first.code !== 150) {
      data.destroy();
      return {first, final: first};
    }
    if (payload.length) data.write(payload);
    data.end();
    const final = await this.reply();
    data.destroy();
    return {first, final};
  }

  close() {
    if (!this.socket.destroyed) this.socket.destroy();
  }
}

// ---------------------------------------------------------------------------------------------
// Server pair helper
// ---------------------------------------------------------------------------------------------
async function pair(engineOptions = {}, ftpOptions = {}) {
  const engine = createMockEngine(engineOptions);
  const engineAddress = await engine.listen(0);
  const socket = '127.0.0.1:' + engineAddress.port;
  const server = createFtpServer(Object.assign({socket, handle: HANDLE}, ftpOptions));
  const ftpAddress = await server.listen(0);
  const client = await FtpClient.connect(ftpAddress.port);
  return {
    engine,
    server,
    client,
    socket,
    handle: HANDLE,
    async close() {
      client.close();
      await server.close();
      await engine.close();
    }
  };
}

// ---------------------------------------------------------------------------------------------
// Test blocks
// ---------------------------------------------------------------------------------------------
async function testReadWrite() {
  const context = await pair({}, {allowWrite: true});
  const {client} = context;
  try {
    await test('banner 220 on connect', async () => {
      assertCode(client.welcome, 220, 'welcome');
    });

    await test('USER/PASS anonymous login', async () => {
      const login = await client.login();
      assertCode(login.user, 331, 'USER');
      assertCode(login.pass, 230, 'PASS');
    });

    await test('SYST returns UNIX type', async () => {
      const reply = await client.send('SYST');
      assertCode(reply, 215, 'SYST');
      assertText(reply.text, 'UNIX', 'SYST');
    });

    await test('TYPE I accepted', async () => {
      assertCode(await client.send('TYPE I'), 200, 'TYPE I');
    });

    await test('FEAT multiline reply', async () => {
      const reply = await client.send('FEAT');
      assertCode(reply, 211, 'FEAT');
      assert(reply.lines.some(line => /SIZE/.test(line)), 'FEAT lists SIZE: ' + reply.text);
    });

    await test('PWD reports virtual root', async () => {
      const reply = await client.send('PWD');
      assertCode(reply, 257, 'PWD');
      assertText(reply.text, '"/"', 'PWD');
    });

    await test('LIST / shows seeded tree', async () => {
      const listing = await client.list('/');
      assertCode(listing.first, 150, 'LIST first');
      assertCode(listing.final, 226, 'LIST final');
      const names = listing.lines.map(line => line.split(/\s+/).pop());
      assert(names.includes('hello.txt'), 'LIST has hello.txt: ' + listing.lines.join(' | '));
      assert(names.includes('switch'), 'LIST has switch: ' + listing.lines.join(' | '));
      assert(listing.lines.some(line => /^drwxr-xr-x\s+.*\sswitch$/.test(line)), 'switch listed as directory');
      assert(listing.lines.some(line => /^-rw-r--r--\s+.*\shello\.txt$/.test(line)), 'hello.txt listed as file');
    });

    await test('LIST -la flags are tolerated', async () => {
      const listing = await client.list('-la /');
      assertCode(listing.final, 226, 'LIST -la');
      assert(listing.lines.some(line => line.endsWith(' hello.txt')), 'LIST -la has hello.txt');
    });

    await test('SIZE reports seed length', async () => {
      const reply = await client.send('SIZE /hello.txt');
      assertCode(reply, 213, 'SIZE');
      assertText(reply.text, String(HELLO.length), 'SIZE');
    });

    await test('RETR /hello.txt content matches', async () => {
      const transfer = await client.retr('/hello.txt');
      assertCode(transfer.first, 150, 'RETR first');
      assertCode(transfer.final, 226, 'RETR final');
      assert(transfer.data.equals(HELLO), 'RETR bytes differ: ' + transfer.data.length);
    });

    await test('RETR 256-byte binary content matches', async () => {
      const transfer = await client.retr('/switch/save/data.bin');
      assertCode(transfer.final, 226, 'RETR final');
      assert(transfer.data.equals(DATA_BIN), 'RETR data.bin differs');
    });

    await test('CWD / CDUP / PWD transitions', async () => {
      assertCode(await client.send('CWD /switch/save'), 250, 'CWD save');
      let reply = await client.send('PWD');
      assertText(reply.text, '"/switch/save"', 'PWD save');
      const listing = await client.list('');
      assertCode(listing.final, 226, 'LIST cwd');
      assert(listing.lines.some(line => line.endsWith(' data.bin')), 'listing in save dir');
      assertCode(await client.send('CDUP'), 250, 'CDUP');
      reply = await client.send('PWD');
      assertText(reply.text, '"/switch"', 'PWD after CDUP');
      assertCode(await client.send('CWD /'), 250, 'CWD /');
    });

    await test('NLST /switch lists save', async () => {
      const listing = await client.nlst('/switch');
      assertCode(listing.final, 226, 'NLST final');
      assert(listing.names.includes('save'), 'NLST names: ' + listing.names.join(','));
    });

    await test('MKD / CWD / RMD round trip', async () => {
      assertCode(await client.send('MKD /newdir'), 257, 'MKD');
      assertCode(await client.send('CWD /newdir'), 250, 'CWD newdir');
      const pwd = await client.send('PWD');
      assertText(pwd.text, '"/newdir"', 'PWD newdir');
      assertCode(await client.send('CDUP'), 250, 'CDUP newdir');
      assertCode(await client.send('RMD /newdir'), 250, 'RMD newdir');
    });

    await test('STOR 40000 bytes chunked across engine writes', async () => {
      const transfer = await client.stor('/upload.bin', UPLOAD);
      assertCode(transfer.first, 150, 'STOR first');
      assertCode(transfer.final, 226, 'STOR final');
      const size = await client.send('SIZE /upload.bin');
      assertCode(size, 213, 'SIZE upload');
      assertText(size.text, String(UPLOAD.length), 'SIZE upload');
      const back = await client.retr('/upload.bin');
      assert(back.data.equals(UPLOAD), 'uploaded bytes differ: ' + back.data.length);
    });

    await test('RNFR/RNTO renames a file', async () => {
      assertCode(await client.send('RNFR /upload.bin'), 350, 'RNFR');
      assertCode(await client.send('RNTO /renamed.bin'), 250, 'RNTO');
      const size = await client.send('SIZE /renamed.bin');
      assertText(size.text, String(UPLOAD.length), 'SIZE renamed');
      const listing = await client.list('/');
      const names = listing.lines.map(line => line.split(/\s+/).pop());
      assert(names.includes('renamed.bin'), 'listing has renamed.bin');
      assert(!names.includes('upload.bin'), 'listing no longer has upload.bin');
    });

    await test('DELE removes a file', async () => {
      assertCode(await client.send('DELE /renamed.bin'), 250, 'DELE');
      assertCode(await client.send('SIZE /renamed.bin'), 550, 'SIZE after DELE');
      const listing = await client.list('/');
      assert(!listing.lines.some(line => line.endsWith(' renamed.bin')), 'listing still has renamed.bin');
    });

    await test('rename and restore hello.txt', async () => {
      assertCode(await client.send('RNFR /hello.txt'), 350, 'RNFR hello');
      assertCode(await client.send('RNTO /hello-moved.txt'), 250, 'RNTO hello');
      const moved = await client.retr('/hello-moved.txt');
      assert(moved.data.equals(HELLO), 'moved hello content differs');
      assertCode(await client.send('RNFR /hello-moved.txt'), 350, 'RNFR back');
      assertCode(await client.send('RNTO /hello.txt'), 250, 'RNTO back');
    });

    await test('empty STOR creates a zero-byte file', async () => {
      const transfer = await client.stor('/empty.bin', Buffer.alloc(0));
      assertCode(transfer.first, 150, 'STOR empty first');
      assertCode(transfer.final, 226, 'STOR empty final');
      const size = await client.send('SIZE /empty.bin');
      assertCode(size, 213, 'SIZE empty');
      assertText(size.text, '0', 'SIZE empty');
      assertCode(await client.send('DELE /empty.bin'), 250, 'DELE empty');
    });

    await test('RMD refuses non-empty directory', async () => {
      assertCode(await client.send('RMD /switch'), 550, 'RMD non-empty');
      assertCode(await client.send('RMD /'), 550, 'RMD root');
    });

    await test('missing targets / bad commands are refused', async () => {
      assertCode(await client.send('DELE /nope.bin'), 550, 'DELE missing');
      assertCode(await client.send('MKD /switch'), 550, 'MKD existing');
      assertCode(await client.send('RETR /nope.bin'), 550, 'RETR missing');
      assertCode(await client.send('SIZE /switch'), 550, 'SIZE directory');
      assertCode(await client.send('TYPE B'), 504, 'TYPE B');
      assertCode(await client.send('PORT 127,0,0,1,4,1'), 502, 'PORT rejected');
    });

    await test('EPSV data connection works', async () => {
      const listing = await client.listEpsv('/');
      assertCode(listing.final, 226, 'EPSV LIST');
      assert(listing.lines.some(line => line.endsWith(' hello.txt')), 'EPSV listing has hello.txt');
    });
  } finally {
    await context.close();
  }
}

async function testReadOnlyBridge() {
  const context = await pair({allowWrites: true}, {allowWrite: false});
  const {client} = context;
  try {
    await test('read-only bridge: login ok', async () => {
      const login = await client.login();
      assertCode(login.pass, 230, 'PASS');
    });

    await test('read-only bridge: reads still work', async () => {
      const listing = await client.list('/');
      assertCode(listing.final, 226, 'LIST');
      const transfer = await client.retr('/hello.txt');
      assert(transfer.data.equals(HELLO), 'RETR differs');
    });

    await test('read-only bridge: STOR refused with 550', async () => {
      assertCode(await client.send('STOR /x.bin'), 550, 'STOR read-only');
    });

    await test('read-only bridge: DELE/MKD/RMD/RNFR/RNTO refused with 550', async () => {
      assertCode(await client.send('DELE /hello.txt'), 550, 'DELE read-only');
      assertCode(await client.send('MKD /x'), 550, 'MKD read-only');
      assertCode(await client.send('RMD /switch'), 550, 'RMD read-only');
      assertCode(await client.send('RNFR /hello.txt'), 550, 'RNFR read-only');
      assertCode(await client.send('RNTO /x'), 550, 'RNTO read-only');
    });
  } finally {
    await context.close();
  }
}

async function testEngineWritesDisabled() {
  const context = await pair({allowWrites: false}, {allowWrite: true});
  const {client, socket} = context;
  try {
    await test('engine-gate: login and LIST work', async () => {
      const login = await client.login();
      assertCode(login.pass, 230, 'PASS');
      const listing = await client.list('/');
      assertCode(listing.final, 226, 'LIST');
      assert(listing.lines.some(line => line.endsWith(' hello.txt')), 'LIST has hello.txt');
    });

    await test('engine-gate: STOR aborts with 451 (writes disabled)', async () => {
      const transfer = await client.stor('/x.bin', Buffer.from('nope', 'utf8'));
      assertCode(transfer.first, 150, 'STOR first');
      assertCode(transfer.final, 451, 'STOR final');
      assertText(transfer.final.text, 'writes disabled', 'STOR final');
    });

    await test('engine-gate: DELE/MKD refused', async () => {
      assertCode(await client.send('DELE /hello.txt'), 550, 'DELE');
      assertCode(await client.send('MKD /x'), 550, 'MKD');
      const size = await client.send('SIZE /hello.txt');
      assertCode(size, 213, 'SIZE still readable');
    });

    await test('engine-gate: direct EngineClient rejects mutations', async () => {
      const direct = new EngineClient(socket, HANDLE);
      const listed = await direct.list('/');
      assert(Array.isArray(listed.entries) && listed.entries.length, 'direct list failed');
      await assertRejects(() => direct.commit(), /writes disabled/, 'direct commit');
      await assertRejects(() => direct.delete('/hello.txt'), /writes disabled/, 'direct delete');
    });
  } finally {
    await context.close();
  }
}

async function testBusyRetry() {
  const engine = createMockEngine({busyReplies: 2});
  const address = await engine.listen(0);
  try {
    await test('EngineClient retries busy engine replies', async () => {
      const direct = new EngineClient('127.0.0.1:' + address.port, HANDLE);
      const listed = await direct.list('/');
      assert(Array.isArray(listed.entries) && listed.entries.some(entry => entry.name === 'hello.txt'),
        'list after busy retries failed: ' + JSON.stringify(listed));
      assert(engine.state.requests.length === 1, 'expected exactly one dispatched request, got ' + engine.state.requests.length);
    });
  } finally {
    await engine.close();
  }
}

async function testRenameFallback() {
  const context = await pair({failRename: true}, {allowWrite: true});
  const {client} = context;
  const payload = Buffer.from('rename fallback payload', 'utf8');
  try {
    await test('rename fallback: login', async () => {
      assertCode((await client.login()).pass, 230, 'PASS');
    });

    await test('rename fallback: file copied when engine rename fails', async () => {
      assertCode((await client.stor('/a.bin', payload)).final, 226, 'STOR a.bin');
      assertCode(await client.send('RNFR /a.bin'), 350, 'RNFR');
      const reply = await client.send('RNTO /b.bin');
      assertCode(reply, 250, 'RNTO');
      assertText(reply.text, 'copy fallback', 'RNTO fallback');
      const back = await client.retr('/b.bin');
      assert(back.data.equals(payload), 'fallback content differs');
      assertCode(await client.send('SIZE /a.bin'), 550, 'old name gone');
      assertCode(await client.send('DELE /b.bin'), 250, 'DELE b.bin');
    });

    await test('rename fallback: directory rename refused (no fallback)', async () => {
      assertCode(await client.send('MKD /dir1'), 257, 'MKD dir1');
      assertCode(await client.send('RNFR /dir1'), 350, 'RNFR dir1');
      assertCode(await client.send('RNTO /dir2'), 550, 'RNTO dir1');
      assertCode(await client.send('RMD /dir1'), 250, 'RMD dir1');
    });
  } finally {
    await context.close();
  }
}

async function testRootMapping() {
  const context = await pair({}, {allowWrite: true, root: '/switch/save'});
  const {client} = context;
  try {
    await test('--root mapping: FTP / maps to SD /switch/save', async () => {
      assertCode((await client.login()).pass, 230, 'PASS');
      const listing = await client.list('/');
      assertCode(listing.final, 226, 'LIST');
      const names = listing.lines.map(line => line.split(/\s+/).pop());
      assert(names.includes('data.bin'), 'mapped listing has data.bin: ' + names.join(','));
      assert(!names.includes('hello.txt'), 'mapped listing leaked root files');
      const transfer = await client.retr('/data.bin');
      assert(transfer.data.equals(DATA_BIN), 'mapped RETR differs');
      assertCode(await client.send('CWD /'), 250, 'CWD /');
    });
  } finally {
    await context.close();
  }
}

async function testAuth() {
  const context = await pair({}, {allowWrite: true, user: 'civ', pass: 'switch'});
  const {client} = context;
  try {
    await test('configured credentials: wrong password refused', async () => {
      const login = await client.login('civ', 'wrong');
      assertCode(login.pass, 530, 'PASS wrong');
    });

    await test('configured credentials: correct password accepted', async () => {
      const login = await client.login('civ', 'switch');
      assertCode(login.pass, 230, 'PASS correct');
      assertCode(await client.send('PWD'), 257, 'PWD after login');
    });
  } finally {
    await context.close();
  }
}

// ---------------------------------------------------------------------------------------------
async function main() {
  const timer = setTimeout(() => {
    console.error('selftest timed out after 180 s');
    process.exit(1);
  }, 180000);
  timer.unref();

  console.log('sd-ftp selftest: mock engine + FTP bridge on ephemeral localhost ports');
  console.log('');
  await testReadWrite();
  await testReadOnlyBridge();
  await testEngineWritesDisabled();
  await testBusyRetry();
  await testRenameFallback();
  await testRootMapping();
  await testAuth();

  const failed = results.filter(result => !result.ok);
  console.log('');
  console.log('selftest summary: ' + (results.length - failed.length) + ' passed, ' + failed.length + ' failed');
  if (failed.length) {
    for (const failure of failed) console.log('  FAILED: ' + failure.name + ' -> ' + failure.message);
    process.exit(1);
  }
  process.exit(0);
}

main().catch(error => {
  console.error('selftest crashed: ' + (error && error.stack ? error.stack : error));
  process.exit(1);
});
