from django.shortcuts import render, redirect,get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Task
from .forms import TaskForm
from django.db.models import Count, Q
from django.utils import timezone

@login_required
def task_list(request):

    # Get all tasks belonging to the logged-in user
    user_tasks = Task.objects.filter(owner=request.user)

    # Calculate dashboard statistics
    stats = user_tasks.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='COMPLETED')),
        pending=Count('id', filter=Q(status='PENDING')),
        in_progress=Count('id', filter=Q(status='IN_PROGRESS')),
        overdue=Count(
            'id',
            filter=Q(due_date__lt=timezone.localdate()) & ~Q(status='COMPLETED')
        ),
    )

    # Calculate completion percentage
    completion_rate = (
        round((stats['completed'] / stats['total']) * 100)
        if stats['total'] > 0 else 0
    )

    # Start with the user's tasks for the task list
    tasks = user_tasks

    # Search by title
    search_query = request.GET.get('search', '')
    if search_query:
        tasks = tasks.filter(title__icontains=search_query)

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        tasks = tasks.filter(status=status_filter)

    # Filter by priority
    priority_filter = request.GET.get('priority', '')
    if priority_filter:
        tasks = tasks.filter(priority=priority_filter)

    # Sort newest tasks first
    tasks = tasks.order_by('-created_at')

    context = {
        'tasks': tasks,
        'search_query': search_query,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'stats': stats,
        'completion_rate': completion_rate,
    }

    return render(request, 'tasks/task_list.html', context)
@login_required
def create_task(request):
    form = TaskForm()

    if request.method == 'POST':
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.owner = request.user
            task.save()

            return redirect('task_list')

    context = {
        'form': form
    }

    return render(request, 'tasks/task_form.html', context)

@login_required
def edit_task(request, task_id):
    task = get_object_or_404(Task, id=task_id,owner=request.user)

    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task)

        if form.is_valid():
            form.save()
            return redirect('task_list')
    else:
        form = TaskForm(instance=task)

    context = {'form': form, 'task': task}
    return render(request, 'tasks/task_edit.html', context)

@login_required
def delete_task(request, task_id):
    task = get_object_or_404(Task, id=task_id,owner=request.user
)

    if request.method == 'POST':
        task.delete()
        return redirect('task_list')

    return render(request, 'tasks/task_confirm_delete.html', {'task': task})