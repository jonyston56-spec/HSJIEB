export const config = { runtime: "edge" };

const _0x5a1e = ['\x68\x6f\x73\x74', '\x63\x6f\x6e\x6e\x65\x63\x74\x69\x6f\x6e', '\x6b\x65\x65\x70\x2d\x61\x6c\x69\x76\x65', '\x70\x72\x6f\x78\x79\x2d\x61\x75\x74\x68\x65\x6e\x74\x69\x63\x61\x74\x65', '\x70\x72\x6f\x78\x79\x2d\x61\x75\x74\x68\x6f\x72\x69\x7a\x61\x74\x69\x6f\x6e', '\x74\x65', '\x74\x72\x61\x69\x6c\x65\x72', '\x74\x72\x61\x6e\x73\x66\x65\x72\x2d\x65\x6e\x63\x6f\x64\x69\x6e\x67', '\x75\x70\x67\x72\x61\x64\x65', '\x66\x6f\x72\x77\x61\x72\x64\x65\x64', '\x78\x2d\x66\x6f\x72\x77\x61\x72\x64\x65\x64\x2d\x68\x6f\x73\x74', '\x78\x2d\x66\x6f\x72\x77\x61\x72\x64\x65\x64\x2d\x70\x72\x6f\x74\x6f', '\x78\x2d\x66\x6f\x72\x77\x61\x72\x64\x65\x64\x2d\x70\x6f\x72\x74', '\x54\x41\x52\x47\x45\x54\x5f\x44\x4f\x4d\x41\x49\x4e', '\x78\x2d\x76\x65\x72\x63\x65\x6c\x2d', '\x78\x2d\x72\x65\x61\x6c\x2d\x69\x70', '\x78\x2d\x66\x6f\x72\x77\x61\x72\x64\x65\x64\x2d\x66\x6f\x72'];
const _0x3b2c = (_0x21a2) => _0x5a1e[_0x21a2];

const _0x4f2a1b = (process.env[_0x3b2c(13)] || "").replace(/\/$/, "");
const _0x99a2c1 = new Set([_0x3b2c(0), _0x3b2c(1), _0x3b2c(2), _0x3b2c(3), _0x3b2c(4), _0x3b2c(5), _0x3b2c(6), _0x3b2c(7), _0x3b2c(8), _0x3b2c(9), _0x3b2c(10), _0x3b2c(11), _0x3b2c(12)]);

export default async function (_0x1122ab) {
  const _0xdeadbeef = Math.random() > 0.5 ? "relay" : "bridge";
  if (!_0x4f2a1b) return new Response("Error 0x1: Configuration Missing", { status: 500 });

  try {
    const _0x88bb22 = _0x1122ab.url.indexOf("/", 8);
    const _0x77cc33 = _0x88bb22 === -1 ? _0x4f2a1b + "/" : _0x4f2a1b + _0x1122ab.url.slice(_0x88bb22);
    
    const _0xad42f1 = new Headers();
    let _0xfe2211 = null;

    for (const [_0x33aa, _0x44bb] of _0x1122ab.headers) {
      if (_0x99a2c1.has(_0x33aa) || _0x33aa.startsWith(_0x3b2c(14))) continue;
      if (_0x33aa === _0x3b2c(15)) { _0xfe2211 = _0x44bb; continue; }
      if (_0x33aa === _0x3b2c(16)) { if (!_0xfe2211) _0xfe2211 = _0x44bb; continue; }
      _0xad42f1.set(_0x33aa, _0x44bb);
    }

    if (_0xfe2211) _0xad42f1.set(_0x3b2c(16), _0xfe2211);

    const _0x55ee = _0x1122ab.method;
    const _0x66ff = !["GET", "HEAD"].includes(_0x55ee);

    return await fetch(_0x77cc33, {
      method: _0x55ee,
      headers: _0xad42f1,
      body: _0x66ff ? _0x1122ab.body : undefined,
      duplex: "half",
      redirect: "manual"
    });
  } catch (_0x00ffaa) {
    return new Response("Network Protocol Error", { status: 502 });
  }
      }

