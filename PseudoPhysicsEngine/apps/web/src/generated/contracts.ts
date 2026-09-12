// Generated from versioned Pydantic JSON Schema. Do not edit manually.

export namespace ProjectContract {
  export type Id = string;
  export type Name = string;
  export type CustomerName = string | null;
  export type CreatedAt = string;
  export type Id1 = string;
  export type ProjectId = string;
  export type Sequence = number;
  export type RevisionStatus = "DRAFT" | "APPROVED" | "RELEASED";
  export type ParentRevisionId = string | null;
  export type CreatedAt1 = string;
  
  export interface ProjectRead {
    id: Id;
    name: Name;
    customer_name: CustomerName;
    created_at: CreatedAt;
    current_revision: ProjectRevision;
  }
  export interface ProjectRevision {
    id: Id1;
    project_id: ProjectId;
    sequence: Sequence;
    status: RevisionStatus;
    parent_revision_id?: ParentRevisionId;
    created_at: CreatedAt1;
  }
}

export namespace FrameTreeContract {
  export type RevisionId = string;
  export type Id = string;
  export type RevisionId1 = string;
  export type Name = string;
  export type ParentFrameId = string | null;
  export type LengthUnit = "mm";
  export type AxisSystem = "RIGHT_HANDED_Z_UP";
  export type Frames = CoordinateFrame[];
  export type Id1 = string;
  export type RevisionId2 = string;
  export type ParentFrameId1 = string;
  export type ChildFrameId = string;
  /**
   * @minItems 4
   * @maxItems 4
   */
  export type Matrix4 = [any, any, any, any];
  export type TrustStatus = "INFERRED" | "DRAWING_CONFIRMED" | "CAD_CONFIRMED" | "SURVEY_CALIBRATED" | "RELEASED";
  export type Source = string;
  export type Transforms = FrameTransform[];
  
  export interface FrameTreeRead {
    revision_id: RevisionId;
    frames: Frames;
    transforms: Transforms;
  }
  export interface CoordinateFrame {
    id: Id;
    revision_id: RevisionId1;
    name: Name;
    parent_frame_id?: ParentFrameId;
    length_unit?: LengthUnit;
    axis_system?: AxisSystem;
  }
  export interface FrameTransform {
    id: Id1;
    revision_id: RevisionId2;
    parent_frame_id: ParentFrameId1;
    child_frame_id: ChildFrameId;
    matrix: Matrix4;
    trust_status: TrustStatus;
    source: Source;
  }
}

export namespace ArtifactContract {
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type OriginalFilename = string;
  export type ArtifactFormat = "STEP" | "GLB" | "PDF";
  export type MimeType = string;
  export type SizeBytes = number;
  export type Sha256 = string;
  export type StorageUri = string;
  export type Source = string;
  export type CreatedAt = string;
  
  export interface ArtifactRead {
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    original_filename: OriginalFilename;
    format: ArtifactFormat;
    mime_type: MimeType;
    size_bytes: SizeBytes;
    sha256: Sha256;
    storage_uri: StorageUri;
    source: Source;
    created_at: CreatedAt;
  }
}

export namespace AuditEventContract {
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string | null;
  export type ActorId = string | null;
  export type EventType = string;
  export type EntityType = string;
  export type EntityId = string | null;
  export type CreatedAt = string;
  
  export interface AuditEventRead {
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    actor_id: ActorId;
    event_type: EventType;
    entity_type: EntityType;
    entity_id: EntityId;
    details: Details;
    created_at: CreatedAt;
  }
  export interface Details {
    [k: string]: any;
  }
}

export namespace ChangeSetContract {
  export type SchemaName = "ChangeSet";
  export type SchemaVersion = "1.0.0";
  export type Id = string;
  export type ProjectId = string;
  export type BaseRevisionId = string;
  export type Reason = string;
  export type UserInstruction = string;
  export type InterpretedIntent = string;
  /**
   * @minItems 1
   */
  export type Operations = [ChangeOperation, ...ChangeOperation[]];
  export type OperationType = "ADD" | "UPDATE" | "REMOVE";
  export type ObjectType = string;
  export type ObjectId = string;
  export type Before = {
    [k: string]: any;
  } | null;
  export type After = {
    [k: string]: any;
  } | null;
  export type RequiresTessellation = boolean;
  export type RequiresSimulation = boolean;
  export type RequiresRender = boolean;
  export type ApprovedBy = string | null;
  
