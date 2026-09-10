"""檢測任務定義表。"""

from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase

from apps.vision.tasks import all as all_tasks
from apps.vision.tasks import get


class TaskDefinitionTests(SimpleTestCase):
    def test_registry_exposes_eight_v1_definitions(self):
        kinds = {(d.kind, d.version) for d in all_tasks()}
        self.assertIn(("measure_diameter", 1), kinds)
        self.assertIn(("locate_part", 1), kinds)
        self.assertEqual(get("measure_diameter").pass_port.as_dict(), {"role": "tol", "port": "in_spec"})
        self.assertEqual(kinds, {(kind, 1) for kind in ("measure_diameter", "measure_distance", "locate_part", "count_objects", "check_presence", "inspect_circular_surface", "inspect_edge_defect", "read_and_verify")})

    def test_kind_payload_is_form_driven(self):
        diameter = get("measure_diameter").as_dict()
        field_keys = {f["key"] for f in diameter["fields"]}
        self.assertTrue({"roi", "edge", "nominal", "upper_tol", "lower_tol", "unit", "result_name", "required"} <= field_keys)
        self.assertTrue(all(f["label"] and f["help_text"] is not None for f in diameter["fields"]))

    def test_core_task_layer_does_not_import_agent(self):
        for rel in (*Path("apps/vision/tasks").glob("*.py"), Path("apps/vision/inspect.py")):
            tree = ast.parse(Path(rel).read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports += [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse([name for name in imports if name.startswith("apps.vision.agent")], rel)
