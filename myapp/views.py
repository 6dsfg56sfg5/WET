from django.shortcuts import render
from django.shortcuts import render
from django.http import JsonResponse
from .models import Square, Triangle, Circle

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