  export interface ChangeSet {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    id: Id;
    project_id: ProjectId;
    base_revision_id: BaseRevisionId;
    reason: Reason;
    user_instruction: UserInstruction;
    interpreted_intent: InterpretedIntent;
    operations: Operations;
    requires_tessellation?: RequiresTessellation;
    requires_simulation?: RequiresSimulation;
    requires_render?: RequiresRender;
    approved_by?: ApprovedBy;
  }
  export interface ChangeOperation {
    operation: OperationType;
    object_type: ObjectType;
    object_id: ObjectId;
    before?: Before;
    after?: After;
  }
}

export namespace ChangeSetPreviewContract {
  export type ChangeSetId = string;
  export type BaseRevisionId = string;
  export type Valid = boolean;
  export type AffectedObjectIds = string[];
  export type Code = string;
  export type Message = string;
  export type OperationIndex = number | null;
  export type Issues = ChangeSetIssue[];
  
  export interface ChangeSetPreview {
    change_set_id: ChangeSetId;
    base_revision_id: BaseRevisionId;
    valid: Valid;
    affected_object_ids: AffectedObjectIds;
    issues: Issues;
  }
  export interface ChangeSetIssue {
    code: Code;
    message: Message;
    operation_index?: OperationIndex;
  }
}

export namespace ChangeSetApplyResultContract {
  export type ChangeSetId = string;
  export type Id = string;
  export type ProjectId = string;
  export type Sequence = number;
  export type RevisionStatus = "DRAFT" | "APPROVED" | "RELEASED";
  export type ParentRevisionId = string | null;
  export type CreatedAt = string;
  export type RevisionId = string;
  export type Id1 = string;
  export type RevisionId1 = string;
  export type Name = string;
  export type ParentFrameId = string | null;
  export type LengthUnit = "mm";
  export type AxisSystem = "RIGHT_HANDED_Z_UP";
  export type Frames = CoordinateFrame[];
  export type Id2 = string;
  export type RevisionId2 = string;
  export type ParentFrameId1 = string;
  export type ChildFrameId = string;
  /**
   * @minItems 4
   * @maxItems 4
   */
  export type Matrix4 = [any, any, any, any];
  export type TrustStatus = "INFERRED" | "DRAWING_CONFIRMED" | "CAD_CONFIRMED" | "SURVEY_CALIBRATED" | "RELEASED";
  export type Source = string;
  export type Transforms = FrameTransform[];
  
  export interface ChangeSetApplyResult {
    change_set_id: ChangeSetId;
    revision: ProjectRevision;
    frame_tree: FrameTreeRead;
  }
  export interface ProjectRevision {
    id: Id;
    project_id: ProjectId;
    sequence: Sequence;
    status: RevisionStatus;
    parent_revision_id?: ParentRevisionId;
    created_at: CreatedAt;
  }
  export interface FrameTreeRead {
    revision_id: RevisionId;
    frames: Frames;
    transforms: Transforms;
  }
  export interface CoordinateFrame {
    id: Id1;
    revision_id: RevisionId1;
    name: Name;
    parent_frame_id?: ParentFrameId;
    length_unit?: LengthUnit;
    axis_system?: AxisSystem;
  }
  export interface FrameTransform {
    id: Id2;
    revision_id: RevisionId2;
    parent_frame_id: ParentFrameId1;
    child_frame_id: ChildFrameId;
    matrix: Matrix4;
    trust_status: TrustStatus;
    source: Source;
  }
}

export namespace JobContract {
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type JobKind = "TESSELLATE" | "SIMULATE" | "RENDER" | "EXPORT";
  export type JobStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  export type IdempotencyKey = string;
  export type InputArtifactIds = string[];
  export type ResultArtifactIds = string[];
  export type ToolName = string;
  export type ToolVersion = string;
  export type WorkerId = string | null;
  export type AttemptCount = number;
  export type MaxAttempts = number;
  export type Error = string | null;
  export type CreatedAt = string;
  export type StartedAt = string | null;
  export type HeartbeatAt = string | null;
  export type LeaseExpiresAt = string | null;
  export type FinishedAt = string | null;
  
