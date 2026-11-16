import sys, os, struct, lzma, bz2, zlib, io

class R:
    def __init__(s, b, p=0): s.b, s.p = b, p
    def u8(s): v = s.b[s.p]; s.p += 1; return v
    def rd(s, n): v = s.b[s.p:s.p+n]; s.p += n; return v
    def num(s):
        f = s.u8(); m = 0x80; v = 0
        for i in range(8):
            if f & m == 0:
                return v | ((f & (m-1)) << (8*i))
            v |= s.u8() << (8*i); m >>= 1
        return v
    def bits(s, n):
        out = []; mask = 0; cur = 0
        for i in range(n):
            if mask == 0: cur = s.u8(); mask = 0x80
            out.append(bool(cur & mask)); mask >>= 1
        return out
    def defbits(s, n):
        if s.u8(): return [True]*n
        return s.bits(n)

def crcs(r, n):
    d = r.defbits(n)
    return [struct.unpack('<I', r.rd(4))[0] if x else None for x in d]

def streams_info(r):
    pack_pos = 0; pack_sizes = []; folders = []; unp = []; nums = None; subsizes = None
    while True:
        t = r.u8()
        if t == 0: break
        if t == 6:
            pack_pos = r.num(); n = r.num()
            while True:
                tt = r.u8()
                if tt == 0: break
                if tt == 9: pack_sizes = [r.num() for _ in range(n)]
                elif tt == 10: crcs(r, n)
        elif t == 7:
            assert r.u8() == 0x0B
            nf = r.num(); assert r.u8() == 0
            for _ in range(nf):
                nc = r.num(); coders = []; nin = 0; nout = 0
                for _ in range(nc):
                    fl = r.u8(); idl = fl & 0xF
                    cid = bytes(r.rd(idl))
                    if fl & 0x10: ci = r.num(); co = r.num()
                    else: ci = co = 1
                    props = bytes(r.rd(r.num())) if fl & 0x20 else b''
                    coders.append((cid, ci, co, props)); nin += ci; nout += co
                bp = [(r.num(), r.num()) for _ in range(nout-1)]
                npk = nin - len(bp)
                if npk == 1:
                    used = {b[0] for b in bp}
                    pk = [i for i in range(nin) if i not in used]
                else:
                    pk = [r.num() for _ in range(npk)]
                folders.append(dict(coders=coders, bp=bp, pk=pk, nout=nout))
            assert r.u8() == 0x0C
            for f in folders:
                f['unp'] = [r.num() for _ in range(f['nout'])]
            while True:
                tt = r.u8()
                if tt == 0: break
                if tt == 0x0A: crcs(r, nf)
        elif t == 8:
            nums = [1]*len(folders); subsizes = None
            tt = r.u8()
            if tt == 0x0D:
                nums = [r.num() for _ in folders]; tt = r.u8()
            if tt == 9:
                subsizes = []
                for f, n in zip(folders, nums):
                    if n == 0: subsizes.append([]); continue
                    tot = f['unp'][-1] if False else main_unp(f)
                    sz = [r.num() for _ in range(n-1)]
                    sz.append(tot - sum(sz)); subsizes.append(sz)
                tt = r.u8()
            while tt != 0:
                if tt == 0x0A:
                    nd = sum(n for f, n in zip(folders, nums))
                    crcs(r, nd)
                else: raise Exception('substream %x' % tt)
                tt = r.u8()
            if subsizes is None:
                subsizes = [[main_unp(f)] if n == 1 else [] for f, n in zip(folders, nums)]
        else:
            raise Exception('si %x' % t)
    if nums is None:
        nums = [1]*len(folders); subsizes = [[main_unp(f)] for f in folders]
    return pack_pos, pack_sizes, folders, nums, subsizes

def main_unp(f):
    used = {b[1] for b in f['bp']}
    for i in range(f['nout']):
        if i not in used: return f['unp'][i]

