"""建立（或重設密碼）管理員。

    manage.py create_admin admin --password xxx
    manage.py create_admin admin --password-env VS_ADMIN_PASSWORD     （安裝腳本用：密碼不進命令列／歷史）
    echo xxx | manage.py create_admin admin --password-stdin
"""

from __future__ import annotations

import os
import sys

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "建立管理員帳號；已存在則重設密碼並升為管理員"

    def add_arguments(self, parser):
        parser.add_argument("username")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--password")
        group.add_argument("--password-env", metavar="NAME", help="從環境變數讀密碼（不會出現在程序清單）")
        group.add_argument("--password-stdin", action="store_true", help="從標準輸入讀一行密碼")

    def handle(self, *args, **options):
        if options["password_env"]:
            password = os.environ.get(options["password_env"], "")
            if not password:
                raise CommandError(f"Environment variable {options['password_env']} is empty")
        elif options["password_stdin"]:
            password = sys.stdin.readline().rstrip("\r\n")
            if not password:
                raise CommandError("No password on stdin")
        else:
            password = options["password"]
        if len(password) < 4:
            raise CommandError("The password is too short")
        user, created = User.objects.get_or_create(username=options["username"], defaults={"is_staff": True, "is_superuser": True})
        user.is_staff = user.is_superuser = user.is_active = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"管理員 {user.username} {'已建立' if created else '已更新'}"))
