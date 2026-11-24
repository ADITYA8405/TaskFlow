from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import TaskForm
from .models import Task
from .tasks import find_overdue_tasks

User = get_user_model()


def make_task(owner, title='Task', **fields):
    return Task.objects.create(owner=owner, title=title, **fields)


def task_payload(**overrides):
    """Return valid POST data for TaskForm."""
    data = {
        'title': 'Write tests',
        'description': 'Cover the main flows',
        'due_date': '25-12-2030',
        'priority': 'HIGH',
        'status': 'IN_PROGRESS',
    }
    data.update(overrides)
    return data


class TaskModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice')

    def test_new_task_uses_default_values(self):
        task = make_task(self.user, 'Defaults')

        self.assertEqual(task.status, 'PENDING')
        self.assertEqual(task.priority, 'MEDIUM')
        self.assertEqual(task.description, '')
        self.assertIsNone(task.due_date)
        self.assertIsNotNone(task.created_at)
        self.assertIsNotNone(task.updated_at)

    def test_task_belongs_to_owner(self):
        task = make_task(self.user)

        self.assertEqual(task.owner, self.user)
        self.assertIn(task, self.user.task_set.all())

    def test_deleting_owner_deletes_their_tasks(self):
        make_task(self.user)

        self.user.delete()

        self.assertEqual(Task.objects.count(), 0)

    def test_string_representation_is_title(self):
        self.assertEqual(str(Task(title='Buy milk')), 'Buy milk')


class TaskFormTests(TestCase):
    def test_valid_submission(self):
        form = TaskForm(data=task_payload())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['due_date'], date(2030, 12, 25))

    def test_required_fields(self):
        for field in ('title', 'priority', 'status'):
            with self.subTest(field=field):
                form = TaskForm(data=task_payload(**{field: ''}))

                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_optional_fields(self):
        form = TaskForm(data=task_payload(description='', due_date=''))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['due_date'])

    def test_whitespace_only_title_is_rejected(self):
        form = TaskForm(data=task_payload(title='   '))

        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)

    def test_title_max_length(self):
        self.assertTrue(TaskForm(data=task_payload(title='x' * 200)).is_valid())

        form = TaskForm(data=task_payload(title='x' * 201))
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)

    def test_invalid_choices_are_rejected(self):
        for field in ('priority', 'status'):
            with self.subTest(field=field):
                form = TaskForm(data=task_payload(**{field: 'INVALID'}))

                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_accepted_due_date_formats(self):
        for value in ('25-12-2030', '25/12/2030', '2030-12-25'):
            with self.subTest(value=value):
                form = TaskForm(data=task_payload(due_date=value))

                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['due_date'], date(2030, 12, 25))

    def test_invalid_due_dates_are_rejected(self):
        for value in ('12-25-2030', '31-02-2030', 'tomorrow'):
            with self.subTest(value=value):
                form = TaskForm(data=task_payload(due_date=value))

                self.assertFalse(form.is_valid())
                self.assertIn('due_date', form.errors)


class TaskViewTestCase(TestCase):
    """Base class providing a logged-in user and a second user."""

    def setUp(self):
        self.user = User.objects.create_user('alice')
        self.other_user = User.objects.create_user('bob')
        self.client.force_login(self.user)
        self.list_url = reverse('task_list')

    def listed_tasks(self, **params):
        response = self.client.get(self.list_url, params)
        self.assertEqual(response.status_code, 200)
        return list(response.context['tasks'])


class AnonymousAccessTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user('alice')
        self.task = make_task(owner, 'Private')
        self.urls = [
            reverse('task_list'),
            reverse('create_task'),
            reverse('edit_task', args=[self.task.id]),
            reverse('delete_task', args=[self.task.id]),
        ]

    def test_get_redirects_to_login(self):
        for url in self.urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_post_redirects_without_changing_data(self):
        for url in self.urls:
            with self.subTest(url=url):
                response = self.client.post(url, task_payload(title='Changed'))

                self.assertRedirects(response, f"{reverse('login')}?next={url}")

        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Private')
        self.assertEqual(Task.objects.count(), 1)


class TaskListViewTests(TaskViewTestCase):
    def test_lists_only_own_tasks(self):
        own = make_task(self.user, 'Alice task')
        make_task(self.other_user, 'Bob task')

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tasks/task_list.html')
        self.assertEqual(list(response.context['tasks']), [own])
        self.assertContains(response, 'Alice task')
        self.assertNotContains(response, 'Bob task')

    def test_empty_state(self):
        response = self.client.get(self.list_url)

        self.assertContains(response, 'No tasks yet')


