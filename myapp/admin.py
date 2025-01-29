from django.contrib import admin
from .models import Shape
from django.contrib import admin
from .models import Square, Triangle, Circle

@admin.register(Square)
class SquareAdmin(admin.ModelAdmin):
    list_display = ('id', 'side_length', 'area', 'perimeter')
    search_fields = ('id',)

@admin.register(Triangle)
class TriangleAdmin(admin.ModelAdmin):
    list_display = ('id', 'side_a', 'side_b', 'side_c', 'area', 'perimeter')
    search_fields = ('id',)

@admin.register(Circle)
class CircleAdmin(admin.ModelAdmin):
    list_display = ('id', 'radius', 'area', 'perimeter')
    search_fields = ('id',)



# Register your models here.
