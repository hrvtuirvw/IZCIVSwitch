#!/usr/bin/env node
// Minimal FTP client smoke test used to prove the sd-ftp bridge against a live engine.
// Raw sockets only (no deps): login, TYPE I, walk up to two directory levels, LIST, RETR.
// Usage: node ftp-smoke.cjs <host> <port> [--user U] [--pass P] [--out <dir>]
const net = require('net');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const argv = process.argv.slice(2);
const host = argv[0] || '127.0.0.1';
const port = Number(argv[1] || 2121);
let user = 'anonymous', pass = 'anonymous', outDir = null;
for (let i = 2; i < argv.length; i++) {
  if (argv[i] === '--user') user = argv[++i];
  else if (argv[i] === '--pass') pass = argv[++i];
  else if (argv[i] === '--out') outDir = argv[++i];
}

const summary = {host, port, steps: [], ok: false};
const record = (name, payload) => {
  summary.steps.push({name, ...payload});
  console.log('[' + name + ']', JSON.stringify(payload));
};

function session() {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({host, port});
    socket.setEncoding('utf8');
    let buffer = '';
    const queue = [];
    const waiters = [];
    socket.on('data', chunk => {
      buffer += chunk;
      let index;
      while ((index = buffer.indexOf('\r\n')) >= 0) {
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        const waiter = waiters.shift();
        if (waiter) waiter(line);
        else queue.push(line);
      }
    });
    socket.on('error', reject);
    const readLine = () => (queue.length ? Promise.resolve(queue.shift()) : new Promise(res => waiters.push(res)));
    const command = async (text, okPrefixes) => {
      socket.write(text + '\r\n');
      let line = await readLine();
      while (/^\d{3}-/.test(line)) line = await readLine();
      if (okPrefixes && !okPrefixes.some(prefix => line.startsWith(prefix))) {
        throw Error(text + ' -> ' + line);
      }
      return line;
    };
    const pasv = async () => {
      const line = await command('PASV', ['227']);
      const match = /(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)/.exec(line);
      if (!match) throw Error('bad PASV reply: ' + line);
      return {host: match.slice(1, 5).join('.'), port: Number(match[5]) * 256 + Number(match[6])};
    };
    const dataCommand = async (text, target) => {
      const {host: dh, port: dp} = await pasv();
      const chunks = [];
      const dataSocket = net.createConnection({host: dh, port: dp});
      const done = new Promise((res, rej) => {
        dataSocket.on('data', chunk => chunks.push(chunk));
        dataSocket.on('end', res);
        dataSocket.on('error', rej);
      });
      const reply = await command((target ? text + ' ' + target : text), ['125', '150']);
      await done;
      let finish = await readLine();
      while (/^\d{3}-/.test(finish)) finish = await readLine();
      if (!/^2\d\d/.test(finish)) throw Error('data finish -> ' + finish);
      return {reply, finish, bytes: Buffer.concat(chunks)};
    };
    socket.on('connect', () => resolve({command, dataCommand, readLine, close: () => socket.destroy()}));
  });
}

const parseEntry = line => {
  const match = /^([-dl])(?:[rwx-]{9})\S*\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\S+\s+\d+\s+[\d:]+)\s+(.+)$/.exec(line);
  if (!match) return null;
  return {type: match[1], size: Number(match[2]), name: match[4]};
};

(async () => {
  let ctrl = null;
  try {
    ctrl = await session();
    record('greeting', {reply: await ctrl.readLine()});
    const userReply = await ctrl.command('USER ' + user, ['230', '331']);
    record('login', {user: userReply});
    if (userReply.startsWith('331')) record('password', {reply: await ctrl.command('PASS ' + pass, ['230'])});
    record('type', {reply: await ctrl.command('TYPE I', ['200'])});

    const walk = async (dir, depth) => {
      const listing = await ctrl.dataCommand('LIST', dir === '/' ? null : dir);
      const lines = listing.bytes.toString('utf8').split('\r\n').filter(Boolean);
      const entries = lines.map(parseEntry).filter(Boolean);
      record('list', {dir, count: entries.length, entries: entries.slice(0, 20)});
      const files = [];
      for (const entry of entries) {
        if (entry.type === '-') files.push({dir, entry});
        else if (entry.type === 'd' && depth > 0) {
          files.push(...await walk((dir === '/' ? '' : dir) + '/' + entry.name, depth - 1));
        }
      }
      return files;
    };

    const files = await walk('/', 4);
    summary.files = files.map(item => ({name: item.entry.name, size: item.entry.size, dir: item.dir}));
    record('files', {count: files.length, files: summary.files.slice(0, 16)});
    if (!files.length) {
      record('retr', {skipped: 'no regular file found'});
    } else {
      const first = files[0];
      const remote = (first.dir === '/' ? '' : first.dir) + '/' + first.entry.name;
      const got = await ctrl.dataCommand('RETR', remote);
      const bytes = got.bytes;
      const result = {path: remote, expectedSize: first.entry.size, length: bytes.length,
        sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
        hex: bytes.subarray(0, 64).toString('hex'), reply: got.reply, finish: got.finish};
      if (outDir) {
        fs.mkdirSync(outDir, {recursive: true});
        const target = path.join(outDir, path.basename(remote));
        fs.writeFileSync(target, bytes);
        result.savedTo = target;
      }
      record('retr', result);
    }
    summary.ok = true;
  } catch (error) {
    summary.error = error.message;
    console.log('[error]', error.message);
  } finally {
    if (ctrl) ctrl.close();
  }
  const out = path.join(outDir || '.', 'ftp-smoke-result.json');
  try { fs.mkdirSync(path.dirname(out), {recursive: true}); fs.writeFileSync(out, JSON.stringify(summary, null, 1)); } catch {}
  console.log('SMOKE ' + (summary.ok ? 'OK' : 'FAIL') + ' -> ' + out);
  process.exit(summary.ok ? 0 : 1);
})();
