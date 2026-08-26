"""閘道器頁：NBIRTH 宣告的內容照原樣留下，設備可依閘道器篩選。"""

from __future__ import annotations

from django.test import TestCase

from apps.devices.models import EdgeNode
from services.sparkplug.datatypes import DataType
from services.sparkplug.topics import MessageType
from tests import factories
from tests.test_api import API, ApiTestCase
from tests.test_ingest_pipeline import PipelineTestCase


class BirthDeclarationTests(TestCase):
    publish = PipelineTestCase.publish
    drain = PipelineTestCase.drain
    next_seq = PipelineTestCase.next_seq

    def setUp(self) -> None:
        PipelineTestCase.setUp(self)

    def tearDown(self) -> None:
        PipelineTestCase.tearDown(self)

    def test_nbirth_metrics_are_kept_verbatim_on_the_node(self) -> None:
        self.publish(
            MessageType.NBIRTH,
            [
                ("bdSeq", 3, DataType.Int64),
                ("Node Control/Rebirth", False, DataType.Boolean),
                ("Properties/Firmware", "1.4.2", DataType.String),
            ],
        )
        self.drain()
        node = EdgeNode.objects.get(pk=self.node.pk)
        by_name = {m["name"]: m for m in node.birth_metrics}
        self.assertEqual(set(by_name), {"bdSeq", "Node Control/Rebirth", "Properties/Firmware"})
        self.assertEqual(by_name["bdSeq"]["datatype"], "Int64")
        self.assertEqual(by_name["bdSeq"]["value"], 3)
        self.assertEqual(by_name["Node Control/Rebirth"]["value"], False)
        self.assertEqual(node.bd_seq, 3)


class GatewayApiTests(ApiTestCase):
    def test_node_out_carries_declaration_and_devices_filter_by_gateway(self) -> None:
        admin = self.login("admin@acme-demo.com")
        node = factories.edge_node(self.org, "GW-PAGE-01")
        other = factories.edge_node(self.org, "GW-PAGE-02")
        EdgeNode.objects.filter(pk=node.pk).update(
            birth_metrics=[{"name": "bdSeq", "alias": None, "datatype": "Int64", "value": 0, "properties": {}}]
        )
        mine = factories.device(self.org, device_id="DEV-PAGE-A", node=node)
        factories.device(self.org, device_id="DEV-PAGE-B", node=other)

        detail = self.get(f"{API}/edge-nodes/{node.pk}", admin).json()
        self.assertEqual(detail["birth_metrics"][0]["name"], "bdSeq")

        rows = self.get(f"{API}/devices?edge_node_id={node.pk}", admin).json()["items"]
        self.assertEqual([r["id"] for r in rows], [str(mine.pk)])
