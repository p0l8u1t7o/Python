"""A bundled MQTT broker, so the live path works without installing one.

**Development only.** It is here because the alternative was worse: without a
broker the console starts with live ingest dead and downlink commands
impossible, and the only fix on offer was "install Docker and pull EMQX" -
which is a large ask for someone who wants to look at the software.

What it is not:

* not clustered, not authenticated against ``EdgeNodeCredential``, and it does
  not call the EMQX auth/ACL webhooks - so it enforces **none** of the device
  identity model in ``deploy/emqx/README.md``;
* no shared subscriptions (``$share/...``), which is why the launcher sets
  ``MQTT_USE_SHARED_SUBSCRIPTION=0`` alongside it. That in turn means only one
  ingestor may run;
* no persistence, no bridging, no metrics.

Every one of those is a reason a real deployment runs EMQX. This exists so
that "does the telemetry arrive" can be answered on a laptop.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

#: amqtt logs every packet at DEBUG and every connection at INFO. At the
#: default level that buries the messages the developer is actually watching
#: for, so its loggers are quietened unless asked otherwise.
_NOISY_LOGGERS = ("amqtt", "amqtt.broker", "amqtt.client", "transitions")


class Command(BaseCommand):
    help = "Run a development MQTT broker. Not for production - use EMQX."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            default="",
            help="Bind address. Defaults to MQTT_HOST, which is 127.0.0.1.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=0,
            help="Bind port. Defaults to MQTT_PORT (1883).",
        )
        parser.add_argument(
            "--verbose-broker",
            action="store_true",
            help="Let amqtt log every connection and packet.",
        )

    def handle(self, *args, **options):
        try:
            from amqtt.broker import Broker
            from amqtt.contexts import BrokerConfig, ListenerConfig
        except ImportError as exc:  # pragma: no cover - depends on install
            raise CommandError(
                "The development broker needs 'amqtt'. Install it with:\n"
                "    pip install -r requirements-dev.txt\n"
                "Or run a real broker instead:\n"
                "    docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8"
            ) from exc

        host = options["host"] or settings.MQTT["HOST"]
        port = options["port"] or settings.MQTT["PORT"]

        if not options["verbose_broker"]:
            for name in _NOISY_LOGGERS:
                logging.getLogger(name).setLevel(logging.WARNING)

        # 連線偵錯：被 amqtt 在 CONNECT 就拒絕的連線只留 WARNING，接成 trace。
        from services.harness.amqtt_trace import install_log_bridge

        install_log_bridge()

        config = BrokerConfig(
            listeners={
                "default": ListenerConfig(
                    type="tcp", bind=f"{host}:{port}", max_connections=200
                )
            },
            # The $SYS topic tree is an EMQX-style diagnostic feed nothing here
            # subscribes to; publishing it every 20 s would only add noise to a
            # log somebody is reading to see their own telemetry.
            sys_interval=0,
            plugins={
                # Anonymous, deliberately. Device credentials are checked by
                # EMQX calling back into this platform; reimplementing that
                # here would be a second copy of the security model that could
                # disagree with the first.
                "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                    "allow_anonymous": True
                },
                # 連線偵錯：只在整合頁開啟偵錯時寫 IngressTrace，平常零成本。
                "services.harness.amqtt_trace.TracePlugin": {},
            },
        )

        self.stdout.write(
            self.style.WARNING(
                "development broker - anonymous, no ACL, no persistence.\n"
                "Device credentials are NOT enforced here. Use EMQX for anything real."
            )
        )
        self.stdout.write(f"listening on mqtt://{host}:{port}")

        # Built inside the coroutine: amqtt's Broker binds itself to the
        # running loop at construction, so creating it out here raises
        # "no running event loop".
        asyncio.run(self._serve(Broker, config, host, port))

    async def _serve(self, broker_cls, config, host: str, port: int) -> None:
        broker = broker_cls(config)
        try:
            await broker.start()
        except OSError as exc:
            raise CommandError(
                f"Could not bind {host}:{port} - is something already using it? ({exc})"
            ) from exc

        stopping = asyncio.Event()
        loop = asyncio.get_running_loop()

        # SIGBREAK is what Windows delivers to a process group; SIGTERM is what
        # Docker and POSIX supervisors send. add_signal_handler is unavailable
        # on the Windows proactor loop, hence the fallback.
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, stopping.set)
            except (NotImplementedError, AttributeError, ValueError):
                try:
                    signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stopping.set))
                except (OSError, ValueError):
                    pass

        try:
            await stopping.wait()
        finally:
            await broker.shutdown()
            self.stdout.write(self.style.SUCCESS("broker stopped"))
