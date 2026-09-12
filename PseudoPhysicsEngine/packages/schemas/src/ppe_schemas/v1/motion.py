from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ppe_schemas.v1.common import ContractModel


class MotionKeyframe(ContractModel):
    time_seconds: float = Field(ge=0)
    position: float


class MotionTrackSpec(ContractModel):
    id: UUID
    scene_node_id: UUID
    joint_name: Annotated[str, Field(min_length=1, max_length=200)]
    position_unit: Literal["mm", "degree", "radian"]
    keyframes: Annotated[list[MotionKeyframe], Field(min_length=2)]

    @model_validator(mode="after")
    def keyframe_times_must_increase(self) -> Self:
        times = [keyframe.time_seconds for keyframe in self.keyframes]
        if any(current <= previous for previous, current in zip(times, times[1:], strict=False)):
            raise ValueError("Motion keyframe times must be strictly increasing")
        return self


class MotionSpec(ContractModel):
    schema_name: Literal["MotionSpec"] = "MotionSpec"
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID
    project_id: UUID
    revision_id: UUID
    tracks: Annotated[list[MotionTrackSpec], Field(min_length=1)]

    @model_validator(mode="after")
    def track_ids_must_be_unique(self) -> Self:
        track_ids = [track.id for track in self.tracks]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("Motion track ids must be unique")
        return self
