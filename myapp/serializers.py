from rest_framework import serializers
from .models import Square, Triangle, Circle
import math

class ShapeSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ['id', 'name']

class SquareSerializer(ShapeSerializer):
    class Meta(ShapeSerializer.Meta):
        model = Square
        fields = ShapeSerializer.Meta.fields + ['side_length', 'area', 'perimeter']

    area = serializers.SerializerMethodField()
    perimeter = serializers.SerializerMethodField()

    def get_area(self, obj):
        return obj.area()

    def get_perimeter(self, obj):
        return obj.perimeter()

class TriangleSerializer(ShapeSerializer):
    class Meta(ShapeSerializer.Meta):
        model = Triangle
        fields = ShapeSerializer.Meta.fields + ['side_a', 'side_b', 'side_c', 'area', 'perimeter']

    area = serializers.SerializerMethodField()
    perimeter = serializers.SerializerMethodField()

    def get_area(self, obj):
        return obj.area()

    def get_perimeter(self, obj):
        return obj.perimeter()

class CircleSerializer(ShapeSerializer):
    class Meta(ShapeSerializer.Meta):
        model = Circle
        fields = ShapeSerializer.Meta.fields + ['radius', 'area', 'perimeter']

    area = serializers.SerializerMethodField()
    perimeter = serializers.SerializerMethodField()

    def get_area(self, obj):
        return obj.area()

    def get_perimeter(self, obj):
        return obj.perimeter()