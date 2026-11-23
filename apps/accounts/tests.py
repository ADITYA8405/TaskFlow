from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

PASSWORD = 'S3cure-Passphrase!42'


class RegistrationTests(TestCase):
    def setUp(self):
        self.url = reverse('register')

    def payload(self, **overrides):
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': PASSWORD,
            'password2': PASSWORD,
        }
        data.update(overrides)
        return data

    def test_register_page_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/register.html')

    def test_successful_registration(self):
        response = self.client.post(self.url, self.payload())

        self.assertRedirects(response, reverse('login'))
        user = User.objects.get(username='newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertTrue(user.check_password(PASSWORD))

    def test_registration_does_not_log_user_in(self):
        self.client.post(self.url, self.payload())

        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_invalid_registration(self):
        cases = {
            'missing username': ({'username': ''}, 'username'),
            'missing email': ({'email': ''}, 'email'),
            'invalid email': ({'email': 'not-an-email'}, 'email'),
            'password mismatch': ({'password2': 'Different-Pass!42'}, 'password2'),
            'common password': (
                {'password1': 'password', 'password2': 'password'},
                'password2',
            ),
        }
        for name, (overrides, field) in cases.items():
            with self.subTest(name):
                response = self.client.post(self.url, self.payload(**overrides))

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'accounts/register.html')
                self.assertIn(field, response.context['form'].errors)
                self.assertEqual(User.objects.count(), 0)

    def test_duplicate_username_is_rejected(self):
        User.objects.create_user('newuser')

        response = self.client.post(self.url, self.payload())

        self.assertEqual(response.status_code, 200)
        self.assertIn('username', response.context['form'].errors)
        self.assertEqual(User.objects.count(), 1)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password=PASSWORD)
        self.login_url = reverse('login')
        self.logout_url = reverse('logout')

    def test_login_page_renders(self):
        response = self.client.get(self.login_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')

    def test_successful_login(self):
        response = self.client.post(
            self.login_url, {'username': 'alice', 'password': PASSWORD}
        )

        self.assertRedirects(response, settings.LOGIN_REDIRECT_URL)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_login_returns_to_next_url(self):
        next_url = reverse('create_task')

        response = self.client.post(
            f'{self.login_url}?next={next_url}',
            {'username': 'alice', 'password': PASSWORD},
        )

        self.assertRedirects(response, next_url)

    def test_login_ignores_external_next_url(self):
        response = self.client.post(
            f'{self.login_url}?next=https://evil.example/',
            {'username': 'alice', 'password': PASSWORD},
        )

        self.assertRedirects(response, settings.LOGIN_REDIRECT_URL)

    def test_invalid_login(self):
        response = self.client.post(
            self.login_url, {'username': 'alice', 'password': 'wrong-password'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_logout_ends_session_and_redirects_to_login(self):
        self.client.force_login(self.user)

        response = self.client.post(self.logout_url)

        self.assertRedirects(response, self.login_url)
        self.assertNotIn(SESSION_KEY, self.client.session)

        task_list_url = reverse('task_list')
        self.assertRedirects(
            self.client.get(task_list_url),
            f'{self.login_url}?next={task_list_url}',
        )

    def test_logout_rejects_get(self):
        self.client.force_login(self.user)

        response = self.client.get(self.logout_url)

        self.assertEqual(response.status_code, 405)
        self.assertIn(SESSION_KEY, self.client.session)
