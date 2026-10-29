"""Read selected public YawDD tar members via HTTP Range; never extract tar paths."""
import json
import urllib.request
import tarfile
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
URL = 'http://skuld.cs.umass.edu/traces/mmsys/2014/user06.tar'

def read_range(start, size):
    if size > 8*1024*1024:
        chunk = 4*1024*1024
        segments = [(s,min(chunk,start+size-s)) for s in range(start,start+size,chunk)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            parts = []
            for i,data in enumerate(pool.map(lambda item: read_range(*item),segments)):
                parts.append(data)
                print(f'Downloaded {(i+1)*chunk/1024**2:.0f}/{size/1024**2:.0f} MiB',flush=True)
        return b''.join(parts)
    req = urllib.request.Request(URL, headers={'Range': f'bytes={start}-{start+size-1}'})
    with urllib.request.urlopen(req, timeout=45) as r:
        if r.status != 206:
            raise RuntimeError('Server did not honor Range; refusing full archive')
        data = r.read(size+1)
    if len(data) != size:
        raise RuntimeError('Incomplete or oversized range')
    return data

def main():
    dest = ROOT/'datasets/yawdd_samples'
    dest.mkdir(exist_ok=True)
    offset = 0
    selected = []
    headers = []
    for _ in range(150):
        block = read_range(offset, 512)
        if not block.strip(b'\0'):
            break
        info = tarfile.TarInfo.frombuf(block, 'utf-8', 'replace')
        headers.append(dict(name=info.name, size=info.size))
        if info.isfile() and info.name.lower().endswith('.rar'):
            # YawDD is a tar containing one RAR4 archive. The first compressed
            # member is independent (not solid); reconstruct only that member.
            head = read_range(offset+512, 65536)
            if head[:7] != b'Rar!\x1a\x07\x00':
                raise RuntimeError('Unsupported nested archive format')
            cursor = 7
            _, kind, flags, length = struct.unpack_from('<HBHH', head, cursor)
            if kind != 0x73 or flags & 8:
                raise RuntimeError('Solid or unrecognized RAR main header')
            prefix = head[:cursor+length]
            cursor += length
            _, kind, flags, length = struct.unpack_from('<HBHH', head, cursor)
            if kind != 0x74 or flags & 0x10 or flags & 0x100:
                raise RuntimeError('First member is solid, large-file or not a file')
            packed = struct.unpack_from('<I',head,cursor+7)[0]
            name_size = struct.unpack_from('<H',head,cursor+26)[0]
            member = head[cursor+32:cursor+32+name_size].split(b'\0')[0].decode('utf-8')
            if packed > 200_000_000 or not member.lower().endswith('.avi'):
                raise RuntimeError('First member exceeds sample bound or is not AVI')
            unrar = Path('C:/Program Files/WinRAR/UnRAR.exe')
            if not unrar.is_file():
                raise RuntimeError('UnRAR unavailable; cannot decode sample')
            archive = dest/'first_member.rar'
            archive.write_bytes(prefix + read_range(offset+512+cursor, length+packed) + bytes.fromhex('c43d7b00400700'))
            local = dest/'01-FemaleNoGlasses.avi'
            with local.open('wb') as output:
                subprocess.run([str(unrar),'p','-inul','-p-',str(archive),member],stdout=output,check=True)
            selected.append(dict(member=member,path=str(local),size=local.stat().st_size,
                                 note='First independent RAR member; one participant only'))
            break
        if info.isfile() and info.name.lower().endswith(('.avi','.mp4')) and info.size < 100_000_000:
            local = dest / (f'{len(selected):02d}_' + Path(info.name).name)
            local.write_bytes(read_range(offset+512, info.size))
            selected.append(dict(member=info.name, path=str(local), size=info.size))
            print(info.name, info.size, flush=True)
            if len(selected) == 2:
                break
        offset += 512 + ((info.size + 511)//512)*512
    report = dict(source=URL, selected=selected, inspected_members=headers)
    (ROOT/'docs/yawdd_download.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not selected:
        raise RuntimeError('No bounded-size video found')

if __name__ == '__main__':
    main()
