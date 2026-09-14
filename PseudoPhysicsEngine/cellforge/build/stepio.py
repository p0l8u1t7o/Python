"""STEP assembly export and strict XCAF round-trip validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import cadquery as cq
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool


class StepValidationError(RuntimeError):
    pass


@dataclass(slots=True)
class StepComponent:
    instance_name: str
    part_name: str
    is_assembly: bool
    child_count: int
    children: list[StepComponent]


@dataclass(slots=True)
class StepInspection:
    free_shape_count: int
    root_name: str
    components: list[StepComponent]

    def _flatten(self) -> list[StepComponent]:
        result: list[StepComponent] = []

        def visit(component: StepComponent) -> None:
            result.append(component)
            for child in component.children:
                visit(child)

        for component in self.components:
            visit(component)
        return result

    def as_dict(self) -> dict:
        flattened = self._flatten()
        return {
            "free_shape_count": self.free_shape_count,
            "root_name": self.root_name,
            "top_level_part_count": len(self.components),
            "total_component_count": len(flattened),
            "assembly_node_count": 1 + sum(item.is_assembly for item in flattened),
            "leaf_part_count": sum(not item.is_assembly for item in flattened),
            "all_names_preserved": all(
                bool(item.instance_name) and item.instance_name == item.part_name
                for item in flattened
            ),
            "components": [asdict(component) for component in self.components],
        }


def _label_name(label: TDF_Label) -> str:
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def _read_document(path: Path) -> tuple[TDocStd_Document, XCAFDoc_ShapeTool]:
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise StepValidationError(f"OCP 無法讀取 STEP：{path}")
    document = TDocStd_Document(TCollection_ExtendedString("CellForge STEP validation"))
    if not reader.Transfer(document):
        raise StepValidationError(f"OCP 無法將 STEP 轉入 XCAF：{path}")
    return document, XCAFDoc_DocumentTool.ShapeTool_s(document.Main())


def inspect_step(path: Path) -> StepInspection:
    _document, shape_tool = _read_document(path)
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    if free_shapes.Length() != 1:
        return StepInspection(free_shapes.Length(), "", [])
    root = free_shapes.Value(1)
    return StepInspection(
        free_shapes.Length(), _label_name(root), _inspect_children(shape_tool, root)
    )


def _inspect_children(shape_tool: XCAFDoc_ShapeTool, parent: TDF_Label) -> list[StepComponent]:
    labels = TDF_LabelSequence()
    shape_tool.GetComponents_s(parent, labels, False)
    components: list[StepComponent] = []
    for index in range(1, labels.Length() + 1):
        instance = labels.Value(index)
        referred = TDF_Label()
        shape_tool.GetReferredShape_s(instance, referred)
        children = _inspect_children(shape_tool, referred)
        components.append(
            StepComponent(
                instance_name=_label_name(instance),
                part_name=_label_name(referred),
                is_assembly=shape_tool.IsAssembly_s(referred),
                child_count=len(children),
                children=children,
            )
        )
    return components


def _rewrite_instance_names(path: Path) -> None:
    document, shape_tool = _read_document(path)
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    if free_shapes.Length() != 1:
        return
    root = free_shapes.Value(1)
    _repair_children(shape_tool, root)
    rewritten = path.with_suffix(".xcaf.step")
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    if not writer.Transfer(document, STEPControl_AsIs):
        raise StepValidationError("OCP XCAF 無法準備 STEP 裝配文件")
    if writer.Write(str(rewritten)) != IFSelect_RetDone:
        raise StepValidationError("OCP XCAF 無法寫出 STEP 裝配文件")
    rewritten.replace(path)


def _repair_children(shape_tool: XCAFDoc_ShapeTool, parent: TDF_Label) -> None:
    components = TDF_LabelSequence()
    shape_tool.GetComponents_s(parent, components, False)
    for index in range(1, components.Length() + 1):
        instance = components.Value(index)
        referred = TDF_Label()
        shape_tool.GetReferredShape_s(instance, referred)
        part_name = _label_name(referred)
        if part_name:
            TDataStd_Name.Set_s(instance, TCollection_ExtendedString(part_name))
        if shape_tool.IsAssembly_s(referred):
            _repair_children(shape_tool, referred)


def export_and_validate_step(
    assembly: cq.Assembly, path: Path, expected_names: list[str]
) -> tuple[StepInspection, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    assembly.save(str(path), exportType="STEP", mode="default")
    first = inspect_step(path)
    used_xcaf_fallback = [item.instance_name for item in first.components] != expected_names
    if used_xcaf_fallback:
        _rewrite_instance_names(path)
    verified = inspect_step(path)
    actual_parts = [item.part_name for item in verified.components]
    actual_instances = [item.instance_name for item in verified.components]
    all_components = verified._flatten()
    errors: list[str] = []
    if verified.free_shape_count != 1:
        errors.append(f"free shape 應為 1，實際 {verified.free_shape_count}")
    if len(verified.components) != len(expected_names):
        errors.append(f"頂層零件數應為 {len(expected_names)}，實際 {len(verified.components)}")
    if actual_parts != expected_names:
        errors.append(f"part 名稱應為 {expected_names}，實際 {actual_parts}")
    if actual_instances != expected_names:
        errors.append(f"component 名稱應為 {expected_names}，實際 {actual_instances}")
    unnamed_or_mismatched = [
        item.instance_name
        for item in all_components
        if not item.instance_name or item.instance_name != item.part_name
    ]
    if unnamed_or_mismatched:
        errors.append(f"裝配樹內仍有名稱未保留的 component：{unnamed_or_mismatched}")
    if errors:
        raise StepValidationError("STEP OCP 重讀驗證失敗：" + "；".join(errors))
    return verified, used_xcaf_fallback
