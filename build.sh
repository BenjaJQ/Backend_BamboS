#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Crear un superusuario automáticamente usando los campos correctos de tu modelo
python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
# Usamos 'ususis_username' que es el campo que Django reconoce en tu modelo
if not User.objects.filter(ususis_username='admin@bambo.com').exists():
    User.objects.create_superuser(
        ususis_username='admin@bambo.com', 
        email='admin@bambo.com', 
        password='tu_contraseña_segura'
    )
    print("Superusuario creado correctamente")
else:
    print("El superusuario ya existe")
END