from django.db import models
import math

class Shape(models.Model):
    # Базовый класс для геометрических фигур
    name = models.CharField(max_length=100)

    class Meta:
        abstract = True

class Square(Shape):
    side_length = models.FloatField()

    def area(self):
        return self.side_length ** 2

    def perimeter(self):
        return 4 * self.side_length

class Triangle(Shape):
    side_a = models.FloatField()
    side_b = models.FloatField()
    side_c = models.FloatField()

    def area(self):
        s = (self.side_a + self.side_b + self.side_c) / 2
        return math.sqrt(s * (s - self.side_a) * (s - self.side_b) * (s - self.side_c))

    def perimeter(self):
        return self.side_a + self.side_b + self.side_c

class Circle(Shape):
    radius = models.FloatField()

    def area(self):
        return math.pi * self.radius ** 2

    def perimeter(self):
        return 2 * math.pi * self.radius



#
# Create your models here.
