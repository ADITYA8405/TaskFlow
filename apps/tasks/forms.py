from django import forms
from .models import Task


class TaskForm(forms.ModelForm):

    due_date = forms.DateField(
        required=False,
        input_formats=[
            '%d-%m-%Y',
            '%d/%m/%Y',
            '%Y-%m-%d',
        ],
        widget=forms.DateInput(
            format='%d-%m-%Y',
            attrs={
                'type': 'text',
                'placeholder': 'DD-MM-YYYY',
                'autocomplete': 'off',
            }
        )
    )
    class Meta:
        model = Task
        fields = [
            'title',
            'description',
            'due_date',
            'priority',
            'status',
 
        ]
