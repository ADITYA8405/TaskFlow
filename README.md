# TaskFlow

TaskFlow is a task management web application built with Django. Each user gets a private dashboard for creating, organizing, and tracking their own tasks.

## Features

- User registration, login, and logout
- Private task lists scoped to the signed-in user
- Create, edit, and delete tasks
- Task status: Pending, In Progress, or Completed
- Task priority: Low, Medium, or High
- Optional due dates with overdue tracking
- Dashboard statistics and completion rate
- Search by title and filter by status or priority
- Django admin integration

## Technology Stack

- Python 3.13
- Django 6.1
- SQLite for local development
- Django templates, CSS, and JavaScript
- python-dotenv for local environment configuration

## Project Structure

```text
.
├── apps/
│   ├── accounts/      # Registration and authentication
│   └── tasks/         # Task models, views, templates, and static files
├── config/            # Project settings and URL configuration
├── .env.example       # Environment variable template
├── manage.py
└── requirements.txt
```

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd <repository-directory>
```

### 2. Create and activate a virtual environment

macOS or Linux:

```bash
python3.13 -m venv venv
source venv/bin/activate
```

Windows (PowerShell):

```powershell
py -3.13 -m venv venv
venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure the environment

Copy the example file:

```bash
cp .env.example .env
```

On Windows, use `Copy-Item .env.example .env`.

Generate a secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Paste the generated value into `.env`, keeping the single quotes:

```dotenv
DJANGO_SECRET_KEY='your-generated-secret-key'
```

Never commit `.env`.

### 5. Apply database migrations

```bash
python manage.py migrate
```

### 6. Create an admin user (optional)

```bash
python manage.py createsuperuser
```

## Local Development

Start the development server:

```bash
python manage.py runserver
```

| Page | URL |
| --- | --- |
| Dashboard | http://127.0.0.1:8000/ |
| Register | http://127.0.0.1:8000/accounts/register/ |
| Login | http://127.0.0.1:8000/accounts/login/ |
| Admin | http://127.0.0.1:8000/admin/ |

Run Django's configuration check:

```bash
python manage.py check
```

The current settings are intended for local development. Disable `DEBUG` and configure `ALLOWED_HOSTS` before deploying.
