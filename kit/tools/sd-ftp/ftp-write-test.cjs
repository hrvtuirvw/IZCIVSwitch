#!/usr/bin/env node
// SD write self-test over the sd-ftp bridge (patch 19 write commands + patch 20 held session).
// Creates a scratch directory on the mounted filesystem, uploads a deterministic 64 KiB file,
// verifies size + sha256 by downloading it again, then deletes the file and the directory.
// Usage: node ftp-write-test.cjs <host> <port> [--dir /CivSwitch-selftest] [--out <dir>]
const net = require('net');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const argv = process.argv.slice(2);
const host = argv[0] || '127.0.0.1';
const port = Number(argv[1] || 2121);
let workDir = '/CivSwitch-selftest';
let outDir = null;
for (let i = 2; i < argv.length; i++) {
  if (argv[i] === '--dir') workDir = argv[++i];
  else if (argv[i] === '--out') outDir = argv[++i];
}
if (!workDir.startsWith('/')) workDir = '/' + workDir;
const filePath = (workDir === '/' ? '' : workDir) + '/payload.bin';

const PAYLOAD = Buffer.alloc(64 * 1024);
for (let i = 0; i < PAYLOAD.length; i++) PAYLOAD[i] = (i * 37 + 11) & 0xff;
const PAYLOAD_SHA = crypto.createHash('sha256').update(PAYLOAD).digest('hex');

const summary = {host, port, workDir, payloadBytes: PAYLOAD.length, payloadSha256: PAYLOAD_SHA, steps: [], ok: false};
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
    const readReply = async () => {
      let line = await readLine();
      while (/^\d{3}-/.test(line)) line = await readLine();
      return line;
    };
    const command = async (text, okPrefixes) => {
      socket.write(text + '\r\n');
      const line = await readReply();
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
    const download = async (target) => {
      const {host: dh, port: dp} = await pasv();
      const chunks = [];
      const dataSocket = net.createConnection({host: dh, port: dp});
      const done = new Promise((res, rej) => {
        dataSocket.on('data', chunk => chunks.push(chunk));
        dataSocket.on('end', res);
        dataSocket.on('error', rej);
      });
      const reply = await command('RETR ' + target, ['125', '150']);
      await done;
      const finish = await readReply();
      if (!/^2\d\d/.test(finish)) throw Error('retr finish -> ' + finish);
      return {reply, finish, bytes: Buffer.concat(chunks)};
    };
    const upload = async (target, bytes) => {
      const {host: dh, port: dp} = await pasv();
      const dataSocket = net.createConnection({host: dh, port: dp});
      const step = await command('STOR ' + target, ['125', '150']);
      dataSocket.write(bytes);
      await new Promise(res => dataSocket.end(res));
      const finish = await readReply();
      if (!/^2\d\d/.test(finish)) throw Error('stor finish -> ' + finish);
      return {reply: step, finish, sent: bytes.length};
    };
    socket.on('connect', () => resolve({command, readReply, download, upload, close: () => socket.destroy()}));
  });
}

const parseEntry = line => {
  const match = /^([-dl])(?:[rwx-]{9})\S*\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\S+\s+\d+\s+[\d:]+)\s+(.+)$/.exec(line);
  if (!match) return null;
  return {type: match[1], size: Number(match[2]), name: match[4]};
};

const list = async (ctrl, dir) => {
  const listing = await ctrl.command('PASV', ['227']);
  const match = /(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)/.exec(listing);
  const dh = match.slice(1, 5).join('.');
  const dp = Number(match[5]) * 256 + Number(match[6]);
  const chunks = [];
  const dataSocket = net.createConnection({host: dh, port: dp});
  const done = new Promise((res, rej) => {
    dataSocket.on('data', chunk => chunks.push(chunk));
    dataSocket.on('end', res);
    dataSocket.on('error', rej);
  });
  await ctrl.command('LIST ' + dir, ['125', '150']);
  await done;
  const finish = await ctrl.readReply();
  const lines = Buffer.concat(chunks).toString('utf8').split('\r\n').filter(Boolean);
  const entries = lines.map(parseEntry).filter(Boolean);
  record('list', {dir, finish, count: entries.length, entries: entries.slice(0, 20)});
  return entries;
};

