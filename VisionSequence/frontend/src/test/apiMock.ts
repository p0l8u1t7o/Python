/** `@/lib/api` 的假後端：依路徑回最小合法資料，讓頁面 render 走完 loading → 內容。 */
import { vi } from 'vitest'
import type { FlowGraph, InspectKind } from '@/lib/types'

export const INSPECT_KINDS: InspectKind[] = [{
  kind: 'measure_diameter', version: 1, label: 'Measure diameter', help_text: 'Measure a circular edge.', roles: { find: 'find_circle', tol: 'tolerance_judge' }, public_inputs: [{ role: 'find', port: 'image' }], public_outputs: [], pass_port: { role: 'tol', port: 'in_spec' },
  fields: [
    { key: 'roi', label: 'Region', kind: 'roi', role: 'find', param: 'roi', required: true, default: null, shapes: ['annulus'] },
    { key: 'nominal', label: 'Nominal', kind: 'number', role: 'tol', param: 'nominal', required: true, default: 100 },
    { key: 'upper_tol', label: 'Upper tolerance', kind: 'number', role: 'tol', param: 'upper_tol', required: true, default: 2 },
    { key: 'unit', label: 'Unit', kind: 'select', role: 'tol', param: 'unit', default: 'px', options: [{ value: 'px', label: 'Pixels' }, { value: 'mm', label: 'Millimetres' }] },
    { key: 'calibration', label: 'Calibration', kind: 'asset', role: 'find', param: 'calibration', default: '', accept: 'calibration' },
    { key: 'result_name', label: 'Result name', kind: 'output_key', role: 'tol', param: 'name', default: '' },
  ].map((field) => ({ required: false, help_text: '', options: [], unit: '', minimum: null, maximum: null, step: null, shapes: [], accept: '', ...field })),
}] as InspectKind[]

