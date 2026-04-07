#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Crear un superusuario automáticamente si no existe
# Cambia 'admin@bambo.com' y 'tu_contraseña_segura' por lo que quieras
python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(email='admin@bambo.com').exists():
    User.objects.create_superuser('admin@bambo.com', 'admin@bambo.com', 'tu_contraseña_segura')
    print("Superusuario creado correctamente")
else:
    print("El superusuario ya existe")
END