"""OpenCascade desktop fallback for large STEP files; source is read-only.
Requires cadquery-ocp 8.0.1.0.0 (see requirements.txt). Units remain millimetres.
"""
from pathlib import Path
import sys,json,struct
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString,TCollection_AsciiString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import Sequence_TDF_Label,IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.RWGltf import RWGltf_CafWriter
from OCP.RWMesh import RWMesh_CoordinateSystem,RWMesh_NameFormat
from OCP.Message import Message_ProgressRange

source,output=sys.argv[1:3]
print('Reading STEP with OpenCascade desktop',Path(source).name,flush=True)
doc=TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
reader=STEPCAFControl_Reader();reader.SetColorMode(True);reader.SetNameMode(True)
if reader.ReadFile(source)!=IFSelect_RetDone or not reader.Transfer(doc):raise RuntimeError('STEP transfer failed')
tool=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main());roots=Sequence_TDF_Label();tool.GetFreeShapes(roots)
print('Tessellating',roots.Length(),'root assemblies at 0.08 mm',flush=True)
for i in range(1,roots.Length()+1):
    mesh=BRepMesh_IncrementalMesh(tool.GetShape_s(roots.Value(i)),.08,False,.22,True)
    if not mesh.IsDone():raise RuntimeError('Tessellation failed')
writer=RWGltf_CafWriter(TCollection_AsciiString(output),True);writer.SetMergeFaces(True)
writer.SetNodeNameFormat(RWMesh_NameFormat.RWMesh_NameFormat_ProductOrInstance)
writer.SetMeshNameFormat(RWMesh_NameFormat.RWMesh_NameFormat_Product)
converter=writer.ChangeCoordinateSystemConverter()
converter.SetInputCoordinateSystem(RWMesh_CoordinateSystem.RWMesh_CoordinateSystem_Yup)
converter.SetOutputCoordinateSystem(RWMesh_CoordinateSystem.RWMesh_CoordinateSystem_Yup)
converter.SetInputLengthUnit(.001);converter.SetOutputLengthUnit(.001)
print('Writing GLB',flush=True)
if not writer.Perform(doc,IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString(),Message_ProgressRange()):raise RuntimeError('GLB export failed')
data=Path(output).read_bytes();size=struct.unpack_from('<I',data,12)[0];gltf=json.loads(data[20:20+size]);nodes=gltf.get('nodes',[])
parts=sum('mesh' in n for n in nodes);triangles=sum(sum(gltf['accessors'][p['indices']]['count']//3 for p in gltf['meshes'][n['mesh']]['primitives']) for n in nodes if 'mesh' in n)
if not parts or not triangles:raise RuntimeError('STEP export produced no geometry')
meta={'parts':parts,'triangles':triangles,'bytes':len(data),'quality':{'linearUnit':'millimeter','linearDeflectionType':'absolute_value','linearDeflection':.08,'angularDeflection':.22},'upAxis':'y','converter':'OpenCascade 8.0.1 desktop'}
Path(output+'.meta.json').write_text(json.dumps(meta),encoding='utf8');print(json.dumps(meta),flush=True)
