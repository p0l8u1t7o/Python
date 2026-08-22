"""Minimal object builders for the test suite."""

from __future__ import annotations

import itertools

from apps.accounts.models import Membership, Organization, Role, User
from apps.devices.models import Device, DeviceType, EdgeNode, Site
from apps.telemetry.models import RecordingPolicy

_counter = itertools.count(1)


def organization(slug: str = "acme", **kwargs) -> Organization:
    return Organization.objects.create(
        name=kwargs.pop("name", slug.title()), slug=slug, **kwargs
    )


def user(email: str = "", password: str = "TestPassw0rd!23", **kwargs) -> User:
    email = email or f"user{next(_counter)}@example.com"
    return User.objects.create_user(email=email, password=password, **kwargs)


def member(org: Organization, role: str = Role.ADMIN, **kwargs) -> tuple[User, Membership]:
    account = user(**kwargs)
    membership = Membership.objects.create(organization=org, user=account, role=role)
    return account, membership


def site(org: Organization, code: str = "hq", **kwargs) -> Site:
    return Site.objects.create(
        organization=org,
        code=code,
        name=kwargs.pop("name", code.upper()),
        latitude=kwargs.pop("latitude", 25.0),
        longitude=kwargs.pop("longitude", 121.5),
        **kwargs,
    )


def blueprint(key: str = "test-bess", org: Organization | None = None, **kwargs) -> DeviceType:
    return DeviceType.objects.create(
        organization=org,
        key=key,
        name=kwargs.pop("name", key),
        command_definitions=kwargs.pop(
            "command_definitions",
            [
                {
                    "name": "set_power_limit",
                    "min_role": Role.OPERATOR,
                    "params": {
                        "type": "object",
                        "required": ["limit_w"],
                        "properties": {
                            "limit_w": {"type": "number", "minimum": 0, "maximum": 1000}
                        },
                    },
                }
            ],
        ),
        **kwargs,
    )


def edge_node(
    org: Organization, node_id: str = "", *, site: Site | None = None, **kwargs
) -> EdgeNode:
    node_id = node_id or f"NODE-{next(_counter):05d}"
    return EdgeNode.objects.create(
        organization=org,
        node_id=node_id,
        name=kwargs.pop("name", node_id),
        site=site,
        **kwargs,
    )


def device(
    org: Organization,
    device_id: str = "",
    *,
    site_obj: Site | None = None,
    policy: RecordingPolicy | None = None,
    device_type: DeviceType | None = None,
    node: EdgeNode | None = None,
    **kwargs,
) -> Device:
    """A device and, unless one is given, the edge node that carries it.

    Every device needs a node now. Defaulting to an implicit one keeps the
    hundreds of existing tests reading the way they did - they are about
    devices, not about connections - while the tests that care about gateways
    pass ``node`` explicitly.
    """
    device_id = device_id or f"DEV-{next(_counter):05d}"
    if node is None:
        node = EdgeNode.objects.create(
            organization=org,
            node_id=device_id,
            name=device_id,
            site=site_obj,
            is_implicit=True,
        )
    return Device.objects.create(
        organization=org,
        edge_node=node,
        device_id=device_id,
        name=kwargs.pop("name", device_id),
        site=site_obj,
        device_type=device_type,
        recording_policy=policy,
        **kwargs,
    )


def storage_plan(org, site_obj, name: str = "", **kwargs):
    """A named plan template bound to ``site_obj``."""
    from apps.ems.models import StoragePlan

    plan = StoragePlan.objects.create(
        organization=org,
        name=name or f"{site_obj.name} plan",
        **kwargs,
    )
    site_obj.storage_plan = plan
    site_obj.save(update_fields=["storage_plan"])
    return plan
