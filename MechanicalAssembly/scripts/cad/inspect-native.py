"""Inspect bounded, CRC-checked SolidWorks block streams (read only).
Container layout: cadmpeg docs/formats/sldprt.md (CC-BY-4.0).
"""
from pathlib import Path
import struct, zlib, json, os
MARKER = bytes.fromhex('140006000800')
def streams(file):
    data = Path(file).read_bytes()
    if data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        try:
            import olefile
            with olefile.OleFileIO(str(file)) as ole:
                for entry in ole.listdir():
                    name='/'.join(entry);payload=ole.openstream(entry).read()
                    if name.endswith('__ZLB') and payload.startswith(bytes.fromhex('231dd571da8148a2a85898b21b89ef99')) and len(payload)>=24:
                        size,packed=struct.unpack_from('<2I',payload,16)
                        if size>256*1024*1024 or 24+packed>len(payload):continue
                        try:
                            decoder=zlib.decompressobj();decoded=decoder.decompress(payload[24:24+packed],size+1)
                            if len(decoded)!=size or not decoder.eof:continue
                            payload=decoded;name=name[:-5]
                        except zlib.error:continue
                    yield name,payload
        except (ImportError,OSError):pass
        return
    offset = 8
    while True:
        offset = data.find(MARKER, offset)
        if offset < 0: return
        start = offset
        offset += 6
        if start + 26 > len(data): continue
        kind, crc, packed, size, n = struct.unpack_from('<5I', data, start+6)
        end = start + 26 + n + packed
        if not (0 < packed <= len(data) and 0 < size < 256*1024*1024 and n < 4096 and end <= len(data)): continue
        try:
            decoder=zlib.decompressobj(-15)
            output=decoder.decompress(data[start+26+n:end], size+1)
            if len(output)!=size or not decoder.eof or zlib.crc32(output)!=crc: continue
        except zlib.error: continue
        name=bytes((b>>4)|((b&15)<<4) for b in data[start+26:start+26+n]).decode('utf-8',errors='replace')
        yield name, output
        offset=end
if __name__ == '__main__':
    base=Path(__file__).resolve().parents[2]
    source=Path(os.environ.get('CAD_SOURCE_DIR') or base/'cad-source')
    output=base/'tmp'/'native-research'/'streams'
    output.mkdir(parents=True,exist_ok=True)
    for name in ['202401-FA00.SLDASM','202401-GA00.SLDASM','202401-JA00.SLDASM']:
        file=next(source.rglob(name))
        print(name)
        for i,(stream,content) in enumerate(streams(file)):
            print(' ',stream,len(content))
            if any(key in stream.lower() for key in ['display','xml','config','header']):
                (output/(name+f'-{i}.bin')).write_bytes(content)
