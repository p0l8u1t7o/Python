"""Recover saved display meshes and explicitly referenced placements, not B-rep.

Face strip descriptor grammar: cadmpeg format specification (CC-BY-4.0),
https://github.com/cadmpeg/cadmpeg/blob/main/docs/formats/sldprt.md .
Only CRC-checked modern blocks and validated triangle strips are accepted.
Suppressed/hidden references, unresolved paths and unsupported faces are reported.
No coordinates are guessed for unresolved assembly references.
"""
from pathlib import Path
from collections import defaultdict
import struct, json, math, array, hashlib, re, xml.etree.ElementTree as ET, sys, os
from importlib.util import spec_from_file_location, module_from_spec
spec=spec_from_file_location('native_blocks',Path(__file__).with_name('inspect-native.py'))
blocks=module_from_spec(spec);spec.loader.exec_module(blocks)
BASE=Path(__file__).resolve().parents[2]
SOURCE=Path(os.environ.get('CAD_SOURCE_DIR') or BASE.parent/'TestCode'/'Temp'/'自動爆炸圖與拆圖CAD設計')
OUT=BASE/'public'/'models'/'native'
SIG=struct.pack('<3I',4,8,2)
IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]

def face_tables(data):
    cursor=0; faces=[];rejected=0
    def desc(offset,width,kind):
        if offset+16>len(data):raise ValueError('truncated descriptor')
        w,k,flags,count=struct.unpack_from('<4I',data,offset)
        end=offset+16+w*count
        if (w,k,flags)!=(width,kind,2) or count>10_000_000 or end>len(data):raise ValueError('invalid descriptor')
        return offset+16,count,end
    while True:
        start=data.find(SIG,cursor)
        if start<0:break
        cursor=start+12
        try:
            a,n,end=desc(start,4,8);pos,c,end=desc(end,12,100)
        except ValueError:continue
        try:
            normal,nc,end=desc(end,12,100);b,nb,end=desc(end,4,8);sc,ns,end=desc(end,4,8);d,nd,end=desc(end,1,8)
            lengths=struct.unpack_from(f'<{n}I',data,a)
            if not n or any(k<3 for k in lengths) or sum(lengths)!=c or nc not in [0,c] or ns!=n:raise ValueError('strip partition')
            sections=struct.unpack_from(f'<{ns}I',data,sc)
            if any(k!=2*l-2 for k,l in zip(sections,lengths)) or not ((nb==nd==0) or (nb==nd==sum(sections))):raise ValueError('strip annotations')
            vertices=array.array('f');vertices.frombytes(data[pos:pos+c*12])
            normals=array.array('f');normals.frombytes(data[normal:normal+nc*12])
            if any(not math.isfinite(v) or abs(v)>10000 for v in vertices):raise ValueError('nonfinite positions')
            if normals and any(not math.isfinite(v) for v in normals):raise ValueError('nonfinite normals')
            indices=array.array('I');v=0
            for length in lengths:
                for i in range(2,length):indices.extend([v+i-2,v+i-1,v+i] if i%2==0 else [v+i-1,v+i-2,v+i])
                v+=length
            faces.append((vertices,normals,indices));cursor=end
        except (ValueError,struct.error,OverflowError):rejected+=1
    return faces,rejected

class Model:
    def __init__(self,file):
        self.file=file;self.xml=None;self.faces=[];self.rejected=0;self.preview=None
        for name,data in blocks.streams(file):
            if name=='swXmlContents/COMPINSTANCETREE':
                try:self.xml=ET.fromstring(data)
                except ET.ParseError:pass
            if name=='Contents/DisplayLists' and file.suffix.lower()=='.sldprt':
                self.faces,self.rejected=face_tables(data)
            if name=='PreviewPNG':self.preview=data

