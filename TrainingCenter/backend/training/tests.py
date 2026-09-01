"""training API 的行為測試：解鎖規則、判題不外洩答案、角色權限。"""

from django.contrib.auth.models import User
from django.test import TestCase

from .models import (
    Course,
    KnowledgeCard,
    Lesson,
    Profile,
    Project,
    ProjectSubmission,
    QuizQuestion,
)

API = "/api/training"


class TrainingApiTests(TestCase):
    def setUp(self):
        self.card = KnowledgeCard.objects.create(
            code="MEC-99", category="mech", name="測試元件", function="f", install_location="l"
        )
        self.c1 = Course.objects.create(slug="l1", title="第一級", level=1)
        self.c2 = Course.objects.create(slug="l2", title="第二級", level=2)
        self.l1 = Lesson.objects.create(course=self.c1, slug="a", title="A")
        self.l2 = Lesson.objects.create(course=self.c2, slug="b", title="B")
        self.q = QuizQuestion.objects.create(
            prompt="1+1=?", options=["1", "2", "3"], answer_index=1, explanation="因為是 2"
        )
        self.project = Project.objects.create(slug="p1", title="專案一", level=1)

    def login(self, name="stu", role=Profile.Role.STUDENT):
        user = User.objects.create_user(username=name, password="pw12345678")
        Profile.objects.create(user=user, role=role)
        self.client.force_login(user)
        return user

    # ---------------- 知識庫

    def test_cards_search_and_filter(self):
        self.assertEqual(len(self.client.get(f"{API}/cards?category=mech").json()), 1)
        self.assertEqual(len(self.client.get(f"{API}/cards?category=arm").json()), 0)
        self.assertEqual(len(self.client.get(f"{API}/cards?q=測試").json()), 1)

    # ---------------- 課程解鎖

    def test_level_locked_until_previous_completed(self):
        self.login()
        courses = {c["slug"]: c for c in self.client.get(f"{API}/courses").json()}
        self.assertFalse(courses["l1"]["locked"])
        self.assertTrue(courses["l2"]["locked"], "第一級未完成前，第二級應鎖住")

        self.assertEqual(self.client.post(f"{API}/lessons/{self.l1.id}/complete").status_code, 200)

        courses = {c["slug"]: c for c in self.client.get(f"{API}/courses").json()}
        self.assertFalse(courses["l2"]["locked"], "第一級完成後應解鎖第二級")
        self.assertEqual(courses["l1"]["completed_count"], 1)

    def test_complete_lesson_requires_login(self):
        self.assertEqual(self.client.post(f"{API}/lessons/{self.l1.id}/complete").status_code, 401)

    # ---------------- 測驗

    def test_quiz_does_not_leak_answer(self):
        body = self.client.get(f"{API}/quiz").json()[0]
        self.assertNotIn("answer_index", body)
        self.assertNotIn("explanation", body)

    def test_answer_grades_and_records(self):
        self.login()
        r = self.client.post(
            f"{API}/quiz/{self.q.id}/answer", {"chosen_index": 1}, content_type="application/json"
        ).json()
        self.assertTrue(r["correct"])
        self.assertEqual(r["answer_index"], 1)

        me = self.client.get(f"{API}/me").json()
        self.assertEqual((me["quiz_answered"], me["quiz_correct"]), (1, 1))

        # 重答錯誤：以最新一筆為準
        self.client.post(
            f"{API}/quiz/{self.q.id}/answer", {"chosen_index": 0}, content_type="application/json"
        )
        me = self.client.get(f"{API}/me").json()
        self.assertEqual((me["quiz_answered"], me["quiz_correct"]), (1, 0))

    # ---------------- Mini Project

    def test_student_sees_only_own_submissions(self):
        other = User.objects.create_user(username="other", password="pw12345678")
        ProjectSubmission.objects.create(project=self.project, student=other)
        self.login()
        self.client.post(
            f"{API}/projects/p1/submit",
            {"repo_url": "https://example.com/repo", "note": "n"},
            content_type="application/json",
        )
        subs = self.client.get(f"{API}/submissions").json()
        self.assertEqual([s["student"] for s in subs], ["stu"])

    def test_mentor_sees_all_and_can_review(self):
        student = User.objects.create_user(username="s2", password="pw12345678")
        sub = ProjectSubmission.objects.create(project=self.project, student=student)
        self.login("mentor", Profile.Role.MENTOR)
        self.assertEqual(len(self.client.get(f"{API}/submissions").json()), 1)

        r = self.client.post(
            f"{API}/submissions/{sub.id}/review",
            {"status": "passed", "mentor_feedback": "不錯", "score": 90},
            content_type="application/json",
        ).json()
        self.assertEqual((r["status"], r["score"]), ("passed", 90))
        self.assertIsNotNone(r["reviewed_at"])

    def test_student_cannot_review(self):
        sub = ProjectSubmission.objects.create(
            project=self.project, student=User.objects.create_user("s3", password="pw12345678")
        )
        self.login()
        r = self.client.post(
            f"{API}/submissions/{sub.id}/review",
            {"status": "passed"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    # ---------------- 身分

    def test_register_then_me(self):
        r = self.client.post(
            f"{API}/auth/register",
            {"username": "newbie", "password": "pw12345678", "display_name": "小新"},
            content_type="application/json",
        ).json()
        self.assertTrue(r["authenticated"])
        self.assertEqual((r["display_name"], r["role"]), ("小新", "student"))

    def test_register_rejects_short_password(self):
        r = self.client.post(
            f"{API}/auth/register",
            {"username": "x", "password": "short"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_csrf_enforced_on_login_and_answer(self):
        """login／作答沒有 auth=django_auth，CSRF 得靠 require_csrf 補；別讓它悄悄漏掉。"""
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        for url, body in [
            (f"{API}/auth/login", {"username": "u", "password": "pw12345678"}),
            (f"{API}/auth/register", {"username": "u2", "password": "pw12345678"}),
            (f"{API}/quiz/{self.q.id}/answer", {"chosen_index": 0}),
        ]:
            r = c.post(url, body, content_type="application/json")
            self.assertEqual(r.status_code, 403, f"{url} 應該擋下沒有 CSRF token 的請求")

        # 帶了 token 就要放行
        token = c.get(f"{API}/csrf").json()["csrf_token"]
        r = c.post(
            f"{API}/quiz/{self.q.id}/answer",
            {"chosen_index": 1},
            content_type="application/json",
            headers={"x-csrftoken": token},
        )
        self.assertEqual(r.status_code, 200)

    def test_login_bad_password(self):
        User.objects.create_user(username="u", password="pw12345678")
        r = self.client.post(
            f"{API}/auth/login",
            {"username": "u", "password": "nope"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 401)
