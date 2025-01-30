# Проект Django: Аутентификация и геометрические фигуры

Этот проект представляет собой веб-приложение на Django. Цель данного программного обесечения помочь в освоении множества web технологий

## Основные функции

- Регистрация новых пользователей.
- Вход и выход из системы.
- главнвя страница, с кнопками!
- Логирование всех входящих запросов с помощью кастомной middleware.
- поддержка postgreSQL
- проверка стиля кода с помощью flake8.
- следование стилю кода PEP8 с помощью autopep8.
- а также статический анализатор типов для Python - mypy.
- Модели для геометрических фигур:
  - Квадрат (площадь и периметр).
  - Треугольник (площадь и периметр).
  - Круг (площадь и периметр).

## Навигация по сайту 
  http://127.0.0.1:8000/ - home  
  http://127.0.0.1:8000/squares/ - квадрат  
  http://127.0.0.1:8000/triangles/ - треугольник  
  http://127.0.0.1:8000/circles/ - круг  
  http://127.0.0.1:8000/register/ - регистрация  
  http://127.0.0.1:8000/login/ - вход  
  http://127.0.0.1:8000/logout/ -выход  

## Установка и настройка

```bash
# Для Linux/MacOS
curl -sSL https://install.python-poetry.org | python3 -

# Для Windows (PowerShell)
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -

git clone https://github.com/6dsfg56sfg5/WET.git
python -m venv venv
source venv/bin/activate  # Для Linux/MacOS
# или
venv\Scripts\activate     # Для Windows

poetry add $(cat requirements.txt)
python manage.py migrate
poetry run python manage.py runserver
```
## admin panel
username: Congratulations  
passwd: youwon!