class TaskCreateViewTests(TaskViewTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('create_task')

    def test_form_page_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tasks/task_form.html')

    def test_create_assigns_logged_in_user_as_owner(self):
        response = self.client.post(
            self.url,
            task_payload(owner=self.other_user.id),
        )

        self.assertRedirects(response, self.list_url)
        task = Task.objects.get()
        self.assertEqual(task.owner, self.user)
        self.assertEqual(task.title, 'Write tests')
        self.assertEqual(task.due_date, date(2030, 12, 25))

    def test_invalid_submission_shows_errors(self):
        response = self.client.post(self.url, task_payload(title=''))

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'title', 'This field is required.'
        )
        self.assertEqual(Task.objects.count(), 0)


class TaskEditViewTests(TaskViewTestCase):
    def setUp(self):
        super().setUp()
        self.task = make_task(self.user, 'Original')
        self.url = reverse('edit_task', args=[self.task.id])

    def test_edit_page_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tasks/task_edit.html')
        self.assertEqual(response.context['task'], self.task)

    def test_successful_edit(self):
        response = self.client.post(self.url, task_payload(title='Updated'))

        self.assertRedirects(response, self.list_url)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Updated')
        self.assertEqual(self.task.status, 'IN_PROGRESS')
        self.assertEqual(self.task.priority, 'HIGH')

    def test_edit_cannot_reassign_owner(self):
        self.client.post(self.url, task_payload(owner=self.other_user.id))

        self.task.refresh_from_db()
        self.assertEqual(self.task.owner, self.user)

    def test_invalid_edit_does_not_save(self):
        response = self.client.post(self.url, task_payload(title=''))

        self.assertEqual(response.status_code, 200)
        self.assertIn('title', response.context['form'].errors)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Original')

    def test_cannot_edit_another_users_task(self):
        task = make_task(self.other_user, 'Bob task')
        url = reverse('edit_task', args=[task.id])

        self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.post(url, task_payload(title='Hacked'))

        self.assertEqual(response.status_code, 404)
        task.refresh_from_db()
        self.assertEqual(task.title, 'Bob task')


