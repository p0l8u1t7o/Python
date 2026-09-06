"""助手對話：建立／列出／載入／覆寫／刪除、只看得到自己的、上限淘汰。"""

from __future__ import annotations

import json

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import AuthToken
from apps.vision.agent import chats
from apps.vision.models import AssistantChat


def msg(role: str, text: str) -> dict:
    return {"id": f"{role}-{text}", "role": role, "text": text, "at": 1}


class ChatStoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("kate", password="x")

    def test_title_comes_from_the_first_question(self):
        row = chats.create(self.user, [msg("assistant", "您好"), msg("user", "怎麼建立流程？"), msg("user", "第二句")])
        self.assertEqual(row.title, "怎麼建立流程？")
        self.assertEqual(len(row.messages), 3)

    def test_messages_are_capped_and_cleaned(self):
        row = chats.create(self.user, [*(msg("user", str(i)) for i in range(chats.MAX_MESSAGES + 10)), {"role": "nonsense"}, "junk"])
        self.assertEqual(len(row.messages), chats.MAX_MESSAGES)
        self.assertEqual(row.messages[-1]["text"], str(chats.MAX_MESSAGES + 9))

    def test_huge_messages_drop_the_oldest(self):
        big = [msg("user", "x" * (chats.MAX_BYTES + 1000)), msg("user", "小的")]
        row = chats.create(self.user, big)
        self.assertEqual([m["text"] for m in row.messages], ["小的"])

    def test_prune_keeps_the_newest(self):
        for i in range(chats.MAX_CHATS + 3):
            chats.create(self.user, [msg("user", f"q{i}")])
        self.assertEqual(AssistantChat.objects.filter(owner=self.user).count(), chats.MAX_CHATS)
        self.assertEqual(AssistantChat.objects.filter(owner=self.user).first().title, f"q{chats.MAX_CHATS + 2}")


class ChatApiTests(TestCase):
    def _token(self, username: str = "admin") -> str:
        if not User.objects.exists():
            r = self.client.post("/api/auth/setup", data=json.dumps({"username": username, "password": "Admin12345"}), content_type="application/json")
            self.assertIn(r.status_code, (200, 201), r.content)
            return r.json()["token"]
        return AuthToken.issue(User.objects.create_user(username, password="Passw0rd!"))

    def test_round_trip(self):
        head = {"HTTP_AUTHORIZATION": f"Bearer {self._token()}"}
        r = self.client.get("/api/vision/agent/chats", **head)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["items"], [])
        self.assertEqual(r.json()["limits"]["messages"], chats.MAX_MESSAGES)

        r = self.client.post("/api/vision/agent/chats", data=json.dumps({"messages": [msg("user", "怎麼標定？")]}),
                             content_type="application/json", **head)
        self.assertEqual(r.status_code, 201, r.content)
        chat = r.json()
        self.assertEqual(chat["title"], "怎麼標定？")

        r = self.client.patch(f"/api/vision/agent/chats/{chat['id']}",
                              data=json.dumps({"messages": [msg("user", "怎麼標定？"), msg("assistant", "看標定頁")]}),
                              content_type="application/json", **head)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["count"], 2)

        r = self.client.get(f"/api/vision/agent/chats/{chat['id']}", **head)
        self.assertEqual([m["role"] for m in r.json()["messages"]], ["user", "assistant"])
        self.assertEqual(self.client.get("/api/vision/agent/chats", **head).json()["items"][0]["count"], 2)

        r = self.client.patch(f"/api/vision/agent/chats/{chat['id']}", data=json.dumps({"title": "標定筆記"}),
                              content_type="application/json", **head)
        self.assertEqual(r.json()["title"], "標定筆記")

        self.assertEqual(self.client.delete(f"/api/vision/agent/chats/{chat['id']}", **head).status_code, 204)
        self.assertEqual(self.client.get("/api/vision/agent/chats", **head).json()["items"], [])
        self.assertEqual(self.client.get(f"/api/vision/agent/chats/{chat['id']}", **head).status_code, 404)

    def test_only_my_own_conversations(self):
        mine = self._token()
        other_user = User.objects.create_user("bob", password="Passw0rd!")
        chats.create(other_user, [msg("user", "別人的")])
        head = {"HTTP_AUTHORIZATION": f"Bearer {mine}"}
        self.assertEqual(self.client.get("/api/vision/agent/chats", **head).json()["items"], [])
        theirs = AssistantChat.objects.get(owner=other_user)
        self.assertEqual(self.client.get(f"/api/vision/agent/chats/{theirs.pk}", **head).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/vision/agent/chats/{theirs.pk}", **head).status_code, 404)
        self.assertTrue(AssistantChat.objects.filter(pk=theirs.pk).exists())

    def test_integrator_has_no_conversations(self):
        self._token()  # 有使用者了，未帶 token 就是整合方／未登入
        self.assertEqual(self.client.get("/api/vision/agent/chats").status_code, 401)
