from rest_framework import serializers
from .models import Usuario, UsuarioSistema

class RegistroSerializer(serializers.Serializer):
    nombre = serializers.CharField()
    email = serializers.EmailField()
    usuario = serializers.CharField()
    password = serializers.CharField(write_only=True)

    # 🛡️ VALIDACIÓN DE SEGURIDAD: Evita correos o usuarios duplicados
    def validate(self, data):
        email_input = data.get('email').strip().lower()
        usuario_input = data.get('usuario').strip()

        # Verificar si el correo ya está registrado
        if Usuario.objects.filter(usu_email=email_input).exists():
            raise serializers.ValidationError({"email": "Este correo electrónico ya está registrado."})

        # Verificar si el nombre de usuario ya está tomado
        if UsuarioSistema.objects.filter(ususis_username=usuario_input).exists():
            raise serializers.ValidationError({"usuario": "Este nombre de usuario ya está en uso."})

        return data

    def create(self, validated_data):
        nombre_completo = validated_data['nombre'].strip()
        partes = nombre_completo.split(' ', 1)
        nombres = partes[0]
        apellidos = partes[1] if len(partes) > 1 else "---"

        # Crear el perfil del usuario (Rol: Cliente por defecto)
        nuevo_usuario = Usuario.objects.create(
            usu_nombres=nombres,
            usu_apellidos=apellidos,
            usu_email=validated_data['email'].strip().lower(),
            usu_rol='Cliente', 
            usu_tipodocumento='DNI',
            usu_numdocumento='00000000'
        )

        # 🔒 CAMBIO CLAVE PARA LA VERIFICACIÓN:
        # Creamos las credenciales con estado 'Inactivo'. 
        # No podrán hacer Login hasta que den clic al enlace de Resend.
        usuario_sistema = UsuarioSistema.objects.create_user(
            username=validated_data['usuario'].strip(),
            password=validated_data['password'],
            usu=nuevo_usuario,
            ususis_estado='Inactivo' # 👈 ¡Cambiado! Ahora nace protegido.
        )
        
        return usuario_sistema