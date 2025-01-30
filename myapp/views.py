from django.http import JsonResponse
from .models import Square, Triangle, Circle
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages

def home(request):
    return render(request, 'home.html')

def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Автоматический вход после регистрации
            messages.success(request, "Регистрация прошла успешно!")
            return redirect('home')  # Перенаправление на главную страницу
    else:
        form = UserCreationForm()
    return render(request, 'register.html', {'form': form})

def user_login(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f"Добро пожаловать, {username}!")
                return redirect('home')  # Перенаправление на главную страницу
        else:
            messages.error(request, "Неверное имя пользователя или пароль.")
    else:
        form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})

def user_logout(request):
    logout(request)
    messages.success(request, "Вы успешно вышли из системы.")
    return redirect('home')  # Перенаправление на главную страницу

def square_list(request):
    squares = Square.objects.all()
    data = [{'id': square.id, 'side_length': square.side_length, 'area': square.area(), 'perimeter': square.perimeter()} for square in squares]
    return JsonResponse(data, safe=False)


def triangle_list(request):
    triangles = Triangle.objects.all()
    data = [{'id': triangle.id, 'side_a': triangle.side_a, 'side_b': triangle.side_b, 'side_c': triangle.side_c, 'area': triangle.area(), 'perimeter': triangle.perimeter()} for triangle in triangles]
    return JsonResponse(data, safe=False)


def circle_list(request):
    circles = Circle.objects.all()
    data = [{'id': circle.id, 'radius': circle.radius, 'area': circle.area(), 'perimeter': circle.perimeter()} for circle in circles]
    return JsonResponse(data, safe=False)

# Create your views here.
