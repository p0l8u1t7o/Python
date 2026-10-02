import unittest,struct,zlib,tempfile,math
from pathlib import Path
from importlib.util import spec_from_file_location,module_from_spec
spec=spec_from_file_location('native',Path(__file__).resolve().parents[1]/'scripts/native-display.py')
native=module_from_spec(spec);spec.loader.exec_module(native)

def descriptor(width,kind,values,fmt):
    return struct.pack('<4I',width,kind,2,len(values)//(3 if width==12 else 1))+struct.pack('<'+fmt*len(values),*values)
def face(vertices=None):
    return b''.join([descriptor(4,8,[4],'I'),descriptor(12,100,vertices or [0,0,0,1,0,0,0,1,0,1,1,0],'f'),descriptor(12,100,[0,0,1]*4,'f'),descriptor(4,8,[],'I'),descriptor(4,8,[6],'I'),descriptor(1,8,[],'B')])

class NativeDisplayTest(unittest.TestCase):
    def test_strip_winding_and_complete_partition(self):
        faces,rejected=native.face_tables(face())
        self.assertEqual(rejected,0);self.assertEqual(len(faces),1)
        self.assertEqual(list(faces[0][2]),[0,1,2,2,1,3])
        self.assertEqual(len(faces[0][0]),12)

    def test_invalid_face_is_reported_not_rendered(self):
        faces,rejected=native.face_tables(face([float('nan'),0,0,1,0,0,0,1,0,1,1,0]))
        self.assertFalse(faces);self.assertEqual(rejected,1)
        faces,rejected=native.face_tables(face()[:-3]);self.assertFalse(faces);self.assertEqual(rejected,1)

    def test_crc_and_bounds_are_required(self):
        payload=b'confirmed display content';name=b'Contents/DisplayLists'
        name=bytes((b>>4)|((b&15)<<4) for b in name)
        c=zlib.compressobj(wbits=-15);packed=c.compress(payload)+c.flush()
        def block(crc,expected):return b'\x04'+b'\0'*7+native.blocks.MARKER+struct.pack('<5I',0,crc,len(packed),expected,len(name))+name+packed
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.sldprt'
            path.write_bytes(block(zlib.crc32(payload),len(payload)))
            self.assertEqual(list(native.blocks.streams(path)),[('Contents/DisplayLists',payload)])
            path.write_bytes(block(0,len(payload)));self.assertFalse(list(native.blocks.streams(path)))
            path.write_bytes(block(zlib.crc32(payload),len(payload)-1));self.assertFalse(list(native.blocks.streams(path)))

    def test_assembly_placements_suppression_and_missing_references(self):
        from xml.etree import ElementTree as ET
        from types import SimpleNamespace
        root=native.SOURCE/'fixture.SLDASM';part=native.SOURCE/'fixture.SLDPRT'
        transform='1 0 0 0 0 1 0 0 0 0 1 0 0.1 0.2 0.3 1'
        xml=ET.fromstring(f'''<doc xmlns="urn:test"><swFile id="part" swPath="fixture.SLDPRT"/><swModel id="child" swFileRef="part"/><swModel id="root"><swReference swModelRef="child" swTransform="{transform}"/><swReference swModelRef="child" swSuppressed="YES"/><swReference swModelRef="absent"/></swModel><swConfiguration swName="Default" swMostRecentConfiguration="YES" swModelRef="root"/></doc>''')
        cache={root:SimpleNamespace(xml=xml),part:SimpleNamespace(xml=None,file=part,faces=native.face_tables(face())[0],rejected=0)}
        glb,counts,diagnostics=native.build(root,{'fixture.sldprt':[part]},cache)
        self.assertEqual(counts['occurrences'],1);self.assertEqual(counts['suppressed'],1);self.assertEqual(counts['missing'],1)
        self.assertEqual(glb.doc['nodes'][1]['matrix'][12:15],[100,200,300])
        self.assertEqual(glb.doc['accessors'][0]['max'],[1000,1000,0])
        self.assertTrue(diagnostics)

if __name__=='__main__':unittest.main()