class TaskDeleteViewTests(TaskViewTestCase):
    def setUp(self):
        super().setUp()
        self.task = make_task(self.user, 'Disposable')
        self.url = reverse('delete_task', args=[self.task.id])

    def test_get_shows_confirmation_without_deleting(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tasks/task_confirm_delete.html')
        self.assertTrue(Task.objects.filter(id=self.task.id).exists())

    def test_successful_delete(self):
        response = self.client.post(self.url)

        self.assertRedirects(response, self.list_url)
        self.assertFalse(Task.objects.filter(id=self.task.id).exists())

    def test_cannot_delete_another_users_task(self):
        task = make_task(self.other_user, 'Bob task')
        url = reverse('delete_task', args=[task.id])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(Task.objects.filter(id=task.id).exists())


class TaskFilterTests(TaskViewTestCase):
    def setUp(self):
        super().setUp()
        self.report = make_task(
            self.user, 'Quarterly Report', status='PENDING', priority='HIGH'
        )
        self.groceries = make_task(
            self.user, 'Buy groceries', status='COMPLETED', priority='LOW'
        )
        self.review = make_task(
            self.user, 'Review report', status='IN_PROGRESS', priority='HIGH'
        )
        self.foreign = make_task(
            self.other_user, 'Report for Bob', status='PENDING', priority='HIGH'
        )

    def test_search_is_case_insensitive_partial_title_match(self):
        self.assertCountEqual(
            self.listed_tasks(search='REPORT'), [self.report, self.review]
        )

    def test_search_without_match_shows_empty_state(self):
        response = self.client.get(self.list_url, {'search': 'nothing'})

        self.assertEqual(list(response.context['tasks']), [])
        self.assertContains(response, 'No matching tasks')

    def test_status_filter(self):
        self.assertEqual(self.listed_tasks(status='COMPLETED'), [self.groceries])

    def test_priority_filter(self):
        self.assertCountEqual(
            self.listed_tasks(priority='HIGH'), [self.report, self.review]
        )

    def test_filters_combine(self):
        self.assertEqual(
            self.listed_tasks(search='report', status='IN_PROGRESS', priority='HIGH'),
            [self.review],
        )

    def test_filters_never_include_other_users_tasks(self):
        self.assertNotIn(
            self.foreign,
            self.listed_tasks(search='Bob') + self.listed_tasks(priority='HIGH'),
        )

    def test_filters_do_not_change_dashboard_stats(self):
        response = self.client.get(self.list_url, {'status': 'COMPLETED'})

        self.assertEqual(response.context['stats']['total'], 3)
        self.assertEqual(len(response.context['tasks']), 1)

    def test_selected_filters_are_returned_to_template(self):
        response = self.client.get(
            self.list_url,
            {'search': 'report', 'status': 'PENDING', 'priority': 'HIGH'},
        )

        self.assertEqual(response.context['search_query'], 'report')
        self.assertEqual(response.context['status_filter'], 'PENDING')
        self.assertEqual(response.context['priority_filter'], 'HIGH')


class DashboardStatsTests(TaskViewTestCase):
    TODAY = date(2030, 6, 15)

    def setUp(self):
        super().setUp()
        # Fix "today" so the overdue boundary cannot flake around midnight.
        patcher = patch(
            'apps.tasks.views.timezone.localdate', return_value=self.TODAY
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def stats(self):
        return self.client.get(self.list_url).context['stats']

    def test_stats_with_no_tasks(self):
        response = self.client.get(self.list_url)

        self.assertEqual(
            response.context['stats'],
            {'total': 0, 'completed': 0, 'pending': 0, 'in_progress': 0, 'overdue': 0},
        )
        self.assertEqual(response.context['completion_rate'], 0)

    def test_status_counts_and_completion_rate(self):
        make_task(self.user, status='COMPLETED')
        make_task(self.user, status='PENDING')
        make_task(self.user, status='IN_PROGRESS')

        response = self.client.get(self.list_url)

        stats = response.context['stats']
        self.assertEqual(stats['total'], 3)
        self.assertEqual(stats['completed'], 1)
        self.assertEqual(stats['pending'], 1)
        self.assertEqual(stats['in_progress'], 1)
        self.assertEqual(response.context['completion_rate'], 33)

    def test_overdue_counts_past_due_unfinished_tasks(self):
        yesterday = self.TODAY - timedelta(days=1)
        make_task(self.user, status='PENDING', due_date=yesterday)
        make_task(self.user, status='IN_PROGRESS', due_date=yesterday)

        self.assertEqual(self.stats()['overdue'], 2)

    def test_overdue_excludes_tasks_that_are_not_late(self):
        cases = {
            'due today': {'status': 'PENDING', 'due_date': self.TODAY},
            'due tomorrow': {
                'status': 'PENDING',
                'due_date': self.TODAY + timedelta(days=1),
            },
            'no due date': {'status': 'PENDING', 'due_date': None},
            'completed late': {
                'status': 'COMPLETED',
                'due_date': self.TODAY - timedelta(days=1),
            },
        }
        for name, fields in cases.items():
            with self.subTest(name):
                task = make_task(self.user, **fields)

                self.assertEqual(self.stats()['overdue'], 0)
                task.delete()

    def test_stats_ignore_other_users_tasks(self):
        make_task(
            self.other_user,
            status='PENDING',
            due_date=self.TODAY - timedelta(days=1),
        )

        stats = self.stats()

        self.assertEqual(stats['total'], 0)
        self.assertEqual(stats['pending'], 0)
        self.assertEqual(stats['overdue'], 0)


class FindOverdueTasksTaskTests(TestCase):
    TODAY = date(2030, 6, 15)

    def setUp(self):
        self.user = User.objects.create_user(username='celery', password='pass12345')
        patcher = patch('apps.tasks.tasks.timezone.localdate', return_value=self.TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_task(self):
        # .apply() runs the task in-process through Celery, without a broker.
        return find_overdue_tasks.apply().get()

    def test_reports_overdue_tasks_that_are_not_completed(self):
        yesterday = self.TODAY - timedelta(days=1)
        pending = make_task(self.user, 'Pending', status='PENDING', due_date=yesterday)
        in_progress = make_task(
            self.user, 'In progress', status='IN_PROGRESS',
            due_date=self.TODAY - timedelta(days=10),
        )
        ownerless = make_task(None, 'Ownerless', status='PENDING', due_date=yesterday)

        result = self.run_task()

        self.assertEqual(result['checked_on'], '2030-06-15')
        self.assertEqual(result['overdue_count'], 3)
        self.assertEqual(
            result['overdue_task_ids'], [in_progress.pk, pending.pk, ownerless.pk]
        )

    def test_ignores_completed_tasks_even_when_past_due(self):
        make_task(
            self.user, status='COMPLETED', due_date=self.TODAY - timedelta(days=5)
        )

        result = self.run_task()

        self.assertEqual(result['overdue_count'], 0)
        self.assertEqual(result['overdue_task_ids'], [])

    def test_ignores_tasks_that_are_not_overdue(self):
        make_task(self.user, 'Due today', status='PENDING', due_date=self.TODAY)
        make_task(
            self.user, 'Due later', status='PENDING',
            due_date=self.TODAY + timedelta(days=1),
        )
        make_task(self.user, 'No due date', status='PENDING', due_date=None)

        self.assertEqual(self.run_task()['overdue_count'], 0)

    def test_does_not_modify_tasks(self):
        task = make_task(
            self.user, status='PENDING', due_date=self.TODAY - timedelta(days=1)
        )
        before = Task.objects.values().get(pk=task.pk)

        self.run_task()

        self.assertEqual(Task.objects.values().get(pk=task.pk), before)