  export interface JobRead {
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    kind: JobKind;
    status: JobStatus;
    idempotency_key: IdempotencyKey;
    input_artifact_ids: InputArtifactIds;
    result_artifact_ids: ResultArtifactIds;
    parameters: Parameters;
    tool_name: ToolName;
    tool_version: ToolVersion;
    worker_id: WorkerId;
    attempt_count: AttemptCount;
    max_attempts: MaxAttempts;
    error: Error;
    created_at: CreatedAt;
    started_at: StartedAt;
    heartbeat_at: HeartbeatAt;
    lease_expires_at: LeaseExpiresAt;
    finished_at: FinishedAt;
  }
  export interface Parameters {
    [k: string]: any;
  }
}

export namespace JobSubmitContract {
  export type ProjectId = string;
  export type RevisionId = string;
  export type JobKind = "TESSELLATE" | "SIMULATE" | "RENDER" | "EXPORT";
  export type IdempotencyKey = string;
  export type InputArtifactIds = string[];
  export type ToolName = string;
  export type ToolVersion = string;
  export type MaxAttempts = number;
  
  export interface JobSubmit {
    project_id: ProjectId;
    revision_id: RevisionId;
    kind: JobKind;
    idempotency_key: IdempotencyKey;
    input_artifact_ids?: InputArtifactIds;
    parameters?: Parameters;
    tool_name: ToolName;
    tool_version: ToolVersion;
    max_attempts?: MaxAttempts;
  }
  export interface Parameters {
    [k: string]: any;
  }
}

export namespace ProcessSpecContract {
  export type SchemaName = "ProcessSpec";
  export type SchemaVersion = "1.0.0";
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type TargetCycleTimeSeconds = number;
  /**
   * @minItems 1
   */
  export type Steps = [ProcessStep, ...ProcessStep[]];
  export type Id1 = string;
  export type Name = string;
  export type PredecessorIds = string[];
  export type InputConditions = string[];
  export type OutputConditions = string[];
  export type EquipmentRequirements = string[];
  export type EstimatedDurationSeconds = number;
  export type Assumptions = string[];
  export type UnresolvedQuestions = string[];
  
  export interface ProcessSpec {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    target_cycle_time_seconds: TargetCycleTimeSeconds;
    steps: Steps;
    assumptions?: Assumptions;
    unresolved_questions?: UnresolvedQuestions;
  }
  export interface ProcessStep {
    id: Id1;
    name: Name;
    predecessor_ids?: PredecessorIds;
    input_conditions?: InputConditions;
    output_conditions?: OutputConditions;
    equipment_requirements?: EquipmentRequirements;
    estimated_duration_seconds: EstimatedDurationSeconds;
  }
}

export namespace ProcessAnalysisContract {
  export type SchemaName = "ProcessAnalysis";
  export type SchemaVersion = "1.0.0";
  export type ProcessSpecId = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type CriticalPathStepIds = string[];
  export type CycleTimeSeconds = number;
  export type TargetCycleTimeSeconds = number;
  export type WithinTarget = boolean;
  
  export interface ProcessAnalysis {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    process_spec_id: ProcessSpecId;
    project_id: ProjectId;
    revision_id: RevisionId;
    critical_path_step_ids: CriticalPathStepIds;
    cycle_time_seconds: CycleTimeSeconds;
    target_cycle_time_seconds: TargetCycleTimeSeconds;
    within_target: WithinTarget;
  }
}

export namespace MotionSpecContract {
  export type SchemaName = "MotionSpec";
  export type SchemaVersion = "1.0.0";
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  /**
   * @minItems 1
   */
  export type Tracks = [MotionTrackSpec, ...MotionTrackSpec[]];
  export type Id1 = string;
  export type SceneNodeId = string;
  export type JointName = string;
  export type PositionUnit = "mm" | "degree" | "radian";
  /**
   * @minItems 2
   */
  export type Keyframes = [MotionKeyframe, MotionKeyframe, ...MotionKeyframe[]];
  export type TimeSeconds = number;
  export type Position = number;
  
  export interface MotionSpec {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    tracks: Tracks;
  }
  export interface MotionTrackSpec {
    id: Id1;
    scene_node_id: SceneNodeId;
    joint_name: JointName;
    position_unit: PositionUnit;
    keyframes: Keyframes;
  }
  export interface MotionKeyframe {
    time_seconds: TimeSeconds;
    position: Position;
  }
}