(async () => {
  let ctrl = null;
  const checks = [];
  const check = (name, ok, detail) => {
    checks.push({name, ok, detail});
    console.log('[check ' + (ok ? 'PASS' : 'FAIL') + '] ' + name + (detail ? ' :: ' + detail : ''));
    return ok;
  };
  try {
    ctrl = await session();
    record('greeting', {reply: await ctrl.readReply()});
    const userReply = await ctrl.command('USER anonymous', ['230', '331']);
    record('login', {user: userReply});
    if (userReply.startsWith('331')) record('password', {reply: await ctrl.command('PASS anonymous', ['230'])});
    record('type', {reply: await ctrl.command('TYPE I', ['200'])});

    // 0. scratch directory starts absent: clean up leftovers from an interrupted earlier run.
    let leftovers = [];
    try {
      leftovers = await list(ctrl, workDir);
      record('pre-list', {dir: workDir, leftovers: leftovers.slice(0, 20)});
    } catch (error) {
      record('pre-list', {dir: workDir, absent: true, reply: error.message});
    }
    if (leftovers.length) {
      for (const item of leftovers) {
        try {
          await ctrl.command('DELE ' + workDir + '/' + item.name, ['250']);
        } catch (error) {
          record('pre-clean-delete-gap', {name: item.name, error: error.message});
        }
      }
      try {
        await ctrl.command('RMD ' + workDir, ['250']);
        record('pre-clean', {dir: workDir, removed: true});
      } catch (error) {
        record('pre-clean-gap', {dir: workDir, error: error.message});
      }
    }

    // 1. MKD
    const mkd = await ctrl.command('MKD ' + workDir, ['257']);
    check('mkdir', true, mkd);

    // 2. STOR 64 KiB
    const stor = await ctrl.upload(filePath, PAYLOAD);
    check('stor', true, JSON.stringify(stor));

    // 3. SIZE
    const size = await ctrl.command('SIZE ' + filePath, ['213']);
    const sizeMatch = /^\d{3}\s+(\d+)/.exec(size);
    const sizeValue = sizeMatch ? Number(sizeMatch[1]) : NaN;
    check('size', sizeValue === PAYLOAD.length, 'sftp=' + size + ' expected=' + PAYLOAD.length);

    // 4. RETR + sha256
    const got = await ctrl.download(filePath);
    const sha = crypto.createHash('sha256').update(got.bytes).digest('hex');
    check('retr', got.bytes.length === PAYLOAD.length && sha === PAYLOAD_SHA,
      'length=' + got.bytes.length + ' sha256=' + sha);

    // 5. LIST sees the file
    const after = await list(ctrl, workDir);
    const entry = after.find(item => item.name === 'payload.bin');
    check('list-entry', !!entry && entry.size === PAYLOAD.length, entry ? 'size=' + entry.size : 'missing');

    // 6. DELE
    const dele = await ctrl.command('DELE ' + filePath, ['250']);
    check('delete-file', true, dele);

    // 7. RMD
    const rmd = await ctrl.command('RMD ' + workDir, ['250']);
    check('delete-dir', true, rmd);

    // 8. directory is gone
    let gone = false;
    try {
      await ctrl.command('LIST ' + workDir, ['125', '150']);
    } catch (error) {
      gone = true;
    }
    check('dir-gone', gone, gone ? 'LIST now fails as expected' : 'LIST still succeeds');

    summary.ok = checks.every(item => item.ok);
  } catch (error) {
    summary.error = error.message;
    console.log('[error]', error.message);
  } finally {
    summary.checks = checks;
    if (ctrl) ctrl.close();
  }
  if (outDir) {
    try { fs.mkdirSync(outDir, {recursive: true}); } catch {}
  }
  const out = path.join(outDir || '.', 'ftp-write-test-result.json');
  try { fs.writeFileSync(out, JSON.stringify(summary, null, 1)); } catch {}
  console.log('WRITE TEST ' + (summary.ok ? 'OK' : 'FAIL') + ' -> ' + out);
  process.exit(summary.ok ? 0 : 1);
})();
