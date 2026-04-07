from django.shortcuts import render
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import check_password

# Importación de tus modelos
from .models import Administrador, Dj, Cliente, Usuario, UsuarioSistema

# ==========================================
# 1. PERSONALIZACIÓN DEL LOGIN (JWT)
# ==========================================
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Permitimos que ususis_username sea opcional en el esquema de validación inicial
        self.fields['ususis_username'] = serializers.CharField(required=False)
        if 'username' in self.fields:
            self.fields['username'].required = False

    def validate(self, attrs):
        # Extraemos los datos crudos del request
        data_json = self.context['request'].data
        
        # 1. Capturar entrada (Puede venir como 'ususis_username', 'username' o 'email')
        login_input = (
            data_json.get("ususis_username") or 
            attrs.get("username") or 
            data_json.get("email")
        )
        password_input = data_json.get("password")
        
        print(f"\n--- DEBUG LOGIN ---")
        print(f"1. Input recibido: {login_input}")

        # 2. Buscar usuario en la DB
        # Buscamos por el campo de username O por el email en la tabla relacionada Usuario
        user_obj = UsuarioSistema.objects.filter(
            Q(ususis_username=login_input) | Q(usu__usu_email=login_input)
        ).first()
        
        if not user_obj:
            print("2. ERROR: Usuario no encontrado.")
            raise serializers.ValidationError("Usuario no encontrado.")

        print(f"2. Usuario encontrado en DB: {user_obj.ususis_username}")

        # 3. Validar contraseña manualmente
        # CAMBIO CLAVE: Aunque en el modelo se llame ususis_password, 
        # Django AbstractBaseUser siempre expone la contraseña encriptada en el atributo .password
        if not check_password(password_input, user_obj.password):
            print("3. ERROR: Contraseña incorrecta.")
            raise serializers.ValidationError("Contraseña incorrecta.")

        if not user_obj.is_active:
            print("3. ERROR: Cuenta inactiva.")
            raise serializers.ValidationError("Cuenta inactiva.")

        # 4. GENERACIÓN MANUAL DEL TOKEN
        # Usamos RefreshToken para saltar la autenticación estándar de Django que daría 401
        refresh = RefreshToken.for_user(user_obj)
        
        # Determinar el rol para el frontend
        user_role = user_obj.usu.usu_rol.lower() if user_obj.usu.usu_rol else 'cliente'

        print(f"4. LOGIN EXITOSO. Bienvenido {user_obj.ususis_username} (Rol: {user_role})\n")

        # Estructura de respuesta para el Frontend
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'username': user_obj.ususis_username,
            'role': user_role,
            'user_id': user_obj.usu.usu_id
        }

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Vista que utiliza el serializador personalizado para manejar 
    el login por email o username.
    """
    serializer_class = CustomTokenObtainPairSerializer

# ==========================================
# 2. VISTA DE REGISTRO
# ==========================================
class RegistroUsuarioView(APIView):
    def post(self, request):
        from .serializers import RegistroSerializer 
        serializer = RegistroSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "✅ Usuario creado con éxito"}, status=status.HTTP_201_CREATED)
        
        print(f"❌ Error en registro: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
# ==========================================
# 3. GESTIÓN DE USUARIOS PARA EL PANEL
# ==========================================
class ListaUsuariosView(APIView):
    def get(self, request):
        usuarios = Usuario.objects.all().values(
            'usu_id', 'usu_nombres', 'usu_apellidos', 'usu_email', 'usu_rol', 'usu_telefono'
        )
        return Response(list(usuarios), status=status.HTTP_200_OK)

    def patch(self, request, pk):
        try:
            usuario = Usuario.objects.get(pk=pk)
            nuevo_rol = request.data.get('usu_rol')
            if nuevo_rol:
                usuario.usu_rol = nuevo_rol
                usuario.save()
                return Response({"msg": f"Rol actualizado a {nuevo_rol}"})
            return Response({"error": "Falta el campo usu_rol"}, status=400)
        except Usuario.DoesNotExist:
            return Response({"error": "Usuario no encontrado"}, status=404)