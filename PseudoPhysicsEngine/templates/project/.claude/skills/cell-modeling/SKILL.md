# Cell modeling

Use `cell.yaml` as the only model source and preserve every module id. Prefer modules from `library/`; each module must expose `MODULE` and `build(params)`. Mark estimated geometry `trust: inferred`. Run `cell validate`, `cell build --level L1`, and independent OCP STEP readback before completing a modeling task. Never edit generated files under `build/` or `.cellforge/vN`.