export namespace SceneAssemblyContract {
  export type SchemaName = "SceneAssemblySpec";
  export type SchemaVersion = "1.0.0";
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type Id1 = string;
  export type Name = string;
  export type AssetVersionId = string;
  export type CoordinateFrameId = string;
  export type ParentNodeId = string | null;
  export type Visible = boolean;
  export type Nodes = SceneNodeSpec[];
  
  export interface SceneAssemblySpec {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    nodes?: Nodes;
  }
  export interface SceneNodeSpec {
    id: Id1;
    name: Name;
    asset_version_id: AssetVersionId;
    coordinate_frame_id: CoordinateFrameId;
    parent_node_id?: ParentNodeId;
    visible?: Visible;
  }
}

export namespace ValidationReportContract {
  export type SchemaName = "ValidationReport";
  export type SchemaVersion = "1.0.0";
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type ValidationStatus = "PASSED" | "FAILED";
  export type ValidatorVersion = string;
  export type Code = string;
  export type ValidationSeverity = "INFO" | "WARNING" | "ERROR";
  export type Message = string;
  export type ObjectIds = string[];
  export type BlocksRelease = boolean;
  export type Issues = ValidationIssue[];
  
  export interface ValidationReport {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    status: ValidationStatus;
    validator_version: ValidatorVersion;
    issues?: Issues;
  }
  export interface ValidationIssue {
    code: Code;
    severity: ValidationSeverity;
    message: Message;
    object_ids?: ObjectIds;
    blocks_release?: BlocksRelease;
  }
}

export namespace ReleaseManifestContract {
  export type SchemaName = "ReleaseManifest";
  export type SchemaVersion = "1.0.0";
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type ValidationReportId = string;
  export type ApprovedBy = string;
  export type GeneratedAt = string;
  /**
   * @minItems 1
   */
  export type Artifacts = [ReleaseArtifact, ...ReleaseArtifact[]];
  export type Id1 = string;
  export type ArtifactKind =
    "STEP" | "PARASOLID" | "SLDPRT" | "SLDASM" | "BOM" | "COORDINATE_REPORT" | "VALIDATION_REPORT" | "OTHER";
  export type Uri = string;
  export type Sha256 = string;
  export type SizeBytes = number;
  export type MimeType = string;
  
  export interface ReleaseManifest {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    validation_report_id: ValidationReportId;
    approved_by: ApprovedBy;
    generated_at: GeneratedAt;
    artifacts: Artifacts;
  }
  export interface ReleaseArtifact {
    id: Id1;
    kind: ArtifactKind;
    uri: Uri;
    sha256: Sha256;
    size_bytes: SizeBytes;
    mime_type: MimeType;
  }
}

export namespace ReleaseRequestContract {
  export type ApprovedBy = string;
  
  export interface ReleaseRequest {
    approved_by: ApprovedBy;
  }
}

export namespace RevisionDiffContract {
  export type SchemaName = string;
  export type SchemaVersion = string;
  export type ProjectId = string;
  export type FromRevisionId = string;
  export type ToRevisionId = string;
  export type ObjectType = string;
  export type ObjectKey = string;
  export type RevisionChangeKind = "ADDED" | "REMOVED" | "MODIFIED";
  export type Before = {
    [k: string]: any;
  } | null;
  export type After = {
    [k: string]: any;
  } | null;
  export type Entries = RevisionDiffEntry[];
  
  export interface RevisionDiff {
    schema_name?: SchemaName;
    schema_version?: SchemaVersion;
    project_id: ProjectId;
    from_revision_id: FromRevisionId;
    to_revision_id: ToRevisionId;
    entries: Entries;
  }
  export interface RevisionDiffEntry {
    object_type: ObjectType;
    object_key: ObjectKey;
    change_kind: RevisionChangeKind;
    before?: Before;
    after?: After;
  }
}

export namespace ReviewCommentContract {
  export type Id = string;
  export type ProjectId = string;
  export type RevisionId = string;
  export type AuthorId = string;
  export type Body = string;
  export type ObjectIds = string[];
  export type ParentCommentId = string | null;
  export type CreatedAt = string;
  export type ResolvedAt = string | null;
  export type ResolvedBy = string | null;
  
  export interface ReviewCommentRead {
    id: Id;
    project_id: ProjectId;
    revision_id: RevisionId;
    author_id: AuthorId;
    body: Body;
    object_ids: ObjectIds;
    parent_comment_id: ParentCommentId;
    created_at: CreatedAt;
    resolved_at: ResolvedAt;
    resolved_by: ResolvedBy;
  }
}