class GLB:
    def __init__(self):
        self.doc={'asset':{'version':'2.0','generator':'Assembly Studio: validated saved display geometry'},'scene':0,'scenes':[{'nodes':[]}],'nodes':[],'meshes':[],'bufferViews':[],'accessors':[],'materials':[{'name':'Unspecified source material','pbrMetallicRoughness':{'baseColorFactor':[.55,.61,.65,1],'metallicFactor':.65,'roughnessFactor':.3},'extras':{'materialSource':'unspecified'}}]};self.binary=bytearray();self.meshes={}
    def accessor(self,values,kind,type_,target,bounds=False):
        self.binary.extend(b'\0'*((-len(self.binary))%4));offset=len(self.binary);raw=values.tobytes();self.binary.extend(raw)
        vi=len(self.doc['bufferViews']);self.doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(raw),'target':target})
        count=len(values)//(3 if type_=='VEC3' else 1);a={'bufferView':vi,'componentType':kind,'count':count,'type':type_}
        if bounds:a.update(min=[min(values[i::3]) for i in range(3)],max=[max(values[i::3]) for i in range(3)])
        ai=len(self.doc['accessors']);self.doc['accessors'].append(a);return ai
    def mesh(self,model):
        key=str(model.file)
        if key in self.meshes:return self.meshes[key]
        positions=array.array('f');normals=array.array('f');indices=array.array('I');has_normals=True
        for p,n,idx in model.faces:
            offset=len(positions)//3;positions.extend(v*1000 for v in p);normals.extend(n);indices.extend(i+offset for i in idx)
            if len(n)!=len(p):has_normals=False
        if not positions:return None
        attributes={'POSITION':self.accessor(positions,5126,'VEC3',34962,True)}
        if has_normals:attributes['NORMAL']=self.accessor(normals,5126,'VEC3',34962)
        mesh={'name':model.file.stem,'primitives':[{'attributes':attributes,'indices':self.accessor(indices,5125,'SCALAR',34963),'material':0}]}
        index=len(self.doc['meshes']);self.doc['meshes'].append(mesh);self.meshes[key]=index;return index
    def write(self,file):
        self.binary.extend(b'\0'*((-len(self.binary))%4));self.doc['buffers']=[{'byteLength':len(self.binary)}]
        header=json.dumps(self.doc,ensure_ascii=False,separators=(',',':')).encode('utf8');header+=b' '*((-len(header))%4)
        size=12+8+len(header)+8+len(self.binary)
        file.write_bytes(struct.pack('<3I',0x46546c67,2,size)+struct.pack('<2I',len(header),0x4e4f534a)+header+struct.pack('<2I',len(self.binary),0x004e4942)+self.binary)

