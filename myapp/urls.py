from django.urls import path

from . import views
from .views import square_list, triangle_list, circle_list

urlpatterns = [
    path('', views.home, name='home'),  # Домашняя страница
    path('squares/', square_list, name='square-list'),
    path('triangles/', triangle_list, name='triangle-list'),
    path('circles/', circle_list, name='circle-list'),
    path('register/', views.register, name='register'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
]