def dec_folder(data, f):
    coders = f['coders']
    filters = []
    single = None
    for cid, ci, co, props in coders:
        if cid == b'\x21':
            dsz = props[0]
            ds = (2 | (dsz & 1)) << (dsz // 2 + 11) if dsz < 40 else 0xFFFFFFFF
            filters.append({'id': lzma.FILTER_LZMA2, 'dict_size': ds})
        elif cid == b'\x03\x01\x01':
            lc_lp_pb = props[0]; ds = struct.unpack('<I', props[1:5])[0]
            lc = lc_lp_pb % 9; r_ = lc_lp_pb // 9; lp = r_ % 5; pb = r_ // 5
            filters.append({'id': lzma.FILTER_LZMA1, 'dict_size': ds, 'lc': lc, 'lp': lp, 'pb': pb})
        elif cid == b'\x03\x03\x01\x03':
            filters.append({'id': lzma.FILTER_X86})
        elif cid == b'\x00':
            single = 'copy'
        elif cid == b'\x04\x02\x02':
            single = 'bz2'
        elif cid == b'\x04\x01\x08':
            single = 'deflate'
        else:
            raise Exception('coder %s' % cid.hex())
    size = main_unp(f)
    if single == 'copy': return data[:size]
    if single == 'bz2': return bz2.decompress(data)
    if single == 'deflate': return zlib.decompress(data, -15)
    # xz-style filter chain: reverse of 7z order (7z lists coders from outermost)
    d = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters[::-1] if len(filters) > 1 and filters[0]['id'] == lzma.FILTER_X86 and False else filters)
    out = d.decompress(data, max_length=size)
    return out

def open7z(path):
    b = open(path, 'rb').read()
    assert b[:6] == b"7z\xbc\xaf\x27\x1c"
    off, size = struct.unpack('<QQ', b[12:28])
    hdr = b[32+off:32+off+size]
    while True:
        r = R(hdr); t = r.u8()
        if t == 0x17:
            pp, ps, fo, nums, ss = streams_info(r)
            pos = 32 + pp; out = []
            for f, sz in zip(fo, ps):
                pass
            hdr = dec_folder(b[pos:pos+ps[0]], fo[0])
            continue
        assert t == 1, t
        break
    pack_pos = 0; pack_sizes = []; folders = []; nums = []; subsizes = []
    files = []
    while True:
        t = r.u8()
        if t == 0: break
        if t == 2: raise Exception('archive props')
        elif t == 3: raise Exception('additional streams')
        elif t == 4:
            pack_pos, pack_sizes, folders, nums, subsizes = streams_info(r)
        elif t == 5:
            n = r.num(); empty = [False]*n; emptyfile = None; names = []; attrs = [None]*n
            nes = 0
            while True:
                pt = r.u8()
                if pt == 0: break
                sz = r.num(); sub = R(r.rd(sz))
                if pt == 0x0E: empty = sub.bits(n); nes = sum(empty)
                elif pt == 0x0F: emptyfile = sub.bits(nes)
                elif pt == 0x11:
                    assert sub.u8() == 0
                    raw = sub.b[sub.p:]
                    names = raw.decode('utf-16-le').split('\x00')[:n]
                elif pt == 0x15:
                    d = sub.defbits(n); sub.u8()
                    for i in range(n):
                        if d[i]: attrs[i] = struct.unpack('<I', sub.rd(4))[0]
            ei = 0
            for i in range(n):
                isdir = False; isempty = empty[i]
                if isempty:
                    isfile = emptyfile[ei] if emptyfile else False
                    ei += 1
                    isdir = not isfile
                files.append(dict(name=names[i], empty=isempty, dir=isdir, attr=attrs[i]))
    return b, pack_pos, pack_sizes, folders, nums, subsizes, files

def extract(path, dest):
    b, pp, ps, folders, nums, subsizes, files = open7z(path)
    pos = 32 + pp; pi = 0
    streams = []
    for f, n, sz in zip(folders, nums, subsizes):
        npk = len(f['pk'])
        data = b[pos:pos+ps[pi]]; pos += sum(ps[pi:pi+npk]); pi += npk
        out = dec_folder(data, f)
        o = 0
        for s in sz:
            streams.append(out[o:o+s]); o += s
    si = 0; cnt = 0
    for fi in files:
        p = os.path.join(dest, fi['name'])
        if fi['dir']:
            os.makedirs(p, exist_ok=True); continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if fi['empty']:
            open(p, 'wb').close()
        else:
            open(p, 'wb').write(streams[si]); si += 1
        cnt += 1
    return cnt

if __name__ == '__main__':
    print(extract(sys.argv[1], sys.argv[2]), 'files')
