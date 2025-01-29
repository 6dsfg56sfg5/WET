from django.urls import path
from .views import square_list, triangle_list, circle_list

urlpatterns = [
    path('squares/', square_list, name='square-list'),
    path('triangles/', triangle_list, name='triangle-list'),
    path('circles/', circle_list, name='circle-list'),
]
