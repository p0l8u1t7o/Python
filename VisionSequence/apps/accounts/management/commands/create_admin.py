"""建立（或重設密碼）管理員：manage.py create_admin admin --password xxx"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "建立管理員帳號；已存在則重設密碼並升為管理員"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(username=options["username"], defaults={"is_staff": True, "is_superuser": True})
        user.is_staff = user.is_superuser = user.is_active = True
        user.set_password(options["password"])
        user.save()
        self.stdout.write(self.style.SUCCESS(f"管理員 {user.username} {'已建立' if created else '已更新'}"))
