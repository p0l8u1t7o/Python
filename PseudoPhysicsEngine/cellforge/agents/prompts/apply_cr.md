# Apply change request

Read the CR identified in the job context and locate its object/time in `timeline.json` and
`checks.json`. Change engineering truth, not generated build files. For a retract, edit the active
robot step's target offset Z because frame Z is the approach/outward direction; preserve ids and
action dependencies.

Validate, build L1, and snapshot the requested time plus one second before/after. Compare the old
and new measured check values and inspect every remaining red/yellow result so a targeted fix does
not introduce another collision, IK failure, limit, hardware, or takt problem. Never substitute a
hardcoded check value. Complete 代理解讀、影響、差異、結果、狀態 in the CR before returning the
required final JSON.
