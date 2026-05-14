from rest_framework import serializers
from .models import Usuario, UsuarioSistema

# ==========================================
# 1. SERIALIZADOR PARA VER DATOS
# ==========================================
class UsuarioSistemaSerializer(serializers.ModelSerializer):
    class Meta:
        # Usamos los nombres de los campos definidos en el modelo
        model = UsuarioSistema
        fields = ['ususis_id', 'ususis_username', 'ususis_estado']

# ==========================================
# 2. SERIALIZADOR DE REGISTRO (LOGICA DE NEGOCIO)
# ==========================================
class RegistroSerializer(serializers.Serializer):
    # Estos deben coincidir con lo que envías desde el JSON de React
    nombre = serializers.CharField()
    email = serializers.EmailField()
    usuario = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def create(self, validated_data):
        # 1. Lógica para separar Nombres de Apellidos
        nombre_completo = validated_data['nombre'].strip()
        partes = nombre_completo.split(' ', 1)
        nombres = partes[0]
        apellidos = partes[1] if len(partes) > 1 else "---"

        # 2. Crear fila en la tabla 'Usuario' (Perfil Personal)
        # El Signal post_save creará automáticamente el registro en la tabla 'cliente'
        nuevo_usuario = Usuario.objects.create(
            usu_nombres=nombres,
            usu_apellidos=apellidos,
            usu_email=validated_data['email'],
            usu_rol='Cliente', 
            usu_tipodocumento='DNI',
            usu_numdocumento='00000000' # Dato temporal
        )

        # 3. Crear fila en la tabla 'UsuarioSistema' (Acceso)
        # IMPORTANTE: Pasamos 'password' (que es el campo que ahora mapea a la DB)
        # y 'usu' (que es la instancia de Usuario que acabamos de crear)
        usuario_sistema = UsuarioSistema.objects.create_user(
            username=validated_data['usuario'],
            password=validated_data['password'],
            usu=nuevo_usuario,
            ususis_estado='Activo'
        )
        
        return usuario_sistema