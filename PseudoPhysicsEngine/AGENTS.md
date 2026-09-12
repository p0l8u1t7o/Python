# Project working rules

Read `docs/automation-digital-twin-platform-plan.md` and
`docs/development-plan.md` before changing product code.

- Treat `D:\Working Space\Python\PseudoPhysicsEngine` as the complete work boundary.
- This directory intentionally remains inside the parent Git repository. Run Git from this
  directory and path-limit every Git operation to `-- .`; never operate on parent or sibling paths.
- Keep internal length units in millimetres and use a right-handed, Z-up coordinate system.
- Preserve parent/child coordinate frames and 4x4 transforms; never store only display XYZ values.
- Give domain objects permanent UUIDs and keep approved project revisions immutable.
- Apply cross-module changes through a versioned `ChangeSet` and validate it before execution.
- Mark inferred dimensions and transforms as `INFERRED`; they cannot pass an engineering release gate.
- Keep Pydantic/JSON Schema contracts separate from database ORM models and version public schemas.
- Route SQLite writes through the backend transaction boundary. Do not let workers write the DB file.
- Keep CAD, mesh, image, video, and PDF binaries out of SQLite and source control.
- Do not claim native editable SolidWorks output outside explicitly supported parametric families.
- Add automated tests for coordinate transforms, revision integrity, and release-gate rules before feature work is considered complete.
