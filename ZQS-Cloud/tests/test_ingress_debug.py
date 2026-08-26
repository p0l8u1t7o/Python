"""連線偵錯：只在開啟時記錄；拒收／未註冊／序號問題都留下可讀的一列；診斷說出卡在哪一步。"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.devices.models import EdgeNode, IngressDebug, IngressTrace
from services import diagnostics as diag
from services.sparkplug import payload as sp
from services.sparkplug.datatypes import DataType
from services.sparkplug.topics import MessageType
from tests import factories
from tests.test_api import API, ApiTestCase
from tests.test_ingest_pipeline import PipelineTestCase


def enable(org, minutes=30, node=""):
    IngressDebug.objects.update_or_create(
        organization=org, defaults={"enabled_until": timezone.now() + dt.timedelta(minutes=minutes), "node_filter": node},
    )
    diag.invalidate()


class TraceGateTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        diag.invalidate()

    def test_nothing_is_written_while_debug_is_off(self) -> None:
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=self.org.id, edge_node_id="GW-1")
        self.assertEqual(IngressTrace.objects.count(), 0)

    def test_enabled_org_records_and_filter_narrows_to_one_node(self) -> None:
        enable(self.org, node="GW-1")
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=self.org.id, edge_node_id="GW-1", raw=b"\x08\x00")
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=self.org.id, edge_node_id="GW-2")
        rows = list(IngressTrace.objects.all())
        self.assertEqual([r.edge_node_id for r in rows], ["GW-1"])
        self.assertEqual(rows[0].detail["hex"], "08 00", "payload preview captured")

    def test_unattributed_packets_are_kept_while_anyone_debugs(self) -> None:
        enable(self.org)
        diag.trace(diag.STAGE_BROKER, diag.OUTCOME_WARNING, edge_node_id="GW-LV-01", reason="connect")
        self.assertEqual(IngressTrace.objects.filter(organization__isnull=True).count(), 1)

    def test_expired_switch_stops_recording(self) -> None:
        enable(self.org, minutes=-1)
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=self.org.id)
        self.assertEqual(IngressTrace.objects.count(), 0)


class PipelineTraceTests(TestCase):
    publish = PipelineTestCase.publish
    drain = PipelineTestCase.drain
    next_seq = PipelineTestCase.next_seq

    def setUp(self) -> None:
        PipelineTestCase.setUp(self)
        enable(self.org)

    def tearDown(self) -> None:
        PipelineTestCase.tearDown(self)

    def test_garbage_payload_is_traced_as_rejected_with_a_hint(self) -> None:
        self.publish(MessageType.NBIRTH, raw=b"this is not protobuf")
        self.drain()
        row = IngressTrace.objects.filter(stage=diag.STAGE_INGEST, outcome=diag.OUTCOME_REJECTED).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.edge_node_id, self.node.node_id)
        self.assertEqual(row.kind, "NBIRTH")
        self.assertIn("hex", row.detail)

    def test_unknown_node_is_traced_with_the_group_and_node_it_used(self) -> None:
        message = sp.new_payload(timestamp=timezone.now(), seq=0)
        sp.add_metric(message, "bdSeq", 1, datatype=DataType.Int64)
        self.publish(MessageType.NBIRTH, raw=sp.encode(message), node_id="GW-NOBODY")
        self.drain()
        row = IngressTrace.objects.filter(reason="unknown_node").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.edge_node_id, "GW-NOBODY")
        self.assertEqual(row.group_id, self.org.slug)
        self.assertIsNone(row.organization_id)

    def test_good_birth_leaves_an_ok_trail_through_ingest_and_worker(self) -> None:
        self.publish(MessageType.NBIRTH, [("bdSeq", 0, DataType.Int64), ("Node Control/Rebirth", False, DataType.Boolean)])
        self.drain()
        reasons = list(IngressTrace.objects.order_by("id").values_list("stage", "reason"))
        self.assertIn((diag.STAGE_INGEST, "accepted"), reasons)
        self.assertIn((diag.STAGE_WORKER, "node_online"), reasons)

    def test_nbirth_with_nonzero_seq_is_called_out(self) -> None:
        self.publish(MessageType.NBIRTH, [("bdSeq", 0, DataType.Int64)], seq=5)
        self.drain()
        self.assertTrue(IngressTrace.objects.filter(reason="seq_birth_not_zero").exists())


class DebugApiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        diag.invalidate()
        self.node = factories.edge_node(self.org, "GW-LV-01")

    def test_enable_disable_and_status(self) -> None:
        admin = self.login("admin@acme-demo.com")
        viewer = self.login("view@acme-demo.com")
        self.assertFalse(self.get(f"{API}/integration/debug", viewer).json()["enabled"])
        r = self.call("put", f"{API}/integration/debug", admin, {"minutes": 15, "node_filter": "GW-LV-01"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["enabled"])
        self.assertEqual(r.json()["node_filter"], "GW-LV-01")
        self.assertEqual(self.call("put", f"{API}/integration/debug", viewer, {"minutes": 5}).status_code, 403)
        self.assertFalse(self.call("delete", f"{API}/integration/debug", admin).json()["enabled"])

    def test_traces_are_tenant_scoped_and_incremental(self) -> None:
        enable(self.org)
        enable(self.other_org)
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=self.org.id, edge_node_id="GW-LV-01", reason="a")
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=self.other_org.id, edge_node_id="GW-X", reason="b")
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_DROPPED, group_id=self.org.slug, edge_node_id="GW-LV-01", reason="unknown_node")
        admin = self.login("admin@acme-demo.com")
        rows = self.get(f"{API}/integration/debug/traces?node=GW-LV-01", admin).json()
        self.assertEqual([r["reason"] for r in rows], ["a", "unknown_node"])
        newer = self.get(f"{API}/integration/debug/traces?after_id={rows[0]['id']}", admin).json()
        self.assertEqual([r["reason"] for r in newer], ["unknown_node"])
        self.assertEqual(self.call("delete", f"{API}/integration/debug/traces", admin).status_code, 200)
        self.assertEqual(IngressTrace.objects.filter(organization=self.other_org).count(), 1, "other tenant untouched")

    def test_wrong_group_packets_for_my_node_are_visible_and_called_out(self) -> None:
        admin = self.login("admin@acme-demo.com")
        enable(self.org)
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_DROPPED, group_id="wrong-group", edge_node_id="GW-LV-01",
                   kind="NBIRTH", reason="unknown_node", message="no such node")
        rows = self.get(f"{API}/integration/debug/traces?node=GW-LV-01", admin).json()
        self.assertEqual([r["reason"] for r in rows], ["unknown_node"])
        d = self.get(f"{API}/integration/debug/diagnose/GW-LV-01", admin).json()
        self.assertTrue(any("wrong-group" in f["text"] for f in d["findings"]))

    def test_diagnosis_walks_the_protocol_steps(self) -> None:
        admin = self.login("admin@acme-demo.com")
        enable(self.org)
        # 1. 沒有任何封包
        d = self.get(f"{API}/integration/debug/diagnose/GW-LV-01", admin).json()
        self.assertEqual(d["verdict_level"], "error")
        self.assertIn("連線層", d["verdict"])
        # 2. 未註冊的節點
        d = self.get(f"{API}/integration/debug/diagnose/GW-NOBODY", admin).json()
        self.assertFalse(d["registered"])
        self.assertEqual(d["verdict"], "節點未註冊")
        # 3. 連上 broker 但沒有 NBIRTH
        diag.trace(diag.STAGE_BROKER, diag.OUTCOME_OK, edge_node_id="GW-LV-01", reason="connected")
        d = self.get(f"{API}/integration/debug/diagnose/GW-LV-01", admin).json()
        self.assertIn("NBIRTH", d["verdict"])
        # 4. 拒收
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_REJECTED, organization_id=self.org.id, edge_node_id="GW-LV-01",
                   kind="NBIRTH", reason="decode_error", message="bad protobuf")
        d = self.get(f"{API}/integration/debug/diagnose/GW-LV-01", admin).json()
        self.assertIn("拒收", d["verdict"])
        self.assertTrue(any("decode_error" in f["text"] for f in d["findings"]))
        # 5. 上線
        EdgeNode.objects.filter(pk=self.node.pk).update(status="online")
        IngressTrace.objects.all().delete()
        diag.trace(diag.STAGE_INGEST, diag.OUTCOME_OK, organization_id=self.org.id, edge_node_id="GW-LV-01", kind="NBIRTH", reason="accepted")
        d = self.get(f"{API}/integration/debug/diagnose/GW-LV-01", admin).json()
        self.assertEqual(d["verdict_level"], "ok")