def build(file,lookup,cache):
    glb=GLB();diagnostics=[];counts={'occurrences':0,'suppressed':0,'hidden':0,'missing':0,'unsupported':0,'rejectedFaces':0};active=set()
    def get(p):
        if p not in cache:cache[p]=Model(p)
        return cache[p]
    def resolve(stored,parent):
        name=stored.replace('\\','/').split('/')[-1].casefold();candidates=lookup.get(name,[])
        same=[p for p in candidates if p.parent==parent.parent]
        if len(same)==1:return same[0]
        if len(candidates)==1:return candidates[0]
        if len(candidates)>1:
            # Identical copies are interchangeable, but different revisions are not.
            hashes={hashlib.sha256(p.read_bytes()).hexdigest() for p in candidates}
            if len(hashes)==1:return candidates[0]
        return None
    def visit(p,config=None,label=None,matrix=None,depth=0):
        if depth>40 or (p,config) in active:counts['unsupported']+=1;diagnostics.append('recursive reference: '+p.name);return None
        active.add((p,config));model=get(p)
        node={'name':label or p.stem,'extras':{'sourcePath':p.relative_to(SOURCE).as_posix(),'geometrySource':'saved-display','savedDisplay':True}}
        if matrix:node['matrix']=matrix
        ni=len(glb.doc['nodes']);glb.doc['nodes'].append(node)
        if p.suffix.lower()=='.sldprt':
            mi=glb.mesh(model)
            if mi is None:counts['unsupported']+=1;diagnostics.append('no supported saved mesh: '+p.name)
            else:node['mesh']=mi;counts['occurrences']+=1;counts['rejectedFaces']+=model.rejected
        elif model.xml is not None:
            elements=list(model.xml.iter());files={e.get('id'):e for e in elements if e.tag.endswith('}swFile')};models={e.get('id'):e for e in elements if e.tag.endswith('}swModel')};configs=[e for e in elements if e.tag.endswith('}swConfiguration')]
            chosen=next((c for c in configs if config and c.get('swName')==config),None)
            if chosen is None:chosen=next((c for c in configs if c.get('swMostRecentConfiguration')=='YES'),configs[0] if configs else None)
            top=models.get(chosen.get('swModelRef')) if chosen is not None else None
            children=[]
            if top is not None:
                for ref in top:
                    if not ref.tag.endswith('}swReference'):continue
                    if ref.get('swSuppressed')=='YES':counts['suppressed']+=1;continue
                    if ref.get('swHidden')=='YES':counts['hidden']+=1;continue
                    child=models.get(ref.get('swModelRef'));sf=files.get(child.get('swFileRef')) if child is not None else None
                    stored=sf.get('swPath','') if sf is not None else '';target=resolve(stored,p)
                    if not target:counts['missing']+=1;diagnostics.append('unresolved: '+stored);continue
                    try:
                        transform=[float(v) for v in ref.get('swTransform','').split()]
                        if len(transform)!=16 or any(not math.isfinite(v) for v in transform):raise ValueError()
                        # XML uses a column-major affine matrix. Source units are metres.
                        if any(abs(transform[i])>1e-6 for i in [3,7,11]) or abs(transform[15]-1)>1e-6:raise ValueError()
                        for i in [12,13,14]:transform[i]*=1000
                    except ValueError:counts['unsupported']+=1;diagnostics.append('invalid transform: '+stored);continue
                    ci=visit(target,ref.get('swConfigurationName'),ref.get('swName','')+' #'+ref.get('swReferenceNumber',''),transform,depth+1)
                    if ci is not None:children.append(ci)
            if children:node['children']=children
        else:counts['unsupported']+=1;diagnostics.append('no supported assembly tree: '+p.name)
        active.remove((p,config));return ni
    root=visit(file);glb.doc['scenes'][0]['nodes']=[root]
    return glb,counts,sorted(set(diagnostics))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    native=[p for p in SOURCE.rglob('*') if p.is_file() and p.suffix.lower() in ['.sldasm','.sldprt'] and not p.name.startswith('~$')]
    lookup=defaultdict(list)
    for p in native:lookup[p.name.casefold()].append(p)
    cache={};manifest={};names=sys.argv[1:]
    selected=sorted(native) if names==['--all'] else [lookup[name.casefold()][0] for name in (names or [f'202401-{c}A00.SLDASM' for c in 'ABCDEFGHIJ']) if lookup[name.casefold()]]
    for ordinal,file in enumerate(selected):
        relative=file.relative_to(SOURCE).as_posix();key=hashlib.sha1(relative.encode('utf8')).hexdigest()[:16]
        if ordinal%25==0:print('Reading',ordinal+1,'/',len(selected),file.name,flush=True)
        try:glb,counts,diagnostics=build(file,lookup,cache)
        except Exception as error:
            manifest[key]={'id':key,'source':relative,'parts':0,'scope':'原生顯示格式未支援','diagnostics':[str(error)]};continue
        item={'id':key,'source':relative,'scope':'原生組合件顯示快取' if file.suffix.lower()=='.sldasm' else '原生零件顯示快取','upAxis':'y','geometrySource':'saved-display','parts':counts['occurrences'],'counts':counts,'diagnostics':diagnostics}
        if counts['occurrences']:
            glb.write(OUT/(key+'.glb'));item['url']='models/native/'+key+'.glb'
        else:item['scope']='來源配置無可顯示零件'
        model=cache.get(file)
        if model and model.preview:
            (OUT/(key+'.png')).write_bytes(model.preview);item['preview']='models/native/'+key+'.png'
        manifest[key]=item
        if ordinal%25==0:print(json.dumps({'source':relative,**counts},ensure_ascii=False),flush=True)
    (BASE/'public/data/native-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
