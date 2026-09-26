"""Phase 11 — authentication, profile, password, user management, authorization."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

PW = "T3stPass!!"
U = get_user_model()


def mkuser(u, role="staff", active=True, **kw):
    o, _ = U.objects.get_or_create(username=u, defaults={"email": f"{u}@t.local", "role": role})
    o.email = f"{u}@t.local"
    o.role = role
    o.is_active = active
    for k, v in kw.items():
        setattr(o, k, v)
    o.set_password(PW)
    o.save()
    return o


class AuthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = mkuser("a_admin", "admin")
        cls.staff = mkuser("a_staff", "staff")
        cls.off = mkuser("a_off", "staff", active=False)

    def test_login_logout(self):
        c = Client()
        r = c.post("/login/", {"username": "a_staff", "password": PW})
        self.assertEqual(r.status_code, 302)
        self.assertIn("_auth_user_id", c.session)
        c.post("/logout/")
        self.assertNotIn("_auth_user_id", c.session)

    def test_wrong_password_rejected(self):
        self.assertEqual(Client().post("/login/", {"username": "a_staff", "password": "nope"}).status_code, 200)
        self.assertNotIn("_auth_user_id", Client().session)

    def test_inactive_blocked(self):
        c = Client()
        self.assertFalse(c.login(username="a_off", password=PW))
        r = c.post("/login/", {"username": "a_off", "password": PW})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", c.session)

    def test_profile_update(self):
        c = Client()
        c.login(username="a_staff", password=PW)
        r = c.post("/profile/", {"first_name": "Staff", "last_name": "One",
                                 "email": "a_staff@t.local", "phone": "999"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(U.objects.get(username="a_staff").first_name, "Staff")

    def test_password_change_and_weak_rejected(self):
        c = Client()
        c.login(username="a_staff", password=PW)
        weak = c.post("/password/change/", {"old_password": PW, "new_password1": "123",
                                            "new_password2": "123"})
        self.assertEqual(weak.status_code, 200)  # form error, not changed
        self.assertTrue(Client().login(username="a_staff", password=PW))
        ok = c.post("/password/change/", {"old_password": PW, "new_password1": "NewPass456!",
                                          "new_password2": "NewPass456!"})
        self.assertEqual(ok.status_code, 302)
        self.assertTrue(Client().login(username="a_staff", password="NewPass456!"))


class UserManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = mkuser("m_admin", "admin")
        cls.staff = mkuser("m_staff", "staff")

    def _login(self, u):
        c = Client()
        c.login(username=u, password=PW)
        return c

    def test_list_admin_only(self):
        self.assertEqual(Client().get("/users/").status_code, 302)
        self.assertEqual(self._login("m_staff").get("/users/").status_code, 403)
        self.assertEqual(self._login("m_admin").get("/users/").status_code, 200)

    def test_create_and_duplicate_email_blocked(self):
        c = self._login("m_admin")
        r = c.post("/users/add/", {"username": "n1", "email": "n1@t.local", "role": "staff",
                                   "password1": "Xy123456!", "password2": "Xy123456!"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(U.objects.filter(username="n1").exists())
        dup = c.post("/users/add/", {"username": "n2", "email": "n1@t.local", "role": "staff",
                                     "password1": "Xy123456!", "password2": "Xy123456!"})
        self.assertEqual(dup.status_code, 200)
        self.assertIn("already exists", dup.content.decode())

    def test_cannot_deactivate_self(self):
        c = self._login("m_admin")
        admin = U.objects.get(username="m_admin")
        c.post(f"/users/{admin.pk}/toggle/")
        self.assertTrue(U.objects.get(username="m_admin").is_active)

    def test_toggle_other_user(self):
        c = self._login("m_admin")
        target = U.objects.get(username="m_staff")
        c.post(f"/users/{target.pk}/toggle/")
        self.assertFalse(U.objects.get(username="m_staff").is_active)
