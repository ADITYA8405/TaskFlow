"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Root URL serves the task list view
    path('', include('apps.tasks.urls')),
    # Preserve /tasks/ for backward compatibility
    path('tasks/', include('apps.tasks.urls')),
    path('accounts/', include('apps.accounts.urls')),
]
