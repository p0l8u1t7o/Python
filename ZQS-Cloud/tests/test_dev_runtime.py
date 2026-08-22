"""The development runtime: bundled broker, combined pipeline, protocol choice.

These pin three things that were each silently broken and produced no error:

* ``Worker.start()`` logged through a reserved ``LogRecord`` field and died on
  the first line - so ``manage.py run_worker`` never consumed a message, and
  the only symptom was an empty database;
* ``Ingestor`` and ``Worker`` each build their own bus, which is right across
  processes and wrong inside one: two ``InMemoryBus`` objects are two
  unconnected queues, so a single-process pipeline moves nothing;
* the MQTT client hard-coded protocol 5, which the bundled broker refuses.
"""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from services.bus.factory import build_bus


class WorkerStartupTests(TestCase):
    def test_starting_the_worker_does_not_raise_on_its_own_log_line(self):
        """``name`` is reserved on LogRecord; passing it through ``extra``
        raised, and it was the first thing start() did."""
        from services.worker.main import Worker

        bus = build_bus("memory")
        worker = Worker(bus, name="test-worker")

        # Let it get past the log line, then stop it immediately.
        with mock.patch.object(Worker, "_consume_loop", return_value=None):
            worker.start()  # must not raise

    def test_the_worker_reports_its_name_under_a_safe_key(self):
        from services.worker.main import Worker

        bus = build_bus("memory")
        worker = Worker(bus, name="named-worker")

        with mock.patch.object(Worker, "_consume_loop", return_value=None), \
                self.assertLogs("zqs.worker", level="INFO") as captured:
            worker.start()

        record = next(r for r in captured.records if r.getMessage() == "worker starting")
        self.assertEqual(getattr(record, "worker", None), "named-worker")


class PipelineBusTests(TestCase):
    """One bus, or the two halves cannot see each other."""

    def test_the_two_services_default_to_separate_buses(self):
        """Correct across processes, and the reason the pipeline must inject."""
        from services.ingestor.main import Ingestor
        from services.worker.main import Worker

        with override_settings(BUS_BACKEND="memory"):
            self.assertIsNot(Ingestor().bus, Worker().bus)

    def test_an_injected_bus_is_shared(self):
        from services.ingestor.main import Ingestor
        from services.worker.main import Worker

        bus = build_bus("memory")
        self.assertIs(Ingestor(bus).bus, Worker(bus).bus)

    def test_a_message_published_by_one_is_visible_to_the_other(self):
        """The property the pipeline depends on, stated directly."""
        bus = build_bus("memory")
        bus.connect()
        bus.ensure_group(["telemetry"], "workers")
        bus.publish("telemetry", {"device_id": "X", "metrics": {}})

        received = bus.consume(["telemetry"], group="workers", consumer="c1", count=10)
        self.assertEqual(len(list(received)), 1)


class MqttProtocolTests(SimpleTestCase):
    """MQTT 5 by default; 3.1.1 where the broker only speaks that."""

    def _client(self, version):
        from services.mqtt.client import MqttClient

        config = {**self.settings_mqtt(), "PROTOCOL_VERSION": version}
        with override_settings(MQTT=config):
            return MqttClient(client_suffix="test")

    @staticmethod
    def settings_mqtt() -> dict:
        from django.conf import settings

        return dict(settings.MQTT)

    def test_the_default_is_mqtt_5(self):
        import paho.mqtt.client as mqtt

        client = self._client(5)
        self.assertTrue(client._v5)
        self.assertEqual(client._client._protocol, mqtt.MQTTv5)

    def test_311_is_selectable_for_the_bundled_broker(self):
        import paho.mqtt.client as mqtt

        client = self._client(311)
        self.assertFalse(client._v5)
        self.assertEqual(client._client._protocol, mqtt.MQTTv311)

    def test_connecting_under_311_omits_the_mqtt5_only_arguments(self):
        """paho rejects clean_start and CONNECT properties outside MQTT 5."""
        client = self._client(311)
        with mock.patch.object(client._client, "connect") as connect, \
                mock.patch.object(client._client, "loop_start"):
            client.connect(timeout=0.01)

        kwargs = connect.call_args.kwargs
        self.assertNotIn("clean_start", kwargs)
        self.assertNotIn("properties", kwargs)

    def test_connecting_under_5_still_sends_them(self):
        client = self._client(5)
        with mock.patch.object(client._client, "connect") as connect, \
                mock.patch.object(client._client, "loop_start"):
            client.connect(timeout=0.01)

        self.assertIn("clean_start", connect.call_args.kwargs)


class BundledBrokerTests(SimpleTestCase):
    """The command exists, is honest about what it is, and refuses cleanly."""

    def test_it_is_registered(self):
        from django.core.management import get_commands

        self.assertEqual(get_commands().get("run_broker"), "apps.core")
        self.assertEqual(get_commands().get("run_pipeline"), "apps.core")

    def test_a_missing_dependency_points_at_the_alternatives(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        real_import = __import__

        def without_amqtt(name, *args, **kwargs):
            if name.startswith("amqtt"):
                raise ImportError("no amqtt")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=without_amqtt):
            with self.assertRaises(CommandError) as caught:
                call_command("run_broker")

        message = str(caught.exception)
        self.assertIn("requirements-dev.txt", message)
        self.assertIn("emqx", message.lower())
