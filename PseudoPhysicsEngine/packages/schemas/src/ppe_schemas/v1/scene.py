from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ppe_schemas.v1.common import ContractModel


class SceneNodeSpec(ContractModel):
    id: UUID
    name: Annotated[str, Field(min_length=1, max_length=200)]
    asset_version_id: UUID
    coordinate_frame_id: UUID
    parent_node_id: UUID | None = None
    visible: bool = True


class SceneAssemblySpec(ContractModel):
    schema_name: Literal["SceneAssemblySpec"] = "SceneAssemblySpec"
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID
    project_id: UUID
    revision_id: UUID
    nodes: list[SceneNodeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scene_tree(self) -> Self:
        nodes_by_id = {node.id: node for node in self.nodes}
        if len(nodes_by_id) != len(self.nodes):
            raise ValueError("Scene node ids must be unique")

        for node in self.nodes:
            if node.parent_node_id == node.id:
                raise ValueError("A scene node cannot be its own parent")
            if node.parent_node_id is not None and node.parent_node_id not in nodes_by_id:
                raise ValueError("Scene node references an unknown parent")

        for node in self.nodes:
            visited_on_path: set[UUID] = set()
            current = node
            while current.parent_node_id is not None:
                if current.id in visited_on_path:
                    raise ValueError("Scene node hierarchy must not contain a cycle")
                visited_on_path.add(current.id)
                current = nodes_by_id[current.parent_node_id]
        return self
