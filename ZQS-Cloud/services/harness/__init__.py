"""Device conformance harness.

A test fixture that accepts MQTT connections and judges them with the
platform's own rules, so a device author learns *why* a connection would be
refused rather than only that it was.

**Not a production broker.** See :mod:`services.harness.broker` for what it
deliberately does not emulate, and ``docs/device-test-harness.html`` for how to
use it.
"""