// 與後端定義一致的多方式表單快照。
INSPECT_KINDS.push(...[
  {
    "kind": "check_presence", "version": 1, "label": "Check presence", "help_text": "Configure and run check presence using the current image.", "roles": {"det": "template_match"}, "internal_edges": [], "public_inputs": [{"role": "det", "port": "image"}, {"role": "det", "port": "roi"}, {"role": "det", "port": "_transform"}, {"role": "det", "port": "_flow"}], "public_outputs": [{"role": "det", "port": "detected"}, {"role": "det", "port": "valid"}], "pass_port": {"role": "det", "port": "valid"},
    "fields": [
      {"key": "method", "label": "Method", "kind": "select", "role": null, "param": null, "required": false, "default": "template", "help_text": "", "unit": "", "options": [{"value": "template", "label": "Template"}, {"value": "blob", "label": "Blob"}, {"value": "print", "label": "Print"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "roi", "label": "Region", "kind": "roi", "role": "det", "param": "roi", "required": false, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": ["rect", "rotated_rect"], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "expected", "label": "Expected", "kind": "select", "role": "det", "param": "expected", "required": false, "default": "present", "help_text": "", "unit": "", "options": [{"value": "present", "label": "Present"}, {"value": "absent", "label": "Absent"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "template_images", "label": "Reference pictures", "kind": "images", "role": null, "param": null, "required": true, "default": [], "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "template"}, "source_type": ""},
      {"key": "threshold", "label": "Score threshold", "kind": "range", "role": "det", "param": "threshold", "required": false, "default": 0.7, "help_text": "NCC score 0–1; below this is not a match.", "unit": "", "options": [], "minimum": 0, "maximum": 1, "step": 0.01, "shapes": [], "accept": "", "visible_when": {"method": "template"}, "source_type": ""},
      {"key": "threshold_method", "label": "Threshold", "kind": "select", "role": "det", "param": "threshold_method", "required": false, "default": "otsu", "help_text": "", "unit": "", "options": [{"value": "otsu", "label": "Otsu (automatic)"}, {"value": "fixed", "label": "Fixed"}, {"value": "hysteresis", "label": "Hysteresis (high seed + low grow)"}, {"value": "soft", "label": "Soft weighted"}, {"value": "none", "label": "The input is already a mask (anything non-zero is foreground)"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "blob"}, "source_type": ""},
      {"key": "blob_threshold", "label": "Threshold", "kind": "number", "role": "det", "param": "threshold", "required": false, "default": 128, "help_text": "", "unit": "", "options": [], "minimum": 0, "maximum": 255, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "blob"}, "source_type": ""},
      {"key": "polarity", "label": "Foreground", "kind": "select", "role": "det", "param": "polarity", "required": false, "default": "bright", "help_text": "", "unit": "", "options": [{"value": "bright", "label": "Bright objects"}, {"value": "dark", "label": "Dark objects"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "blob"}, "source_type": ""},
      {"key": "min_area", "label": "Min area", "kind": "number", "role": "det", "param": "min_area", "required": false, "default": 50, "help_text": "", "unit": "px²", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "blob"}, "source_type": ""},
      {"key": "max_area", "label": "Max area", "kind": "number", "role": "det", "param": "max_area", "required": false, "default": 0, "help_text": "0 means no limit.", "unit": "px²", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "blob"}, "source_type": ""},
      {"key": "print_polarity", "label": "Text colour", "kind": "select", "role": "det", "param": "polarity", "required": false, "default": "dark", "help_text": "", "unit": "", "options": [{"value": "dark", "label": "Dark text"}, {"value": "bright", "label": "Light text"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "print"}, "source_type": ""},
      {"key": "min_ratio", "label": "Min stroke ratio", "kind": "range", "role": "det", "param": "min_ratio", "required": false, "default": 0.03, "help_text": "", "unit": "", "options": [], "minimum": 0, "maximum": 1, "step": 0.005, "shapes": [], "accept": "", "visible_when": {"method": "print"}, "source_type": ""},
      {"key": "max_ratio", "label": "Max stroke ratio", "kind": "range", "role": "det", "param": "max_ratio", "required": false, "default": 0.6, "help_text": "Above this it is treated as smearing or a solid block.", "unit": "", "options": [], "minimum": 0, "maximum": 1, "step": 0.005, "shapes": [], "accept": "", "visible_when": {"method": "print"}, "source_type": ""},
      {"key": "required", "label": "Required", "kind": "boolean", "role": null, "param": null, "required": false, "default": true, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "locator", "label": "Locator", "kind": "text", "role": null, "param": null, "required": false, "default": "", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
    ],
  },
  {
    "kind": "count_objects", "version": 1, "label": "Count objects", "help_text": "Configure and run count objects using the current image.", "roles": {"blob": "blob", "range": "in_range"}, "internal_edges": [{"source_role": "blob", "source_port": "count", "target_role": "range", "target_port": "value"}], "public_inputs": [{"role": "blob", "port": "image"}, {"role": "blob", "port": "roi"}, {"role": "blob", "port": "_transform"}, {"role": "blob", "port": "_flow"}], "public_outputs": [{"role": "blob", "port": "count"}, {"role": "range", "port": "result"}], "pass_port": {"role": "range", "port": "result"},
    "fields": [
      {"key": "roi", "label": "Region", "kind": "roi", "role": "blob", "param": "roi", "required": false, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": ["rect", "rotated_rect"], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "threshold_method", "label": "Threshold", "kind": "select", "role": "blob", "param": "threshold_method", "required": false, "default": "otsu", "help_text": "", "unit": "", "options": [{"value": "otsu", "label": "Otsu (automatic)"}, {"value": "fixed", "label": "Fixed"}, {"value": "hysteresis", "label": "Hysteresis (high seed + low grow)"}, {"value": "soft", "label": "Soft weighted"}, {"value": "none", "label": "The input is already a mask (anything non-zero is foreground)"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "threshold", "label": "Threshold", "kind": "number", "role": "blob", "param": "threshold", "required": false, "default": 128, "help_text": "", "unit": "", "options": [], "minimum": 0, "maximum": 255, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "polarity", "label": "Foreground", "kind": "select", "role": "blob", "param": "polarity", "required": false, "default": "bright", "help_text": "", "unit": "", "options": [{"value": "bright", "label": "Bright objects"}, {"value": "dark", "label": "Dark objects"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "min_area", "label": "Min area", "kind": "number", "role": "blob", "param": "min_area", "required": false, "default": 50, "help_text": "", "unit": "px²", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "max_area", "label": "Max area", "kind": "number", "role": "blob", "param": "max_area", "required": false, "default": 0, "help_text": "0 means no limit.", "unit": "px²", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "min_circularity", "label": "Min circularity", "kind": "range", "role": "blob", "param": "min_circularity", "required": false, "default": 0, "help_text": "4πA/P², 1 for a perfect circle.", "unit": "", "options": [], "minimum": 0, "maximum": 1, "step": 0.01, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "min_count", "label": "Minimum count", "kind": "number", "role": "range", "param": "low", "required": false, "default": 0, "help_text": "", "unit": "", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "max_count", "label": "Maximum count", "kind": "number", "role": "range", "param": "high", "required": false, "default": 10, "help_text": "", "unit": "", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "result_name", "label": "Result name", "kind": "output_key", "role": null, "param": null, "required": false, "default": "count", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "required", "label": "Required", "kind": "boolean", "role": null, "param": null, "required": false, "default": true, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "locator", "label": "Locator", "kind": "text", "role": null, "param": null, "required": false, "default": "", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
    ],
  },
  {
  "kind": "inspect_circular_surface",
  "version": 1,
  "label": "Inspect circular surface",
  "help_text": "Configure and run inspect circular surface using the current image.",
  "roles": {
    "unwrap": "polar_unwrap",
    "defect": "edge_defect",
    "geom": "defects_to_geometry",
    "restore": "polar_restore"
  },
  "internal_edges": [
    {
      "source_role": "unwrap",
      "source_port": "image",
      "target_role": "defect",
      "target_port": "image"
    },
    {
      "source_role": "defect",
      "source_port": "defects",
      "target_role": "geom",
      "target_port": "defects"
    },
    {
      "source_role": "geom",
      "source_port": "points",
      "target_role": "restore",
      "target_port": "points"
    },
    {
      "source_role": "geom",
      "source_port": "contours",
      "target_role": "restore",
      "target_port": "contours"
    },
    {
      "source_role": "unwrap",
      "source_port": "mapping",
      "target_role": "restore",
      "target_port": "mapping"
    },
    {
      "source_role": "defect",
      "source_port": "ok",
      "target_role": "restore",
      "target_port": "_flow"
    },
    {
      "source_role": "defect",
      "source_port": "defect",
      "target_role": "restore",
      "target_port": "_flow"
    }
  ],
  "fields": [
    {
      "key": "roi",
      "label": "Region",
      "kind": "roi",
      "role": "unwrap",
      "param": "roi",
      "required": true,
      "default": null,
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [
        "annulus"
      ],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "direction",
      "label": "Direction",
      "kind": "select",
      "role": "unwrap",
      "param": "direction",
      "required": false,
      "default": "ccw",
      "help_text": "Which way around the ring the strip runs, as seen on screen.",
      "unit": "",
      "options": [
        {
          "value": "ccw",
          "label": "Counter-clockwise"
        },
        {
          "value": "cw",
          "label": "Clockwise"
        }
      ],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "start_angle",
      "label": "Start angle",
      "kind": "number",
      "role": "unwrap",
      "param": "start_angle",
      "required": false,
      "default": 0,
      "help_text": "Where the left edge of the strip sits (0 = 3 o'clock, positive = clockwise). Ignored for a sector, which starts at its own angles.",
      "unit": "°",
      "options": [],
      "minimum": -360,
      "maximum": 360,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "polarity",
      "label": "Edge polarity",
      "kind": "select",
      "role": "defect",
      "param": "polarity",
      "required": false,
      "default": "light_to_dark",
      "help_text": "",
      "unit": "",
      "options": [
        {
          "value": "any",
          "label": "Any"
        },
        {
          "value": "dark_to_light",
          "label": "Dark to light"
        },
        {
          "value": "light_to_dark",
          "label": "Light to dark"
        }
      ],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "threshold",
      "label": "Defect threshold",
      "kind": "number",
      "role": "defect",
      "param": "threshold",
      "required": false,
      "default": 3,
      "help_text": "",
      "unit": "px",
      "options": [],
      "minimum": 0,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "max_defects",
      "label": "More faults than this is a reject",
      "kind": "number",
      "role": "defect",
      "param": "max_defects",
      "required": false,
      "default": 0,
      "help_text": "0 = any fault is a reject.",
      "unit": "",
      "options": [],
      "minimum": 0,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "min_length",
      "label": "Minimum defect length",
      "kind": "number",
      "role": null,
      "param": null,
      "required": false,
      "default": 1,
      "help_text": "Applies to every fault, including gaps. Arc length uses the midpoint radius of the taught ring.",
      "unit": "",
      "options": [],
      "minimum": 0,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "unit",
      "label": "Length unit",
      "kind": "select",
      "role": null,
      "param": null,
      "required": false,
      "default": "deg",
      "help_text": "",
      "unit": "",
      "options": [
        {
          "value": "deg",
          "label": "Deg"
        },
        {
          "value": "mm",
          "label": "Mm"
        }
      ],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "calibration",
      "label": "Calibration",
      "kind": "asset",
      "role": null,
      "param": null,
      "required": false,
      "default": "",
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "calibration",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "defect_direction",
      "label": "Defect direction",
      "kind": "select",
      "role": "defect",
      "param": "direction",
      "required": false,
      "default": "inward",
      "help_text": "",
      "unit": "",
      "options": [
        {
          "value": "both",
          "label": "Both"
        },
        {
          "value": "inward",
          "label": "Inward"
        },
        {
          "value": "outward",
          "label": "Outward"
        }
      ],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "result_name",
      "label": "Result name",
      "kind": "output_key",
      "role": null,
      "param": null,
      "required": false,
      "default": "defects",
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "search",
      "label": "Search range",
      "kind": "number",
      "role": "defect",
      "param": "search",
      "required": false,
      "default": 35,
      "help_text": "",
      "unit": "px",
      "options": [],
      "minimum": 2,
      "maximum": 2000,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "geometry",
      "label": "Defect geometry",
      "kind": "select",
      "role": "geom",
      "param": "output",
      "required": false,
      "default": "centres",
      "help_text": "",
      "unit": "",
      "options": [
        {
          "value": "centres",
          "label": "Centres"
        },
        {
          "value": "boxes",
          "label": "Boxes"
        },
        {
          "value": "spans",
          "label": "Spans"
        }
      ],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "required",
      "label": "Required",
      "kind": "boolean",
      "role": null,
      "param": null,
      "required": false,
      "default": true,
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "locator",
      "label": "Locator",
      "kind": "text",
      "role": null,
      "param": null,
      "required": false,
      "default": "",
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    }
  ],
  "public_inputs": [
    {
      "role": "unwrap",
      "port": "image"
    },
    {
      "role": "unwrap",
      "port": "roi"
    },
    {
      "role": "unwrap",
      "port": "_transform"
    },
    {
      "role": "unwrap",
      "port": "_flow"
    },
    {
      "role": "restore",
      "port": "image"
    }
  ],
  "public_outputs": [
    {
      "role": "defect",
      "port": "count"
    },
    {
      "role": "restore",
      "port": "points"
    },
    {
      "role": "restore",
      "port": "contours"
    }
  ],
  "pass_port": null
},
  {
    "kind": "inspect_edge_defect", "version": 1, "label": "Inspect edge defect", "help_text": "Configure and run inspect edge defect using the current image.", "roles": {"defect": "edge_defect"}, "internal_edges": [], "public_inputs": [{"role": "defect", "port": "image"}, {"role": "defect", "port": "roi"}, {"role": "defect", "port": "_transform"}, {"role": "defect", "port": "_flow"}, {"role": "defect", "port": "line"}, {"role": "defect", "port": "circle"}], "public_outputs": [{"role": "defect", "port": "count"}, {"role": "defect", "port": "defects"}], "pass_port": null,
    "fields": [
      {"key": "method", "label": "Method", "kind": "select", "role": null, "param": null, "required": false, "default": "simple", "help_text": "", "unit": "", "options": [{"value": "simple", "label": "Simple"}, {"value": "freeform", "label": "Freeform"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "roi", "label": "Region", "kind": "roi", "role": "defect", "param": "roi", "required": false, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": ["rect", "rotated_rect", "circle", "annulus"], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "reference", "label": "Reference geometry", "kind": "json", "role": null, "param": null, "required": false, "default": null, "help_text": "Optional line or circle source. A connected source takes precedence over the drawn region.", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "simple"}, "source_type": "geometry"},
      {"key": "mode", "label": "What each caliper looks for", "kind": "select", "role": "defect", "param": "mode", "required": false, "default": "single", "help_text": "", "unit": "", "options": [{"value": "single", "label": "One edge"}, {"value": "pair", "label": "A pair of edges (a rib, a groove, a gap)"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "polarity", "label": "Edge polarity", "kind": "select", "role": "defect", "param": "polarity", "required": false, "default": "any", "help_text": "", "unit": "", "options": [{"value": "any", "label": "Either"}, {"value": "dark_to_light", "label": "Dark to light"}, {"value": "light_to_dark", "label": "Light to dark"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "pair_polarity", "label": "The band between the edges is", "kind": "select", "role": "defect", "param": "pair_polarity", "required": false, "default": "any", "help_text": "", "unit": "", "options": [{"value": "any", "label": "Either"}, {"value": "bright", "label": "Brighter"}, {"value": "dark", "label": "Darker"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "search", "label": "Search range", "kind": "number", "role": "defect", "param": "search", "required": false, "default": 20, "help_text": "How far either side of the ideal edge each caliper looks.", "unit": "px", "options": [], "minimum": 2, "maximum": 2000, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "threshold", "label": "Out by more than", "kind": "number", "role": "defect", "param": "threshold", "required": false, "default": 2.0, "help_text": "A stretch further than this from the ideal edge is a fault.", "unit": "px", "options": [], "minimum": 0, "maximum": null, "step": 0.1, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "min_width", "label": "At least this many calipers", "kind": "number", "role": "defect", "param": "min_width", "required": false, "default": 2, "help_text": "Stops single-caliper noise being called a fault.", "unit": "", "options": [], "minimum": 1, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "direction", "label": "Which side counts", "kind": "select", "role": "defect", "param": "direction", "required": false, "default": "both", "help_text": "", "unit": "", "options": [{"value": "both", "label": "Either side"}, {"value": "inward", "label": "Only missing material"}, {"value": "outward", "label": "Only extra material"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "width_min", "label": "Width at least", "kind": "number", "role": "defect", "param": "width_min", "required": false, "default": 0, "help_text": "0 = do not check.", "unit": "px", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "width_max", "label": "Width at most", "kind": "number", "role": "defect", "param": "width_max", "required": false, "default": 0, "help_text": "0 = do not check.", "unit": "px", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "max_defects", "label": "More faults than this is a reject", "kind": "number", "role": "defect", "param": "max_defects", "required": false, "default": 0, "help_text": "0 = any fault is a reject.", "unit": "", "options": [], "minimum": 0, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "baseline", "label": "The ideal edge is", "kind": "select", "role": "defect", "param": "baseline", "required": false, "default": "fit", "help_text": "Fitted suits a part that moves; the region itself suits a fixture where the edge must be in one place.", "unit": "", "options": [{"value": "fit", "label": "Fitted to what was found (a line or a circle)"}, {"value": "median", "label": "A moving median (follows a gentle curve)"}, {"value": "reference", "label": "Exactly the region or the wired-in shape"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "simple"}, "source_type": ""},
      {"key": "model", "label": "Taught outline", "kind": "json", "role": "defect", "param": "model", "required": true, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"method": "freeform"}, "source_type": ""},
      {"key": "required", "label": "Required", "kind": "boolean", "role": null, "param": null, "required": false, "default": true, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "locator", "label": "Locator", "kind": "text", "role": null, "param": null, "required": false, "default": "", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
    ],
  },
  {
  "kind": "locate_part",
  "version": 1,
  "label": "Locate part",
  "help_text": "Find a taught template and publish a position correction transform for downstream tasks.",
  "roles": {
    "ref": "fixed_image",
    "find": "template_match",
    "align": "shape_align"
  },
  "internal_edges": [
    {
      "source_role": "ref",
      "source_port": "image",
      "target_role": "find",
      "target_port": "template_image"
    },
    {
      "source_role": "find",
      "source_port": "matches",
      "target_role": "align",
      "target_port": "matches"
    }
  ],
  "fields": [
    {
      "key": "method",
      "label": "Method",
      "kind": "select",
      "role": null,
      "param": null,
      "required": false,
      "default": "template",
      "help_text": "",
      "unit": "",
      "options": [
        {
          "value": "template",
          "label": "Template"
        },
        {
          "value": "shape",
          "label": "Shape model"
        },
        {
          "value": "register",
          "label": "Registered examples"
        }
      ],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "roi",
      "label": "Search region",
      "kind": "roi",
      "role": "find",
      "param": "roi",
      "required": false,
      "default": null,
      "help_text": "Leave blank to search the whole image.",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [
        "rect",
        "rotated_rect"
      ],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "template_images",
      "label": "Locator mark",
      "kind": "images",
      "role": "ref",
      "param": "images",
      "required": true,
      "default": [],
      "help_text": "A fixed reference picture cropped from the taught part.",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": {
        "method": [
          "template",
          "register"
        ]
      },
      "source_type": ""
    },
    {
      "key": "model",
      "label": "Shape model",
      "kind": "asset",
      "role": "find",
      "param": "model",
      "required": true,
      "default": "",
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "file",
      "visible_when": {
        "method": "shape"
      },
      "source_type": ""
    },
    {
      "key": "threshold",
      "label": "Score threshold",
      "kind": "range",
      "role": "find",
      "param": "threshold",
      "required": false,
      "default": 0.7,
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": 0,
      "maximum": 1,
      "step": 0.01,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "allow_rotation",
      "label": "Allow rotation",
      "kind": "boolean",
      "role": null,
      "param": null,
      "required": false,
      "default": false,
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "angle_range",
      "label": "Rotation range",
      "kind": "number",
      "role": "find",
      "param": "angle_range",
      "required": false,
      "default": 0,
      "help_text": "",
      "unit": "deg",
      "options": [],
      "minimum": 0,
      "maximum": 180,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "ref_x",
      "label": "Reference X",
      "kind": "number",
      "role": "align",
      "param": "ref_x",
      "required": true,
      "default": 0,
      "help_text": "",
      "unit": "px",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "ref_y",
      "label": "Reference Y",
      "kind": "number",
      "role": "align",
      "param": "ref_y",
      "required": true,
      "default": 0,
      "help_text": "",
      "unit": "px",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "ref_angle",
      "label": "Reference angle",
      "kind": "number",
      "role": "align",
      "param": "ref_angle",
      "required": false,
      "default": 0,
      "help_text": "",
      "unit": "deg",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    },
    {
      "key": "required",
      "label": "Required",
      "kind": "boolean",
      "role": null,
      "param": null,
      "required": false,
      "default": true,
      "help_text": "",
      "unit": "",
      "options": [],
      "minimum": null,
      "maximum": null,
      "step": null,
      "shapes": [],
      "accept": "",
      "visible_when": null,
      "source_type": ""
    }
  ],
  "public_inputs": [
    {
      "role": "find",
      "port": "image"
    }
  ],
  "public_outputs": [
    {
      "role": "align",
      "port": "transform"
    },
    {
      "role": "find",
      "port": "found"
    },
    {
      "role": "find",
      "port": "detected"
    }
  ],
  "pass_port": null
},
  {
    "kind": "measure_distance", "version": 1, "label": "Measure distance", "help_text": "Configure and run measure distance using the current image.", "roles": {"cal": "caliper", "tol": "tolerance_judge"}, "internal_edges": [{"source_role": "cal", "source_port": "width", "target_role": "tol", "target_port": "value"}], "public_inputs": [{"role": "cal", "port": "image"}, {"role": "cal", "port": "roi"}, {"role": "cal", "port": "_transform"}, {"role": "cal", "port": "_flow"}], "public_outputs": [{"role": "cal", "port": "width"}, {"role": "tol", "port": "in_spec"}], "pass_port": {"role": "tol", "port": "in_spec"},
    "fields": [
      {"key": "mode", "label": "Mode", "kind": "select", "role": null, "param": null, "required": false, "default": "edge_pair", "help_text": "", "unit": "", "options": [{"value": "edge_pair", "label": "Edge pair"}, {"value": "hole_centres", "label": "Hole centres"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "roi", "label": "Region", "kind": "roi", "role": "cal", "param": "roi", "required": true, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": ["rect", "rotated_rect"], "accept": "", "visible_when": {"mode": "edge_pair"}, "source_type": ""},
      {"key": "roi_a", "label": "Region A", "kind": "roi", "role": "find_a", "param": "roi", "required": true, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": ["annulus", "circle", "rect"], "accept": "", "visible_when": {"mode": "hole_centres"}, "source_type": ""},
      {"key": "roi_b", "label": "Region B", "kind": "roi", "role": "find_b", "param": "roi", "required": true, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": ["annulus", "circle", "rect"], "accept": "", "visible_when": {"mode": "hole_centres"}, "source_type": ""},
      {"key": "polarity", "label": "Edge polarity", "kind": "select", "role": "cal", "param": "polarity", "required": false, "default": "any", "help_text": "", "unit": "", "options": [{"value": "any", "label": "Any"}, {"value": "dark_to_light", "label": "Dark to light"}, {"value": "light_to_dark", "label": "Light to dark"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "edge_pair"}, "source_type": ""},
      {"key": "edge_pair", "label": "Pick edge pair", "kind": "select", "role": "cal", "param": "edge_pair", "required": false, "default": "first_last", "help_text": "", "unit": "", "options": [{"value": "first_last", "label": "First and last"}, {"value": "widest", "label": "Widest pair"}, {"value": "narrowest", "label": "Narrowest adjacent pair"}, {"value": "strongest", "label": "Two strongest"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "edge_pair"}, "source_type": ""},
      {"key": "pair_polarity", "label": "Edge pair polarity", "kind": "select", "role": "cal", "param": "pair_polarity", "required": false, "default": "any", "help_text": "Constrains the polarity order of a pair, so measuring a bright or dark bar does not latch onto a neighbouring noise edge.", "unit": "", "options": [{"value": "any", "label": "Any"}, {"value": "bright", "label": "Bright band (dark to light, then light to dark)"}, {"value": "dark", "label": "Dark band (light to dark, then dark to light)"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "edge_pair"}, "source_type": ""},
      {"key": "nominal", "label": "Nominal", "kind": "number", "role": "tol", "param": "nominal", "required": false, "default": 0, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "upper_tol", "label": "Upper deviation", "kind": "number", "role": "tol", "param": "upper_tol", "required": false, "default": 0.1, "help_text": "Signed; the upper limit is nominal + this.", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "lower_tol", "label": "Lower deviation", "kind": "number", "role": "tol", "param": "lower_tol", "required": false, "default": -0.1, "help_text": "Signed, normally negative; the lower limit is nominal + this.", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "unit", "label": "Unit", "kind": "select", "role": "tol", "param": "unit", "required": false, "default": "px", "help_text": "", "unit": "", "options": [{"value": "px", "label": "Px"}, {"value": "mm", "label": "Mm"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "result_name", "label": "Dimension name", "kind": "text", "role": "tol", "param": "name", "required": false, "default": "", "help_text": "The name written into outputs.tolerances; blank uses the step's label.", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "calibration", "label": "Calibration", "kind": "asset", "role": null, "param": null, "required": false, "default": "", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "calibration", "visible_when": null, "source_type": ""},
      {"key": "required", "label": "Required", "kind": "boolean", "role": null, "param": null, "required": false, "default": true, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "locator", "label": "Locator", "kind": "text", "role": null, "param": null, "required": false, "default": "", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
    ],
  },
  {
    "kind": "read_and_verify", "version": 1, "label": "Read and verify", "help_text": "Configure and run read and verify using the current image.", "roles": {"read": "barcode"}, "internal_edges": [], "public_inputs": [{"role": "read", "port": "image"}, {"role": "read", "port": "roi"}, {"role": "read", "port": "_transform"}, {"role": "read", "port": "_flow"}], "public_outputs": [{"role": "read", "port": "first"}, {"role": "read", "port": "count"}], "pass_port": null,
    "fields": [
      {"key": "mode", "label": "Mode", "kind": "select", "role": null, "param": null, "required": false, "default": "code", "help_text": "", "unit": "", "options": [{"value": "code", "label": "Code"}, {"value": "text", "label": "Text"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "roi", "label": "Region", "kind": "roi", "role": "read", "param": "roi", "required": false, "default": null, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": ["rect", "rotated_rect"], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "types", "label": "Type", "kind": "select", "role": "read", "param": "types", "required": false, "default": "all", "help_text": "", "unit": "", "options": [{"value": "all", "label": "All codes"}, {"value": "qr", "label": "QR only"}, {"value": "2d", "label": "2D codes (QR, Data Matrix, Aztec, PDF417)"}, {"value": "1d", "label": "1D barcodes only"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "code"}, "source_type": ""},
      {"key": "expected", "label": "Expected text", "kind": "text", "role": null, "param": null, "required": false, "default": "", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "font_model", "label": "Model", "kind": "asset", "role": "read", "param": "model", "required": false, "default": null, "help_text": "Blank = the built-in general model. A taught font (.npz) switches to segmentation plus per-character classification.", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "model", "visible_when": {"mode": "text"}, "source_type": ""},
      {"key": "charset", "label": "Character set", "kind": "select", "role": "read", "param": "charset", "required": false, "default": "alnum", "help_text": "", "unit": "", "options": [{"value": "alnum", "label": "Letters and digits"}, {"value": "digits", "label": "Digits (and - . / :)"}, {"value": "upper", "label": "Upper-case letters and digits"}, {"value": "any", "label": "Any character"}, {"value": "custom", "label": "Custom"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "text"}, "source_type": ""},
      {"key": "custom_charset", "label": "Custom characters", "kind": "text", "role": "read", "param": "custom_charset", "required": false, "default": null, "help_text": "Every character that may appear, e.g. 0123456789ABCDEF-", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "text"}, "source_type": ""},
      {"key": "polarity", "label": "Polarity", "kind": "select", "role": "read", "param": "polarity", "required": false, "default": "dark_on_light", "help_text": "", "unit": "", "options": [{"value": "dark_on_light", "label": "Dark text on a light background"}, {"value": "light_on_dark", "label": "Light text on a dark background"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "text"}, "source_type": ""},
      {"key": "min_confidence", "label": "Min confidence", "kind": "range", "role": "read", "param": "min_confidence", "required": false, "default": 0.5, "help_text": "A character below this makes the read not found.", "unit": "", "options": [], "minimum": 0, "maximum": 1, "step": 0.05, "shapes": [], "accept": "", "visible_when": {"mode": "text"}, "source_type": ""},
      {"key": "pattern", "label": "Position pattern", "kind": "text", "role": "read", "param": "pattern", "required": false, "default": "", "help_text": "N=digit, A=letter, X=any, any other character must match exactly. Blank disables this check.", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "text"}, "source_type": ""},
      {"key": "verify_mode", "label": "Mode", "kind": "select", "role": "verify", "param": "mode", "required": false, "default": "exact", "help_text": "", "unit": "", "options": [{"value": "exact", "label": "Exact"}, {"value": "contains", "label": "Contains"}, {"value": "regex", "label": "Regular expression"}], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": {"mode": "text"}, "source_type": ""},
      {"key": "result_name", "label": "Result name", "kind": "output_key", "role": null, "param": null, "required": false, "default": "text", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "required", "label": "Required", "kind": "boolean", "role": null, "param": null, "required": false, "default": true, "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
      {"key": "locator", "label": "Locator", "kind": "text", "role": null, "param": null, "required": false, "default": "", "help_text": "", "unit": "", "options": [], "minimum": null, "maximum": null, "step": null, "shapes": [], "accept": "", "visible_when": null, "source_type": ""},
    ],
  },
] as InspectKind[])

export const INSPECT_GRAPH: FlowGraph = {
  nodes: [
    { id: 'camera', type: 'image_source', params: { source_id: 1 } },
    { id: 'd_find', type: 'find_circle', params: { roi: { shape: 'annulus', cx: 200, cy: 200, r_inner: 40, r_outer: 60 }, calibration: '' }, meta: { inspect: { task_id: 'd', role: 'find', kind: 'measure_diameter', schema_version: 1, required: true } } },
    { id: 'd_tol', type: 'tolerance_judge', params: { nominal: 100, upper_tol: 2, unit: 'px', name: 'Diameter' }, meta: { inspect: { task_id: 'd', role: 'tol', kind: 'measure_diameter', schema_version: 1, required: true } } },
  ], edges: [{ source: 'camera', source_handle: 'image', target: 'd_find', target_handle: 'image' }, { source: 'd_find', source_handle: 'diameter', target: 'd_tol', target_handle: 'value' }],
}

function inspectMock(path: string, body?: unknown) {
  const payload = body as { graph: FlowGraph; task?: { task_id?: string; fields: Record<string, unknown> }; task_id?: string }
  if (path.endsWith('/kinds')) return { items: INSPECT_KINDS }
  const graph = payload.graph
  if (path.endsWith('/read')) {
    const find = graph.nodes.find((node) => node.id === 'd_find')
    const tol = graph.nodes.find((node) => node.id === 'd_tol')
    const inst = graph.nodes.find((node) => node.type === 'composite:measure_diameter')
    const instanceTask = inst ? [{ task_id: inst.id, kind: 'measure_diameter', version: 1, required: true, nodes: { instance: inst.id }, fields: { roi: inst.params?.['find:roi'], calibration: '', nominal: inst.params?.['tol:nominal'], upper_tol: inst.params?.['tol:upper_tol'], unit: 'px', result_name: 'dia' }, disabled: false, custom: false, reasons: [], source: 'composite', tool: 'measure_diameter' }] : []
    return { tasks: [...(find && tol ? [{ task_id: 'd', kind: 'measure_diameter', version: 1, required: true, nodes: { find: 'd_find', tol: 'd_tol' }, fields: { roi: find.params?.roi, calibration: find.params?.calibration ?? '', nominal: tol.params?.nominal, upper_tol: tol.params?.upper_tol, unit: tol.params?.unit, result_name: tol.params?.name }, disabled: find.enabled === false || tol.enabled === false, custom: false, reasons: [] }] : []), ...instanceTask], shared: [{ id: 'camera', type: 'image_source' }], loose: graph.nodes.filter((node) => !node.meta?.inspect && node.type !== 'image_source' && !node.type.startsWith('composite:')).map(({ id, type }) => ({ id, type })) }
  }
  if (path.endsWith('/evidence')) return { items: [{ task_id: 'd', verdict: 'pass', valid: true, detected: true, value: 99.9, unit: 'px', reason: '', overlays: [], node_id: 'd_tol' }] }
  if (path.endsWith('/remove')) return { graph, removed: false, dependencies: [{ target: 'camera', title: 'Downstream camera', target_handle: 'image' }] }
  if (path.endsWith('/update')) {
    const next = structuredClone(graph)
    for (const field of INSPECT_KINDS[0].fields) {
      if (payload.task?.fields && field.key in payload.task.fields) {
        const node = next.nodes.find((entry) => entry.id === `d_${field.role}`)
        if (node && field.param) node.params = { ...node.params, [field.param]: payload.task.fields[field.key] }
      }
    }
    return { graph: next }
  }
  return { graph }
}

export const ME = {
  // 與真實 /auth/me 一致：帶 is_admin 與 role，否則前端會把測試身分當成工程師
  kind: 'user', is_admin: true, role: 'admin',
  user: { id: 1, username: 'admin', display_name: '管理員', is_staff: true, is_active: true, role: 'admin' },
  permissions: ['flows.run', 'flows.teach', 'flows.edit', 'sources', 'assets', 'batch', 'golden', 'dl', 'agent', 'integration', 'audit'],
  prefs: {}, lock: { locked: false, holder: '', reason: '', expires_at: null },
}

export const FLOW = { id: 1, kind: 'flow', name: '示範流程', description: 'Inspect the sample part and publish width.', version: 1, is_enabled: true, continuous_interval_ms: 0, timeout_s: 0, concurrency: 1, stop_on_ng: false, owner_id: 1, owner_name: 'admin', recipe_count: 0, commissioned: false, check_count: 1, stats: { last_status: 'ok', total: 3, ok: 3, ng: 0, failed: 0, avg_ms: 5, last_ms: 5, running: false, continuous: false, queued: 0 }, graph: { nodes: [{ id: 'camera', type: 'image_source', label: 'Camera', params: { source_id: 1 } }, { id: 'thr', type: 'threshold', label: 'Threshold', params: { method: 'fixed', threshold: 60 } }, { id: 'judge_out', type: 'output', params: { name: 'judge' } }, { id: 'width_out', type: 'output', params: { name: 'width' } }], edges: [] }, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }
export const COMPOSITE_TOOL = { id: 7, key: 'count_holes', type: 'composite:count_holes', label: 'Count holes', description: 'Threshold and count', category: 'detect', category_label: 'Detection', icon: 'Boxes', builtin: false, flow_id: 77, interface: { inputs: [{ key: 'thr:image', exposed: true }], outputs: [{ key: 'blob:count', exposed: true }] }, created_by: 'admin', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version: 1, used_by_flows: 1, used_by_tools: 0, uses: [] }
export const FLOW_TOOL = { ...FLOW, id: 77, kind: 'tool', name: 'tool:count_holes', description: 'Threshold and count', is_enabled: false, composite_tool: { id: 7, key: 'count_holes', label: 'Count holes', builtin: false, interface: { inputs: [{ key: 'thr:image', exposed: true }], outputs: [{ key: 'blob:count', exposed: true }], params: [{ key: 'thr:threshold', alias: 'Level', teach: true }] } }, graph: { nodes: [{ id: 'thr', type: 'threshold', label: 'Threshold', params: { method: 'fixed', threshold: 60 } }, { id: 'blob', type: 'blob', label: 'Blob', params: {} }], edges: [{ id: 'e1', source: 'thr', source_handle: 'image', target: 'blob', target_handle: 'image' }] } }
export const FLOW_BARE = { ...FLOW, id: 9, name: '只有取像', check_count: 0, graph: { nodes: [FLOW.graph.nodes[0]], edges: [] } }
export const FLOW_SIDE = { ...FLOW, id: 2, name: '側面流程', graph: { ...FLOW.graph, nodes: FLOW.graph.nodes.map((node) => node.id === 'thr' ? { ...node, params: { method: 'fixed', threshold: 80 } } : node) } }
export const FLOW_GROUPED = {
  ...FLOW,
  id: 3,
  name: 'Grouped inspection',
  description: '',
  commissioned: true,
  graph: {
    nodes: [
      { id: 'camera', type: 'image_source', label: 'Camera', params: { source_id: 1 }, position: { x: 0, y: 0 } },
      { id: 'find_dia', type: 'blob', label: 'Find diameter', params: {}, position: { x: 300, y: 0 }, meta: { inspect: { task_id: 'diameter', role: 'find', kind: 'measure_diameter', schema_version: 1, required: true } } },
      { id: 'judge_dia', type: 'in_range', label: 'Judge diameter', params: {}, position: { x: 560, y: 0 }, meta: { inspect: { task_id: 'diameter', role: 'judge', kind: 'measure_diameter', schema_version: 1, required: true } } },
      { id: 'find_count', type: 'blob', label: 'Find parts', params: {}, position: { x: 300, y: 180 }, meta: { inspect: { task_id: 'count', role: 'find', kind: 'count_objects', schema_version: 1, required: true } } },
      { id: 'judge_count', type: 'in_range', label: 'Judge count', params: {}, position: { x: 560, y: 180 }, meta: { inspect: { task_id: 'count', role: 'judge', kind: 'count_objects', schema_version: 1, required: true } } },
    ],
    edges: [
      { id: 'e1', source: 'camera', source_handle: 'image', target: 'find_dia', target_handle: 'image' },
      { id: 'e2', source: 'find_dia', source_handle: 'count', target: 'judge_dia', target_handle: 'value' },
      { id: 'e3', source: 'camera', source_handle: 'image', target: 'find_count', target_handle: 'image' },
      { id: 'e4', source: 'find_count', source_handle: 'count', target: 'judge_count', target_handle: 'value' },
    ],
  },
}
export const TEACH_PARAM = { key: 'threshold', label: 'Threshold', kind: 'number', required: false, default: 128, help_text: '', options: [], unit: '', minimum: 0, maximum: 255, step: 1, visible_when: null, shapes: [], accept: '', group: '', teach: true }
export const STATION_TEACH_ROWS = [
  { id: '1:thr:threshold', flow_id: 1, flow_name: FLOW.name, flow_version: 1, node_id: 'thr', node_label: 'Threshold', tool_type: 'threshold', tool_label: 'Threshold', tool_category: 'preprocess', param: TEACH_PARAM, value: 60 },
  { id: '2:thr:threshold', flow_id: 2, flow_name: FLOW_SIDE.name, flow_version: 1, node_id: 'thr', node_label: 'Threshold', tool_type: 'threshold', tool_label: 'Threshold', tool_category: 'preprocess', param: TEACH_PARAM, value: 80 },
]

export const RUNS = [
  { id: 'run-2', flow_id: 1, flow_version: 1, trigger: 'ui', status: 'ng', started_at: 1788500100, finished_at: 1788500101, duration_ms: 14, error: '', outputs: { judge: 'NG', width: 2.2 }, nodes: { camera: { status: 'ok', duration_ms: 2, message: '', branch: null, outputs: { image: { ref: 'run-2:image', width: 640, height: 480 } }, overlays: [], overlay_on: null, detail: {}, logs: [] } }, persisted: true },
  { id: 'run-1', flow_id: 1, flow_version: 1, trigger: 'ui', status: 'ok', started_at: 1788500000, finished_at: 1788500001, duration_ms: 13.5, error: '', outputs: { judge: 'OK', width: 1.5 }, nodes: { camera: { status: 'ok', duration_ms: 2, message: '', branch: null, outputs: { image: { ref: 'run-1:image', width: 640, height: 480 } }, overlays: [], overlay_on: null, detail: {}, logs: [] } }, persisted: true },
]

export const DASHBOARD_LAYOUT = {
  rows: 2,
  cols: 3,
  cells: [
    { id: 'image', row: 1, col: 1, row_span: 2, col_span: 2 },
    { id: 'verdict', row: 1, col: 3, row_span: 1, col_span: 1 },
    { id: 'stats', row: 2, col: 3, row_span: 1, col_span: 1 },
  ],
  bars: { top: true, bottom: true, left: false, right: false },
  default_flow_id: 1,
  widgets: [
    { id: 'latest_image', type: 'image', cell: 'image', props: { overlays: true, crosshair: true }, source: { flow_id: 1, kind: 'image' } },
    { id: 'verdict', type: 'verdict', cell: 'verdict', props: {}, source: { flow_id: 1, kind: 'status' } },
    { id: 'today', type: 'stats', cell: 'stats', props: {}, source: { flow_id: 1, kind: 'counts' } },
  ],
  theme: {},
}

export const DASHBOARD = { id: 1, name: 'Line status dashboard', is_default: true, owner_name: 'admin', updated_at: '2026-01-01T00:00:00Z', widget_count: 3, layout: DASHBOARD_LAYOUT }

export const DASHBOARD_CHILD_LAYOUT = {
  rows: 1,
  cols: 1,
  cells: [
    { id: 'main', row: 1, col: 1, row_span: 1, col_span: 1 },
  ],
  bars: { top: false, bottom: false, left: false, right: false },
  default_flow_id: 1,
  widgets: [
    { id: 'child_verdict', type: 'verdict', cell: 'main', props: {}, source: { flow_id: 1, kind: 'status' } },
  ],
  theme: {},
}

export const DASHBOARD_CHILD = { id: 2, name: 'Child station panel', is_default: false, owner_name: 'admin', updated_at: '2026-01-01T00:00:00Z', widget_count: 1, layout: DASHBOARD_CHILD_LAYOUT }

export const DL_PROJECT = {
  id: 1,
  name: 'Fast part',
  description: '',
  trainer_kind: 'ai_detect',
  classes: ['part'],
  params: {},
  last_asset_id: '',
  last_metrics: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  counts: { total: 2, unlabeled: 2, per_class: { part: 0 } },
}

export const DL_TRAINER = {
  kind: 'ai_detect',
  label: 'Object detection',
  description: 'Finds object boxes from labeled examples.',
  label_mode: 'shapes',
  tool_key: 'ai_detect',
  devices: ['cpu'],
  min_per_class: 1,
  params: [
    { key: 'model', label: 'Size', kind: 'select', required: false, default: 'n', help_text: '', options: [{ value: 'n', label: 'Nano' }], unit: '', minimum: null, maximum: null, step: null, visible_when: null, shapes: [], accept: '', group: '' },
    { key: 'epochs', label: 'Epochs', kind: 'number', required: false, default: 100, help_text: '', options: [], unit: '', minimum: 1, maximum: 2000, step: null, visible_when: null, shapes: [], accept: '', group: '' },
    { key: 'imgsz', label: 'Image size', kind: 'select', required: false, default: 640, help_text: '', options: [{ value: '320', label: '320' }, { value: '640', label: '640' }], unit: '', minimum: null, maximum: null, step: null, visible_when: null, shapes: [], accept: '', group: '' },
  ],
}

export const DL_SAMPLES = [
  { id: 's1', label: '', labeled_by: '', score: 0, width: 320, height: 240, created_at: '2026-01-01T00:00:00Z', shapes: [], split: '' },
  { id: 's2', label: '', labeled_by: '', score: 0, width: 320, height: 240, created_at: '2026-01-01T00:00:01Z', shapes: [], split: '' },
]

export const DASHBOARD_DATA = {
  generated_at: '2026-01-01T00:00:00Z',
  flows: {
    '1': {
      flow: { id: 1, name: 'demo', title: 'Line 1' },
      config: { title: 'Line 1', image: '', overlays: true, values: [{ key: 'width', unit: 'mm', low: 1, high: 2 }], variables: ['lot'], show_verdict: true, show_counts: true },
      run: { id: 'run-1', status: 'ok', verdict: 'OK', label: '', started_at: 1788500000, duration_ms: 13.5, trigger: 'ui', recipe: '', error: '', image: { ref: 'run-1:image', width: 640, height: 480 }, overlays: [] },
      values: [{ key: 'width', label: 'width', unit: 'mm', value: 1.5, text: '1.5', ok: true, present: true }],
      variables: { lot: 'A17' },
      counts: { date: '2026-09-08', total: 10, ok: 9, ng: 1, failed: 0, yield: 0.9 },
      stats: {},
    },
  },
  device: {
    station_id: 'ST01',
    version: '1.0.0',
    lock: { locked: false, holder: '', reason: '' },
    capacity: { active: 0, max_workers: 4, flows: [], images: { images: 0, bytes: 0, runs: 0, encoded: 0 } },
    flows_running: [],
  },
  variables: { station: { shift: 'day' } },
}

export function routes(path: string, body?: unknown): unknown {
  if (/\/vision\/inspect\/\d+\/last-trial$/.test(path)) return { trial: null, saved: true }
  if (path === '/vision/composite-tools') return body ? { ...COMPOSITE_TOOL, ...(body as object), id: 8 } : { items: [COMPOSITE_TOOL] }
  if (/\/vision\/composite-tools\/\d+\/usage$/.test(path)) return { flows: [{ id: 1, name: '示範流程', count: 1 }], tools: [] }
  if (/\/vision\/composite-tools\/\d+$/.test(path)) return { ...COMPOSITE_TOOL, graph: { nodes: [], edges: [] } }
  if (path === '/vision/notes') return body ? { ...ENGINEERING_NOTE, ...(body as object), status: 'draft' } : { items: [ENGINEERING_NOTE], total: 1 }
  if (/^\/vision\/notes\/\d+/.test(path)) return { ...ENGINEERING_NOTE, ...(body as object ?? {}), status: path.endsWith('/confirm') ? 'confirmed' : path.endsWith('/retract') ? 'retracted' : 'draft' }
  if (path.startsWith('/vision/inspect/')) return inspectMock(path, body)
  if (path === '/vision/flows/10') return { ...FLOW, id: 10, name: '空白流程', check_count: 0, graph: { nodes: [], edges: [] }, ...(body && typeof body === 'object' ? body : {}) }
  if (path === '/vision/flows/6') return { ...FLOW, id: 6, graph: INSPECT_GRAPH, ...(body && typeof body === 'object' ? body : {}) }
  if (path.startsWith('/auth/status')) return { setup_required: false }
  if (path.startsWith('/auth/me')) return ME
  if (path.startsWith('/vision/batch/sets/')) return { id: 1, flow_id: 1, name: '影像集 A', source: 'upload', image_count: 0, size_bytes: 0, owner_id: 1, labeled: { ok: 0, ng: 0 }, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', images: [], can_manage: true, items: [], total: 0 }
  if (path.startsWith('/vision/batch/sets')) return { items: [], total: 0, max_images: 200, keep_sets: 10, keep_runs: 20 }
  if (path.startsWith('/vision/batch/runs')) return { id: 1, set_id: 1, flow_id: 1, flow_version: 1, label: '', note: '', origin: 'manual', status: 'done', progress: { done: 0, total: 0, stage: '' }, summary: {}, parent_id: null, owner_id: 1, recipe_name: '', meta: {}, error: '', created_at: '2026-01-01T00:00:00Z', finished_at: null, duration_s: 0, items: [], graph: { nodes: [], edges: [] }, ready: true, labeled: 0, match: 0, match_rate: null, confusion: { tp: 0, fp: 0, tn: 0, fn: 0 }, mismatches: [], error_nodes: [], slowest: [], node_time: [], outputs: [], judges: [], vs_parent: null, text: [], suggestions: [] }
  if (path.startsWith('/vision/agent/consult')) return { answer: '', provider: 'rules', suggestions: [], warnings: [] }
  if (path.startsWith('/vision/agent/memory')) return { facts: [{ id: 1, kind: 'fact', text: '產線 3 用流程「檢測 A」', answer: '', rating: 0, created_at: null }], qa: [{ id: 2, kind: 'qa', text: '如何建立影像來源？', answer: '到來源庫', rating: 1, created_at: null }], limits: { facts: 50, qa: 200 } }
  if (path.startsWith('/vision/agent/chat')) return { kind: 'help', answer: '依平台文件：到「批次測試」頁按「新增影像集」。', provider: 'rules', sources: [{ title: '使用者手冊 › 批次測試頁', page: 'user-guide.html', heading: '批次測試頁', url: '/docs/user-guide.html#batch', snippet: '選擇流程後按「新增影像集」', kind: 'doc' }], warnings: [] }
  if (path.startsWith('/vision/agent/help/search')) return { items: [], sections: 0, pages: 0, tools: 0 }
  if (path.startsWith('/vision/teach/params')) return { items: STATION_TEACH_ROWS, total: STATION_TEACH_ROWS.length, flow_count: 2 }
  if (path.startsWith('/vision/teach/groups')) return {
    items: [{ id: 'g1', name: 'Daily checks', items: [{ valid: true, flow_id: 1, node_id: 'thr', param: 'threshold', resolved: STATION_TEACH_ROWS[0] }, { valid: false, flow_id: 9, node_id: 'gone', param: 'threshold', reason: 'missing' }], count: 2 }],
    limit: 32,
  }
  if (/\/vision\/flows\/\d+\/spc/.test(path)) return { flow_id: 1, output: 'diameter', outputs: ['diameter'], hours: 24, chart: 'imr', subgroup: 5, enabled: true, retention_days: 365, series: [{ ts: '2026-01-01T00:00:00Z', value: 12.01, run_id: 'a' }, { ts: '2026-01-01T00:00:10Z', value: 12.02, run_id: 'b' }, { ts: '2026-01-01T00:00:20Z', value: 11.99, run_id: 'c' }], analysis: { limits: { chart: 'imr', n: 3, cl: 12.0067, ucl: 12.06, lcl: 11.95, sigma: 0.0177, mr_bar: 0.02, mr_ucl: 0.065 }, capability: { usl: 12.05, lsl: 11.95, cp: 0.94, cpk: 0.8, cpu: 0.8, cpl: 1.07, out_of_spec: 0 }, rules: {}, rule_names: {}, flagged: [], summary: { n: 3, mean: 12.0067, std: 0.0153, min: 11.99, max: 12.02 } }, spec: { usl: 12.05, lsl: 11.95, nominal: 12, unit: 'mm' }, alerts: [] }
  if (path.startsWith('/vision/spc/alerts')) return { items: [], cached: false }
  if (path.startsWith('/vision/summary')) return { station_id: 'ST01', version: '1.0.0', hours: 24, locked: false, totals: { total: 0, ok: 0, ng: 0, failed: 0, yield: null }, flows: [] }
  if (path.startsWith('/vision/audit')) return { items: [{ id: 1, at: '2026-01-01T00:00:00Z', actor: 'admin', actor_kind: 'user', action: 'flow.update', target_type: 'flow', target_id: '1', target_name: '示範流程', summary: 'threshold 60 → 46', detail: {}, ip: '127.0.0.1' }], total: 1, limit: 50, offset: 0, actions: ['flow.update'], actors: ['admin'] }
  if (/\/vision\/flows\/3$/.test(path)) return FLOW_GROUPED
  if (/\/vision\/flows\/77$/.test(path)) return FLOW_TOOL
  if (path === '/vision/dashboards') return { items: [DASHBOARD, DASHBOARD_CHILD] }
  if (path === '/vision/dashboards/default') return DASHBOARD
  if (/\/vision\/dashboards\/\d+\/data$/.test(path)) return DASHBOARD_DATA
  if (path === '/vision/dashboards/2') return DASHBOARD_CHILD
  if (/\/vision\/dashboards\/\d+$/.test(path)) return DASHBOARD
  if (/\/vision\/flows\/\d+\/teach-contour$/.test(path)) return { model: { version: 1, image_size: [640, 480], closed: true, points: [[10, 10], [30, 10], [30, 30], [10, 30]] }, points: [[10, 10], [30, 10], [30, 30], [10, 30]] }
  if (/\/vision\/flows\/\d+\/preview$/.test(path)) return { ...RUNS[0], id: 'preview-1', persisted: false }
  if (/\/vision\/flows\/\d+\/diff$/.test(path)) return { summary: 'threshold 60 → 70', diff: { params: [{ node: 'thr', param: 'threshold', before: 60, after: 70 }], count: 1 } }
  if (/\/vision\/flows\/\d+$/.test(path)) {
    const patch = typeof body === 'object' && body ? body as Record<string, unknown> : {}
    return { ...FLOW, ...patch, id: 1, version: 2, updated_at: '2026-01-01T00:00:01Z', graph: (patch.graph as typeof FLOW.graph | undefined) ?? FLOW.graph }
  }
  if (/\/vision\/flows\/\d+\/versions/.test(path)) return { items: [], current: 1, keep: 50 }
  if (/\/vision\/flows\/\d+\/recipes/.test(path)) return { items: [] }
  if (/\/vision\/flows\/\d+\/recent/.test(path)) return { items: [] }
  if (/\/vision\/flows\/\d+\/runs/.test(path)) return { items: RUNS, total: RUNS.length, limit: 20, offset: 0 }
  if (/\/vision\/flows\/\d+\/stats/.test(path)) return { hours: 24, total: 8, by_status: { ok: 7, ng: 1 }, avg_ms: 12, max_ms: 30, hourly: [], live: { runs: 0, ok: 0, ng: 0, failed: 0, avg_ms: 0, max_ms: 0, last_ms: 0, last_status: '', last_run_id: '', last_finished_at: 0 } }
  if (path.startsWith('/vision/flows')) return { items: [FLOW, FLOW_SIDE, FLOW_BARE], total: 3, limit: 100, offset: 0 }
  if (path.startsWith('/vision/tool-types')) return { items: [
    { key: 'image_source', label: 'Image source', description: 'Acquire image', category: 'source', category_label: 'Source', icon: 'Camera', params: [{ key: 'source_id', label: 'Source', kind: 'source', required: false, default: null, help_text: '', options: [], unit: '', minimum: null, maximum: null, step: null, visible_when: null, shapes: [], accept: '', group: '' }], inputs: [], outputs: [{ key: 'image', label: 'Image', type: 'image' }], heavy: false },
    { key: 'threshold', label: 'Threshold', description: 'Binary threshold', category: 'preprocess', category_label: 'Pre-processing', icon: 'SlidersHorizontal', params: [TEACH_PARAM], inputs: [{ key: 'image', label: 'Image', type: 'image' }], outputs: [{ key: 'image', label: 'Image', type: 'image' }], heavy: false },
    { key: 'grayscale', label: '灰階', description: '轉灰階', category: 'preprocess', category_label: '影像前處理', icon: 'Box', params: [], inputs: [{ key: 'image', label: '影像', type: 'image' }], outputs: [{ key: 'image', label: '影像', type: 'image' }], heavy: false },
    { key: 'blob', label: 'Find objects', description: 'Find connected objects', category: 'detect', category_label: 'Detection', icon: 'ScanSearch', params: [], inputs: [{ key: 'image', label: 'Image', type: 'image' }], outputs: [{ key: 'count', label: 'Count', type: 'number' }, { key: 'image', label: 'Image', type: 'image' }], heavy: false },
    { key: 'in_range', label: 'Check range', description: 'Check a numeric range', category: 'logic', category_label: 'Logic', icon: 'BetweenHorizontalStart', params: [], inputs: [{ key: 'value', label: 'Value', type: 'number' }], outputs: [{ key: 'pass', label: 'Pass', type: 'flow' }, { key: 'fail', label: 'Fail', type: 'flow' }], heavy: false },
  ], categories: [{ key: 'source', label: 'Source' }, { key: 'preprocess', label: '影像前處理' }] }
  if (path.startsWith('/vision/capture/download/info')) return { available: false, version: '', filename: '', size: 0, sha256: '', built_at: null, url: '/api/vision/capture/download' }
  if (path.startsWith('/vision/capture/clients')) return { listening: true, host: '0.0.0.0', port: 9100, items: [{ name: 'line-pc', address: '127.0.0.1:50000', version: '0.1.0', hostname: 'LINE-PC', connected_at: '2026-01-01T00:00:00', local: true, prefer_encoding: 'raw', shm: true, channels: [{ id: 'cam1', label: '產線相機 1', driver: 'basler', index: 0, width: 1280, height: 960, channels: 1, dtype: 'u8', pixel_format: 'Mono8', roi: { x: 0, y: 0, w: 1280, h: 960 }, full: { w: 1280, h: 960 }, mode: 'on_demand', enabled: true, streaming: false, seq: 12, last_frame_age_ms: 120, encoding: 'shm', shm: true, last_error: '', in_use_by: [], fps: 9.5, bytes_per_s: 0, frames: 12 }] }] }
  if (path.startsWith('/vision/capture')) return {}
  if (path.startsWith('/vision/videos')) return { items: [{ name: 'line-pc/demo.avi', path: 'C:\\data\\videos\\line-pc\\demo.avi', size: 204800, duration_s: 2.5, source: 'line-pc', created_at: '2026-01-01T00:00:00Z' }] }
  if (path.startsWith('/vision/sources/kinds')) return { items: [{ kind: 'folder', label: '資料夾', fields: ['path'] }, { kind: 'capture', label: '擷取端相機', fields: ['client', 'channel', 'mode', 'timeout_ms', 'fresh', 'encoding'] }] }
  if (path.startsWith('/vision/sources')) return { items: [{ id: 1, name: '範例：圓孔量測', kind: 'folder', group: '範例', config: { path: 'x' }, status: { count: 2 }, is_enabled: true }, { id: 2, name: '產線相機', kind: 'capture', group: '', config: { client: 'old-pc', channel: 'cam1', mode: 'on_demand' }, status: { open: false, connected: false, last_error: '' }, is_enabled: true }] }
  if (path.startsWith('/vision/fs')) return { path: 'x', parent: null, dirs: [], files: ['a.png', 'b.png'] }
  if (/\/vision\/flows\/\d+\/board$/.test(path)) return { flow: { id: 1, name: 'demo', title: 'Line 1' }, config: { title: 'Line 1', image: '', overlays: true, values: [{ key: 'width', unit: 'mm', low: 1, high: 2 }], variables: [], show_verdict: true, show_counts: true }, run: null, values: [{ key: 'width', label: 'width', unit: 'mm', value: null, text: '', ok: null, present: false }], variables: { lot: 'A17' }, counts: { date: '2026-09-06', total: 10, ok: 9, ng: 1, failed: 0, yield: 90 }, stats: {} }
  if (/\/vision\/flows\/\d+\/variables$/.test(path)) return { flow_id: 1, items: { parts: 12, lot: 'A17' }, station: { shift: 'day' } }
  if (path.startsWith('/vision/variables')) return { items: { shift: 'day' } }
  if (path === '/vision/queues') return { items: [{ name: 'parts', size: 2, oldest_age_ms: 120, dropped: 0 }] }
  if (path === '/vision/fixed-images/from-ref') return { id: 'fixed-crop', name: 'Crop', width: 32, height: 24, channels: 3, size: 128 }
  if (path.startsWith('/vision/fixed-images')) return { items: [{ id: 'fixed-1', name: 'Reference' }], count: 1, bytes: 128, orphans: [] }
  if (path.startsWith('/vision/calibration/robot/signals')) {
    return {
      items: [{ seq: 1, kind: 'point', x: 12, y: 34, r: 90, ts: 1788500000, source: 'Calibration(12,34,90)' }],
      last_seq: 1,
    }
  }
  if (path.startsWith('/vision/calibration/capture')) return { ref: 'cal:capture:image', width: 640, height: 480, name: 'shot.png' }
  if (path.startsWith('/vision/calibration/detect')) return { found: true, count: 54, corners: [[10, 10], [20, 10]], overlays: [{ kind: 'points', points: [[10, 10], [20, 10]] }] }
  if (path.startsWith('/vision/calibration/stereo/import')) return {
    payload: {
      unit: 'mm',
      image_size: [640, 480],
      stereo: {
        left_source: 'left',
        right_source: 'right',
        M1: [[1200, 0, 320], [0, 1200, 240], [0, 0, 1]],
        D1: [0, 0, 0, 0, 0],
        M2: [[1200, 0, 320], [0, 1200, 240], [0, 0, 1]],
        D2: [0, 0, 0, 0, 0],
        R: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        T: [-60, 0, 0],
        image_size: [640, 480],
        rms: 0.1,
        baseline_mm: 60,
        points: [{ index: 0, error: 0.05 }],
      },
    },
    summary: 'stereo baseline 60.000 mm, rms 0.100 px',
    quality: { stereo: 'good' },
  }
  if (path.startsWith('/vision/calibration/stereo/reference')) return {
    payload: { unit: 'mm', image_size: [640, 480], stereo: { rms: 0.1, baseline_mm: 60, points: [], z_ref: { d0_mm: 800, Z0_mm: 100, scale: 1 } } },
    summary: 'stereo baseline 60.000 mm, rms 0.100 px, z reference set',
    quality: { stereo: 'good' },
  }
  if (path.startsWith('/vision/calibration/solve')) {
    const mode = typeof body === 'object' && body ? (body as { mode?: unknown }).mode : ''
    if (mode === 'stereo') {
      return {
        payload: { unit: 'mm', image_size: [640, 480], stereo: { rms: 0.1, baseline_mm: 60, points: [{ index: 0, error: 0.05 }, { index: 1, error: 0.04 }, { index: 2, error: 0.03 }, { index: 3, error: 0.03 }, { index: 4, error: 0.04 }] } },
        summary: 'stereo baseline 60.000 mm, rms 0.100 px',
        quality: { stereo: 'good' },
      }
    }
    if (mode === 'mapping') {
      return {
        payload: {
          unit: 'mm',
          image_size: [640, 480],
          mapping: {
            kind: 'affine',
            matrix: [[1, 0, 30], [0, 1, -20], [0, 0, 1]],
            points: [
              { ax: 10, ay: 20, bx: 40, by: 0, error: 0.01 },
              { ax: 80, ay: 20, bx: 110, by: 0, error: 0.02 },
              { ax: 10, ay: 90, bx: 40, by: 70, error: 0.01 },
            ],
            rms: 0.01,
            max_error: 0.02,
          },
        },
        summary: 'camera affine 0.010 px rms',
        quality: { mapping: 'good' },
      }
    }
    return { payload: { unit: 'mm', image_size: [640, 480], world: { kind: 'perspective', matrix: [[0.05, 0, 0], [0, 0.05, 0], [0, 0, 1]], mm_per_px: 0.05, rms: 0.01, max_error: 0.02, points: [] } }, summary: 'perspective 0.05000 mm/px', quality: { world: 'good' } }
  }
  if (path.startsWith('/vision/calibration')) return { items: [] }
  if (path.startsWith('/vision/assets')) return { items: [] }
  if (path.startsWith('/vision/groups')) return { items: [{ id: 1, kind: 'source', name: '範例' }] }
  if (path.startsWith('/vision/agent/chats')) return { items: [], limits: { chats: 50, messages: 60 } }
  if (path.startsWith('/vision/retention')) {
    const settings = { run_days: 365, audit_days: 365, measurement_days: 365, archive_days: 90, archive_max_gb: 20, backup_keep: 10, window_hour: 3, vacuum: true, enabled: true }
    return {
      settings, defaults: settings, last_sweep_at: null, last_deep_at: null, last_result: {}, busy: false,
      usage: { db_bytes: 1048576, archive_files: 0, archive_bytes: 0, backup_files: 0, backup_bytes: 0, runs: 0, audit: 0, measurements: 0 },
    }
  }
  // 內建範本：畫廊預設用範例圖片（has_samples），instantiate 回帶圖的固定影像節點
  if (/\/vision\/templates\/[^/]+\/instantiate/.test(path)) return { graph: { nodes: [{ id: 'src', type: 'fixed_image', params: { images: [{ id: 'abc', name: 'sample 01.png', width: 8, height: 6, size: 99 }], role: 'acquire', mode: 'cycle' } }], edges: [] }, missing_source: false, used_samples: true, name: '孔數檢測', description: '' }
  if (path.startsWith('/vision/templates')) return { items: [{ id: 'builtin:hole_count', name: '孔數檢測', description: '灰階、二值化、blob 計數', category: 'count', source: 'builtin', node_count: 8, graph: { nodes: [{ id: 'src', type: 'image_source', params: {} }], edges: [] }, owner_name: '', created_at: null, has_samples: true }], can_manage: true }
  if (path.startsWith('/vision/capacity')) return { active: 0, max_workers: 4, flows: [], images: { images: 0, bytes: 0, runs: 0, encoded: 0 }, queue: {} }
  if (path.startsWith('/vision/agent/info')) return { provider: 'offline', model: '', llm: false, has_key: false, key_hint: '', source: 'none', mode: 'single', reason: '', providers: [{ value: 'offline', label: '離線規則引擎', default_model: '' }] }
  if (path.startsWith('/vision/agent/jobs')) return { items: [] }
  if (path.startsWith('/vision/agent/sessions')) return { items: [], total: 0 }
  if (path.startsWith('/vision/agent/skills/custom')) return { items: [] }
  if (path.startsWith('/vision/agent/clarify')) return { ready: true, questions: [], summary: '', intent: 'count', provider: 'rules' }
  if (path.startsWith('/vision/agent/run')) return { graph: { nodes: [], edges: [] }, report: { id: 'r', status: 'ok', outputs: {}, nodes: {}, duration_ms: 1 }, reports: [], main_image: 0 }
  if (path.startsWith('/vision/agent/autotune')) return { graph: { nodes: [], edges: [] }, rationale: '', provider: 'autotune', changes: [], before: { ok: 0, ng: 0, failed: 0 }, after: null, items: [], applied: false }
  if (path.startsWith('/vision/agent/skills')) return { items: [{ key: 'platform', label: '平台規則', category: 'guide', curated: true }] }
  if (/\/vision\/dl\/projects\/\d+\/quick-register$/.test(path)) return { job_id: 'job123', labeled: 2, skipped: 0, params: { model: 'n', epochs: 20, imgsz: 320, batch: 4 } }
  if (/\/vision\/dl\/projects\/\d+\/video-extract\/status$/.test(path)) return { job: null }
  if (/\/vision\/dl\/projects\/\d+\/video-extract\/stop$/.test(path)) return { stopped: true }
  if (/\/vision\/dl\/projects\/\d+\/video-extract$/.test(path)) return { id: 'video-job', project_id: 1, video_path: 'demo.avi', status: 'running', progress: 0.1, stage: 'running', frame: 1, total_frames: 10, saved: 0, duplicates: 0, per_class: {}, recent: [], logs: [], log_from: 0, log_next: 0, error: '' }
  if (/\/vision\/dl\/projects\/\d+\/samples$/.test(path)) return { items: DL_SAMPLES }
  if (/\/vision\/dl\/projects\/\d+\/versions$/.test(path)) return { items: [] }
  if (/\/vision\/dl\/projects\/\d+\/models$/.test(path)) return { items: [] }
  if (/\/vision\/dl\/projects\/\d+\/corrections$/.test(path)) return { sample: DL_SAMPLES[0], holdout: false }
  if (/\/vision\/dl\/projects\/\d+$/.test(path)) return DL_PROJECT
  if (path.startsWith('/vision/dl/projects')) return { items: [DL_PROJECT] }
  if (path.startsWith('/vision/dl/trainers')) return { items: [DL_TRAINER] }
  if (path.startsWith('/vision/dl/train/status')) return { job: null }
  if (path.startsWith('/vision/dl/devices')) return { available: ['cpu'], preferred: ['cpu'], train_device: 'cpu', accelerators: [], gpus: [], providers: ['CPUExecutionProvider'] }
  if (path.startsWith('/vision/integration/rules')) return { items: [{ id: 'r1', name: '', enabled: true, source: 'text', address: '', mode: 'rising', value: 0, value2: 0, match: 'prefix', pattern: 'SCAN ', capture: 'lot', action: 'run_flow', flow: 'demo', node: '', param: '', recipe: '', variable: '', scope: 'flow', set_value: '', signal_kind: 'point', args: {}, reason: '', ttl: 0, clear: false, done: '', reply: '' }] }
  if (path.startsWith('/vision/integration/trace')) return { items: [{ seq: 1, ts: 1788500000, channel: 'tcp', direction: 'in', name: '127.0.0.1:5000', summary: 'RUN 1', ok: true, ms: 3.2, detail: { ok: true } }], seq: 1, channels: { http: 0, tcp: 1, modbus: 0, capture: 0 }, keep: 300, watching: true }
  if (path.startsWith('/vision/integration/info')) return { http_base: 'http://127.0.0.1:8000/api', host: '127.0.0.1', http_port: 8000, tcp_host: '0.0.0.0', tcp_port: 9000, tcp_listening: true, api_key_required: false, max_workers: 4, run_timeout_s: 30, commands: ['RUN <flow> [k=v ...]', 'TRIGGER <flow>', 'STATUS [flow]', 'LIST', 'PING'], capture_host: '0.0.0.0', capture_port: 9100, capture_listening: true, capture_download_url: '/api/vision/capture/download' }
  if (path.startsWith('/openapi.json')) return { openapi: '3.1.0', info: { title: 'VisionSequence API', version: '1.0' }, paths: {
    '/api/vision/flows/{flow_id}/run': { post: { summary: 'Run Flow', tags: ['vision'], parameters: [{ name: 'flow_id', in: 'path', required: true, schema: { type: 'integer' } }, { name: 'wait', in: 'query', schema: { type: 'boolean', default: true } }], requestBody: { content: { 'multipart/form-data': { schema: { properties: { image: { anyOf: [{ type: 'string', format: 'binary' }, { type: 'null' }] }, context: { anyOf: [{ type: 'string' }, { type: 'null' }] } } } } } }, responses: { '200': { description: 'OK' } } } },
    '/api/vision/lock': { get: { summary: 'Get Lock', tags: ['lock'], responses: { '200': { description: 'OK' } } }, post: { summary: 'Acquire Lock', tags: ['lock'], requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/LockIn' } } } }, responses: { '200': { description: 'OK' } } } },
    '/api/auth/me': { get: { summary: 'Me', tags: ['auth'], responses: { '200': { description: 'OK' } } } },
  }, components: { schemas: { LockIn: { type: 'object', properties: { reason: { type: 'string', default: '' }, ttl_s: { anyOf: [{ type: 'integer' }, { type: 'null' }] } } } } } }
  if (path.startsWith('/vision/plugins')) return { dir: 'D:/vs/plugins', docs_url: '/docs/plugins.html', mounted: [], items: [
    { name: 'example_dark_ratio.py', path: 'D:/vs/plugins/example_dark_ratio.py', kind: 'file', status: 'ok', error: '', mounted: ['tool:dark_ratio'], requirements: false, loaded_at: 1 },
    { name: 'broken.py', path: 'D:/vs/plugins/broken.py', kind: 'file', status: 'error', error: "Missing package 'foo'", mounted: [], requirements: true, loaded_at: 1 },
  ] }
  if (path.startsWith('/vision/connections')) return { items: [] }
  if (path.startsWith('/vision/lock')) return { locked: false, holder: '', reason: '', expires_at: null }
  if (path.startsWith('/users/permissions')) return {
    features: [{ key: 'flows.run', default: { engineer: true, operator: true } }, { key: 'flows.edit', default: { engineer: true, operator: false } }, { key: 'dl', default: { engineer: true, operator: false } }],
    matrix: { engineer: ['flows.run', 'flows.edit', 'dl'], operator: ['flows.run'] },
    roles: ['engineer', 'operator'],
  }
  if (path.startsWith('/users')) return { items: [{ id: 1, username: 'admin', display_name: '管理員', is_staff: true, is_active: true, role: 'admin', last_login: '2026-01-01T00:00:00Z' }], roles: ['admin', 'engineer', 'operator'] }
  return {}
}

export function installApiMock() {
  vi.mock('@/lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/lib/api')>()
    return {
      ...actual,
      request: vi.fn(async (path: string, options?: { body?: unknown }) => routes(path, options?.body)),
      api: {
        get: vi.fn(async (path: string) => routes(path)),
        post: vi.fn(async (path: string, body?: unknown) => routes(path, body)),
        postForm: vi.fn(async (path: string) => routes(path)),
        put: vi.fn(async (path: string) => routes(path)),
        patch: vi.fn(async (path: string, body?: unknown) => routes(path, body)),
        delete: vi.fn(async () => undefined),
      },
      authToken: () => 'test-token',
      apiKey: () => '',
    }
  })
}
export const ENGINEERING_NOTE = { id: 1, title: 'Diffuse light for polished cups', body: 'A diffuser reduces reflections near the rim.', project: 'Cup inspection', part_number: 'CUP-01', flow: 1, flow_name: 'Cup inspection', recipe: null, source: null,
  kind: 'lighting', status: 'draft', owner: 2, owner_name: 'engineer', confirmed_by: null, confirmed_by_name: '', confirmed_at: null, supersedes: null, replacement: null,
  conditions: { material: 'Polished steel' }, applies_from_version: 1, applies_to_version: null, images: [], runs: [], created_at: '2026-09-11T00:00:00Z', updated_at: '2026-09-11T00:00:00Z', can_confirm: true }
