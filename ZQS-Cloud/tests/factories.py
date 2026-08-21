"""Minimal object builders for the test suite."""

from __future__ import annotations

import itertools

from apps.accounts.models import Membership, Organization, Role, User
from apps.devices.models import Device, DeviceType, Site
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


def device(
    org: Organization,
    device_id: str = "",
    *,
    site_obj: Site | None = None,
    policy: RecordingPolicy | None = None,
    device_type: DeviceType | None = None,
    **kwargs,
) -> Device:
    device_id = device_id or f"DEV-{next(_counter):05d}"
    return Device.objects.create(
        organization=org,
        device_id=device_id,
        name=kwargs.pop("name", device_id),
        site=site_obj,
        device_type=device_type,
        recording_policy=policy,
        **kwargs,
    )
