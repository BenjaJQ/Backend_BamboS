import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings') # Revisa si tu carpeta de settings se llama 'core'
django.setup()

from django.contrib.auth.models import User

try:
    u = User.objects.get(username='admin_test')
    u.set_password('BamboActual1243') 
    u.save()
    print("✅ CONTRASEÑA ACTUALIZADA CON ÉXITO")
except Exception as e:
    print(f"❌ ERROR: {e}")