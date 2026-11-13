import os  
import json
import resend
import requests
from django.shortcuts import render
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers
from datetime import datetime
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import AnonRateThrottle 
from django.contrib.auth.hashers import check_password
from rest_framework import status
from django.db import transaction

# Librerías para Excel
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# 🚀 CAMBIO DE LIBRERÍA: Usamos Groq en lugar de Google GenAI
from groq import Groq 

# Importación de tus modelos
from .models import Administrador, Dj, Cliente, Usuario, UsuarioSistema, Venta, Pago, Local, Paquete


# ==========================================
# CONFIGURACIÓN DE IA SEGURA (CONTRA FILTRACIONES EN GITHUB)
# ==========================================
# Ahora os.environ.get busca exactamente los nombres que pusiste en Render
GROQ_API_KEY_ADMIN = os.environ.get("GROQ_API_KEY_ADMIN")
GROQ_API_KEY_CLIENTE = os.environ.get("GROQ_API_KEY_CLIENTE")

resend.api_key = os.environ.get("RESEND_API_KEY")

# Inicializamos los clientes de Groq inyectando las llaves explícitamente
client_groq = Groq(api_key=GROQ_API_KEY_ADMIN) if GROQ_API_KEY_ADMIN else None
client_groq_cliente = Groq(api_key=GROQ_API_KEY_CLIENTE) if GROQ_API_KEY_CLIENTE else None

def validar_turnstile(token):
    # Secret Key de prueba oficial de Cloudflare Turnstile
    SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
    url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    
    payload = {
        'secret': SECRET_KEY,
        'response': token
    }
    
    try:
        response = requests.post(url, data=payload, timeout=5)
        datos = response.json()
        return datos.get('success', False)
    except Exception as e:
        print(f"❌ Error al consultar servidor de Turnstile: {str(e)}")
        return False
    
# ==========================================
# VERIFICACION DE UBICACIONES 
# ==========================================
    
class BuscarLocalView(APIView):
    """Retorna sugerencias de locales registrados cuando el cliente escribe."""
    def get(self, request):
        query = request.GET.get('q', '').strip()
        if len(query) >= 2:
            locales = Local.objects.filter(loc_nombre__icontains=query).values(
                'loc_id', 'loc_nombre', 'loc_direccion', 'loc_distrito'
            )[:5]
            return Response(list(locales), status=status.HTTP_200_OK)
        return Response([], status=status.HTTP_200_OK)


class RegistrarEventoView(APIView):
    """Crea o reutiliza el Local y registra la Venta en BD."""
    @transaction.atomic
    def post(self, request):
        data = request.data
        tipo_evento = data.get('tipo_evento') # 'hogar' o 'local'
        local_id = data.get('loc_id')

        # 1. Obtener datos de ubicación
        if tipo_evento == 'local' and local_id:
            local_obj = Local.objects.get(pk=local_id)
            nombre_lugar = local_obj.loc_nombre
            direccion = local_obj.loc_direccion
            distrito = local_obj.loc_distrito
        else:
            nombre_lugar = "Casa / Hogar" if tipo_evento == 'hogar' else data.get('loc_nombre')
            direccion = data.get('loc_direccion')
            distrito = data.get('loc_distrito')
            
            Local.objects.create(
                loc_nombre=nombre_lugar,
                loc_direccion=direccion,
                loc_distrito=distrito
            )

        # 2. Obtener o crear el cliente en BD si aún no existe el perfil
        usuario_obj = request.user.usu
        cliente_obj = Cliente.objects.filter(usu=usuario_obj).first()
        if not cliente_obj:
            cliente_obj = Cliente.objects.create(usu=usuario_obj)

        paquete_obj = Paquete.objects.get(pk=data.get('paq_id'))

        # 3. Crear la Venta
        nueva_venta = Venta.objects.create(
            cli=cliente_obj,
            paq=paquete_obj,
            ven_fechaevento=data.get('ven_fechaevento'),
            ven_duracionhoras=paquete_obj.paq_tiempohoras or 5,
            ven_montototal=paquete_obj.paq_precio,
            ven_nombrelugar=nombre_lugar,
            ven_direccion=direccion,
            ven_distrito=distrito,
            ven_referencia=data.get('loc_referencia', ''),
            ven_estado='Pendiente'
        )

        return Response({
            "message": "Evento registrado correctamente",
            "ven_id": nueva_venta.pk
        }, status=status.HTTP_201_CREATED)

# ==========================================
# 1. PERSONALIZACIÓN DEL LOGIN (JWT + CAPTCHA)
# ==========================================
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ususis_username'] = serializers.CharField(required=False)
        if 'username' in self.fields:
            self.fields['username'].required = False

    def validate(self, attrs):
        data_json = self.context['request'].data
        
        # 🛡️ VALIDACIÓN DE CLOUDFLARE TURNSTILE
        captcha_token = data_json.get('cf_turnstile_response')
        if not captcha_token or not validar_turnstile(captcha_token):
            print("❌ ERROR: Verificación de Captcha fallida.")
            raise serializers.ValidationError("Error en la verificación de seguridad (Captcha). Intenta nuevamente.")
        
        login_input = (
            data_json.get("ususis_username") or 
            attrs.get("username") or 
            data_json.get("email")
        )
        password_input = data_json.get("password")
        
        print(f"\n--- DEBUG LOGIN ---")
        print(f"1. Input recibido: {login_input}")

        user_obj = UsuarioSistema.objects.filter(
            Q(ususis_username=login_input) | Q(usu__usu_email=login_input)
        ).first()
        
        if not user_obj:
            print("2. ERROR: Usuario no encontrado.")
            raise serializers.ValidationError("Usuario no encontrado.")

        print(f"2. Usuario encontrado en DB: {user_obj.ususis_username}")

        if not check_password(password_input, user_obj.password):
            print("3. ERROR: Contraseña incorrecta.")
            raise serializers.ValidationError("Contraseña incorrecta.")

        if not user_obj.is_active:
            print("3. ERROR: Cuenta inactiva.")
            raise serializers.ValidationError("Cuenta inactiva.")

        refresh = RefreshToken.for_user(user_obj)
        user_role = user_obj.usu.usu_rol.lower() if user_obj.usu.usu_rol else 'cliente'

        print(f"4. LOGIN EXITOSO. Bienvenido {user_obj.ususis_username} (Rol: {user_role})\n")

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'username': user_obj.ususis_username,
            'role': user_role,
            'user_id': user_obj.usu.usu_id
        }

class CustomTokenObtainPairView(TokenObtainPairView):
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
    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated()]

    def _es_admin(self, user):
        if not user or not user.is_authenticated:
            return False
        usuario = getattr(user, 'usu', None)
        rol = (usuario.usu_rol if usuario else '').strip().lower()
        return rol in ['admin', 'administrador', 'super admin']

    def _serializar_usuario(self, u):
        cuenta = UsuarioSistema.objects.filter(usu=u).first()
        dj_perfil = Dj.objects.filter(usu=u).first()
        estado = cuenta.ususis_estado if cuenta else 'Activo'

        return {
            'usu_id': u.usu_id,
            'usu_nombres': u.usu_nombres or '',
            'usu_apellidos': u.usu_apellidos or '',
            'usu_tipodocumento': u.usu_tipodocumento or 'DNI',
            'usu_numdocumento': u.usu_numdocumento or '',
            'usu_email': u.usu_email or (cuenta.ususis_username if cuenta else ''),
            'usu_telefono': u.usu_telefono or '',
            'usu_fechanacimiento': u.usu_fechanacimiento.strftime('%Y-%m-%d') if u.usu_fechanacimiento else '',
            'usu_rol': u.usu_rol or 'Cliente',
            'usu_fecharegistro': u.usu_fecharegistro.strftime('%d/%m/%Y') if u.usu_fecharegistro else '',
            'estado': estado,  # 'Activo' o 'Inactivo'
            'dj_activo': bool(dj_perfil.dj_activo) if dj_perfil else (estado == 'Activo'),
        }

    def get(self, request, pk=None):
        if pk is not None:
            usuario = Usuario.objects.filter(usu_id=pk).first()
            if not usuario:
                return Response({'detail': 'Usuario no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
            return Response(self._serializar_usuario(usuario), status=status.HTTP_200_OK)

        usuarios = Usuario.objects.all().order_by('-usu_id')
        return Response([self._serializar_usuario(u) for u in usuarios], status=status.HTTP_200_OK)

    def patch(self, request, pk=None):
        if not self._es_admin(request.user):
            return Response(
                {'detail': 'Solo un administrador tiene permiso para modificar estos datos.'},
                status=status.HTTP_403_FORBIDDEN
            )

        usuario = Usuario.objects.filter(usu_id=pk).first()
        if not usuario:
            return Response({'detail': 'Usuario no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data

        # 1. Nombres y Apellidos
        if 'usu_nombres' in data:
            nombres = str(data.get('usu_nombres') or '').strip()
            if not nombres:
                return Response({'detail': 'El nombre no puede estar vacío.'}, status=status.HTTP_400_BAD_REQUEST)
            usuario.usu_nombres = nombres

        if 'usu_apellidos' in data:
            usuario.usu_apellidos = str(data.get('usu_apellidos') or '').strip()

        # 2. Documento (DNI de 8 dígitos u otro documento)
        if 'usu_tipodocumento' in data:
            usuario.usu_tipodocumento = str(data.get('usu_tipodocumento') or 'DNI').strip()[:3]

        if 'usu_numdocumento' in data:
            doc = str(data.get('usu_numdocumento') or '').strip()
            if doc:
                if usuario.usu_tipodocumento == 'DNI' and (len(doc) != 8 or not doc.isdigit()):
                    return Response(
                        {'detail': 'El DNI debe contener exactamente 8 dígitos numéricos.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                if Usuario.objects.filter(usu_numdocumento=doc).exclude(usu_id=usuario.usu_id).exists():
                    return Response(
                        {'detail': 'Ese número de documento ya pertenece a otro usuario.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            usuario.usu_numdocumento = doc

        # 3. Teléfono
        if 'usu_telefono' in data:
            telefono = str(data.get('usu_telefono') or '').strip()
            if telefono and (not telefono.isdigit() or len(telefono) != 9):
                return Response(
                    {'detail': 'El teléfono debe tener 9 dígitos numéricos.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            usuario.usu_telefono = telefono or None

        # 4. Fecha de nacimiento (solo editable por admin una vez que el cliente la registró)
        if 'usu_fechanacimiento' in data:
            fecha_str = str(data.get('usu_fechanacimiento') or '').strip()
            if fecha_str:
                try:
                    usuario.usu_fechanacimiento = datetime.strptime(fecha_str, '%Y-%m-%d').date()
                except ValueError:
                    return Response(
                        {'detail': 'Formato de fecha inválido (use AAAA-MM-DD).'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                usuario.usu_fechanacimiento = None

        # 5. Correo electrónico
        if 'usu_email' in data:
            nuevo_email = str(data.get('usu_email') or '').strip()
            if nuevo_email and nuevo_email != usuario.usu_email:
                if Usuario.objects.filter(usu_email=nuevo_email).exclude(usu_id=usuario.usu_id).exists():
                    return Response(
                        {'detail': 'Este correo ya está registrado por otro usuario.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                cuenta = UsuarioSistema.objects.filter(usu=usuario).first()
                if cuenta and cuenta.ususis_username == usuario.usu_email:
                    if not UsuarioSistema.objects.filter(ususis_username=nuevo_email).exclude(ususis_id=cuenta.ususis_id).exists():
                        cuenta.ususis_username = nuevo_email
                        cuenta.save(update_fields=['ususis_username'])
            usuario.usu_email = nuevo_email or None

        # 6. Cambio de Rol y creación automática de su perfil asociado
        if 'usu_rol' in data:
            nuevo_rol = str(data.get('usu_rol') or '').strip()
            if nuevo_rol:
                usuario.usu_rol = nuevo_rol
                if nuevo_rol == 'Cliente':
                    Cliente.objects.get_or_create(usu=usuario)
                elif nuevo_rol == 'DJ':
                    Dj.objects.get_or_create(usu=usuario, defaults={'dj_activo': 1})
                elif nuevo_rol in ['Admin', 'Asistente']:
                    Administrador.objects.get_or_create(usu=usuario, defaults={'adm_rol': nuevo_rol})

        usuario.save()

        # 7. Habilitar / Deshabilitar cuenta (Admin, DJ, Asistente o Cliente)
        if 'estado' in data:
            nuevo_estado = str(data.get('estado') or '').strip()
            if nuevo_estado in ['Activo', 'Inactivo']:
                cuenta = UsuarioSistema.objects.filter(usu=usuario).first()
                if cuenta:
                    cuenta.ususis_estado = nuevo_estado
                    cuenta.save(update_fields=['ususis_estado'])

                # Si es DJ, sincronizamos su disponibilidad automáticamente
                dj_perfil = Dj.objects.filter(usu=usuario).first()
                if dj_perfil:
                    dj_perfil.dj_activo = 1 if nuevo_estado == 'Activo' else 0
                    dj_perfil.save(update_fields=['dj_activo'])

        return Response(self._serializar_usuario(usuario), status=status.HTTP_200_OK)


class ListaDJsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        djs = Dj.objects.select_related('usu').all().order_by('dj_id')
        resultado = []

        for dj in djs:
            usuario = dj.usu
            cuenta = UsuarioSistema.objects.filter(usu=usuario).first()
            cuenta_activa = (cuenta.ususis_estado == 'Activo') if cuenta else True
            disponible = bool(dj.dj_activo == 1 and cuenta_activa)

            resultado.append({
                'dj_id': dj.dj_id,
                'usu_id': usuario.usu_id,
                'nombre': f"{usuario.usu_nombres} {usuario.usu_apellidos}".strip(),
                'especialidad': dj.dj_especialidad or 'DJ Eventos',
                'disponible': disponible,
                'estado': 'Disponible' if disponible else 'No disponible',
            })

        return Response(resultado, status=status.HTTP_200_OK)

# ==========================================
# 4. GESTIÓN DE VENTAS 
# ==========================================
class ListaVentasView(APIView):
    def get(self, request):
        try:
            ventas_queryset = Venta.objects.all()
            lista_ventas = []
            
            for v in ventas_queryset:
                lista_ventas.append({
                    'ven_id': getattr(v, 'ven_id', None) or v.pk,
                    'cli': v.cli.pk if v.cli else None,
                    'dj': v.dj.pk if v.dj else None,
                    'adm': v.adm.pk if v.adm else None,
                    'loc': v.loc.pk if v.loc else None,
                    'paq': v.paq.pk if v.paq else None,
                    'ven_fechaevento': str(v.ven_fechaevento) if v.ven_fechaevento else None,
                    'ven_duracionhoras': v.ven_duracionhoras,
                    'ven_montototal': float(v.ven_montototal) if v.ven_montototal else 0.0,
                    'ven_referencia': v.ven_referencia,  # <-- CAMBIO AQUÍ
                    'ven_estado': v.ven_estado,
                })
                
            return Response(lista_ventas, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"❌ Error interno en ListaVentasView: {str(e)}")
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM venta")
                columnas = [col[0].lower() for col in cursor.description]
                filas = cursor.fetchall()
                
            lista_ventas = []
            for fila in filas:
                dict_fila = dict(zip(columnas, fila))
                lista_ventas.append({
                    'ven_id': dict_fila.get('ven_id') or dict_fila.get('id'),
                    'cli': dict_fila.get('cli_id'),
                    'dj': dict_fila.get('dj_id'),
                    'adm': dict_fila.get('adm_id'),
                    'loc': dict_fila.get('loc_id') or dict_fila.get('id_local'),
                    'paq': dict_fila.get('paq_id'),
                    'ven_fechaevento': str(dict_fila.get('ven_fechaevento')),
                    'ven_duracionhoras': dict_fila.get('ven_duracionhoras'),
                    'ven_montototal': float(dict_fila.get('ven_montototal') or 0),
                    'ven_referencia': dict_fila.get('ven_referencia'),  # <-- CAMBIO AQUÍ
                    'ven_estado': dict_fila.get('ven_estado'),
                })
            return Response(lista_ventas, status=status.HTTP_200_OK)


# ==========================================
# 5. GESTIÓN DE PAGOS (ESTABILIZADO SIN ERROR DE COLUMNA)
# ==========================================
class ListaPagosView(APIView):
    def get(self, request):
        try:
            pagos_queryset = Pago.objects.all()
            lista_pagos = []
            
            for p in pagos_queryset:
                metodo_desc = "No especificado"
                if hasattr(p, 'metpag') and p.metpag:
                    metodo_desc = getattr(p.metpag, 'metpag_descripcion', "No especificado")
                elif hasattr(p, 'metpag_id') and p.metpag_id:
                    metodo_desc = f"Método {p.metpag_id}"

                lista_pagos.append({
                    'pag_id': p.pk,
                    'ven': p.ven.pk if p.ven else None,
                    'metpag': p.metpag.pk if hasattr(p, 'metpag') and p.metpag else None,
                    'metpag_descripcion': metodo_desc,
                    'pag_monto': float(p.pag_monto) if p.pag_monto else 0.0,
                    'pag_referencia': p.pag_referencia,
                    'pag_estado': p.pag_estado,
                    'pag_fecha': str(p.pag_fecha) if p.pag_fecha else None
                })
                
            return Response(lista_pagos, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"❌ Error interno en ListaPagosView: {str(e)}")
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM pago")
                columnas = [col[0].lower() for col in cursor.description]
                filas = cursor.fetchall()
                
            lista_pagos = []
            for fila in filas:
                dict_fila = dict(zip(columnas, fila))
                lista_pagos.append({
                    'pag_id': dict_fila.get('pag_id') or dict_fila.get('id'),
                    'ven': dict_fila.get('ven_id'),
                    'metpag': dict_fila.get('metpag_id'),
                    'metpag_descripcion': f"Método {dict_fila.get('metpag_id')}",
                    'pag_monto': float(dict_fila.get('pag_monto') or 0),
                    'pag_referencia': dict_fila.get('pag_referencia'),
                    'pag_estado': dict_fila.get('pag_estado'),
                    'pag_fecha': str(dict_fila.get('pag_fecha')),
                })
            return Response(lista_pagos, status=status.HTTP_200_OK)


# ==========================================
# 6. REPORTES INTELIGENTES (IA GRATUITA CON GROQ + LLAMA 3.3)
# ==========================================
class IAVistaPreviaView(APIView):
    def post(self, request):
        if not client_groq:
            return Response(
                {"error": "La API Key de Groq no está configurada en las variables de entorno."}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        prompt_usuario = request.data.get('prompt', '')
        if not prompt_usuario:
            return Response({"error": "El prompt es requerido"}, status=status.HTTP_400_BAD_REQUEST)

        contexto_bd = """
        Eres un asistente experto en SQL para una base de datos MySQL de una agencia de DJs y eventos. Tu única tarea es escribir una consulta SQL válida basada en la petición del usuario.
        
        REGLAS DE ORO PARA LAS TABLAS (Usa estrictamente MINÚSCULAS para los nombres de las TABLAS, pero respeta las mayúsculas exactas de sus CAMPOS):
        
        1. Tabla `usuario` (En minúsculas):
           - Campos exactos: usu_id, usu_nombres, usu_apellidos, usu_email, usu_rol, usu_telefono, usu_tipodocumento, usu_numdocumento

        2. Tabla `dj` (En minúsculas):
           - Campos exactos: DJ_ID, DJ_Especialidad, DJ_Activo, Usu_ID
           - Relación: El campo `Usu_ID` se conecta con `usuario.usu_id`.

        3. Tabla `paquete` (En minúsculas):
           - Campos exactos: Paq_ID, Paq_Nombre, Paq_Precio, Paq_Descripcion, Paq_MaxInvitados, Paq_TiempoHoras

        4. Tabla `venta` (En minúsculas):
           - Campos exactos: Ven_ID, Ven_FechaEvento, Ven_DuracionHoras, Ven_MontoTotal, Ven_Estado, Ven_FechaRegistro, Ven_Direccion, Ven_Distrito, Ven_NombreLugar, Adm_ID, Cli_ID, DJ_ID, Paq_ID
           - Relaciones importantes: 
             * Cli_ID se conecta con usuario.usu_id (Es el Cliente)
             * DJ_ID se conecta con dj.DJ_ID (Es el perfil del DJ)
             * Paq_ID se conecta con paquete.Paq_ID (El paquete elegido de servicios)

        5. Tabla `pago` (En minúsculas):
           - Campos exactos: Pag_ID, Pag_Monto, Pag_Referencia, Pag_Estado, Pag_Fecha, MetPag_ID, Ven_ID
           - Relación: Ven_ID se conecta con venta.Ven_ID

        6. Tabla `metodopago` (En minúsculas):
           - Campos exactos: MetPag_ID, MetPag_Descripcion (Ej: 'Yape', 'Plin', 'Efectivo')
           - Relación: MetPag_ID se conecta con pago.MetPag_ID

        REGLAS CRÍTICAS DE BÚSQUEDA Y RETORNO:
        - Si te piden información sobre qué servicios o paquetes se vendieron más, realiza un INNER JOIN entre `venta` y `paquete` usando `venta.Paq_ID = paquete.Paq_ID`.
        - Si te piden la lista de paquetes disponibles o precios de paquetes, consulta directamente a la tabla `paquete` respetando sus campos reales (`Paq_Nombre`, `Paq_Precio`, etc.).
        - Si el usuario te pide una fecha como "24 de mayo" sin año, busca usando el mes y el día (Ej: WHERE MONTH(Ven_FechaEvento) = 5 AND DAY(Ven_FechaEvento) = 24).
        - Debes responder ÚNICAMENTE con un objeto JSON válido. No saludes, no uses marcas de bloque de código markdown como ```json o texto explicativo adicional.
        - Estructura exacta a retornar: {"sql": "SELECT ... QUERY SQL AQUÍ"}
        - Usa alias amigables en español en el SELECT (ej: SELECT Paq_Nombre AS 'Paquete'...) para que React dibuje la tabla de forma impecable.
        """

        try:
            # 🚀 MODELO ACTUALIZADO: Cambiado a llama-3.3-70b-versatile (Vigente y ultra veloz)
            completion = client_groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": contexto_bd},
                    {"role": "user", "content": f"Genera la consulta SQL para: {prompt_usuario}"}
                ],
                temperature=0.1
            )

            respuesta_ia = completion.choices[0].message.content.strip()

            # Mantenemos las limpiezas de seguridad por si acaso
            if "<think>" in respuesta_ia:
                respuesta_ia = respuesta_ia.split("</think>")[-1].strip()

            if "```" in respuesta_ia:
                if "json" in respuesta_ia:
                    respuesta_ia = respuesta_ia.split("```json")[-1].split("```")[0].strip()
                else:
                    respuesta_ia = respuesta_ia.split("```")[1].split("```")[0].strip()

            datos_json = json.loads(respuesta_ia)
            query_sql = datos_json.get("sql")
            
            print(f"\n🔍 [SQL GENERADO POR LLAMA VIA GROQ]: {query_sql}\n")

            # --- EJECUTAR CONSULTA DINÁMICA ---
            with connection.cursor() as cursor:
                cursor.execute(query_sql)
                columnas = [col[0] for col in cursor.description]
                filas = cursor.fetchall()

            return Response({
                "columnas": columnas,
                "filas": filas
            }, status=status.HTTP_200_OK)

        except json.JSONDecodeError:
            print(f"❌ Falló el parseo de la respuesta de la IA: {respuesta_ia}")
            return Response({"error": "La IA no devolvió un formato de consulta estructurado válido."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print("❌ Error en Reporte con Groq:", str(e))
            return Response({"error": "No se pudo procesar la consulta inteligente en el servidor"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 7. EXPORTACIÓN PROFESIONAL A EXCEL
# ==========================================
class IADescargarExcelView(APIView):
    def post(self, request):
        titulo = request.data.get('titulo', 'Reporte Inteligente')
        columnas = request.data.get('columnas', [])
        filas = request.data.get('filas', [])

        wb = Workbook()
        ws = wb.active
        ws.title = "Reporte Filtrado"

        ws.merge_cells('A1:E1')
        ws['A1'] = titulo
        ws['A1'].font = Font(name='Arial', size=14, bold=True, color='217346')
        ws['A1'].alignment = Alignment(horizontal='left', vertical='center')
        ws.row_dimensions[1].height = 30

        ws.append([]) 
        ws.append(columnas) 

        fill_header = PatternFill(start_color='217346', end_color='217346', fill_type='solid')
        font_header = Font(name='Arial', size=11, bold=True, color='FFFFFF')
        
        for cell in ws[3]:
            cell.fill = fill_header
            cell.font = font_header
            cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[3].height = 24

        font_datos = Font(name='Arial', size=10)
        for fila in filas:
            ws.append(fila)
            for cell in ws[ws.max_row]:
                cell.font = font_datos
                cell.alignment = Alignment(horizontal='left', vertical='center')
            ws.row_dimensions[ws.max_row].height = 20

        for col in ws.columns:
            max_len = 0
            for cell in col:
                valor_str = str(cell.value) if cell.value is not None else ""
                if len(valor_str) > max_len:
                    max_len = len(valor_str)
            
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="Reporte_Inteligente.xlsx"'
        
        wb.save(response)
        return response
    
# ==========================================
# 8. VISTA DE REGISTRO CON ENVÍO DE CORREO (RESEND)
# ==========================================
class RegistroUsuarioView(APIView):
    def post(self, request):
        from .serializers import RegistroSerializer 
        serializer = RegistroSerializer(data=request.data)
        
        if serializer.is_valid():
            # CORRECCIÓN AQUÍ: Pasar el nombre exacto de la variable
            resend.api_key = os.environ.get("RESEND_API_KEY")
            
            usuario_sistema = serializer.save()
            correo_destino = request.data.get('email')
            nombre_usuario = request.data.get('nombre', 'Usuario')
            
            try:
                html_content = f"""
                <div style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; border: 1px solid #eeeeee; border-radius: 8px;">
                    <h2 style="color: #222222;">¡Hola, {nombre_usuario}!</h2>
                    <p>Gracias por registrarte en la plataforma de <strong>Bambo Eventos</strong>.</p>
                    <p>Tu cuenta ha sido creada con éxito. Ya puedes explorar nuestros paquetes, cotizar tu evento y gestionar tus reservas.</p>
                    <br>
                    <p>Saludos cordiales,</p>
                    <p><strong>El equipo de Bambo Eventos</strong></p>
                </div>
                """

                remitente = os.getenv("RESEND_FROM_EMAIL", "Bambo Eventos <contacto@bamboeventos.com>")

                resend.Emails.send({
                    "from": remitente,
                    "to": [correo_destino],
                    "subject": "Confirmacion de registro en Bambo Eventos",
                    "html": html_content
                })
                print(f"📩 [RESEND SUCCESS]: Correo enviado con éxito a {correo_destino}")
                
            except Exception as e:
                print(f"❌ [RESEND ERROR]: No se pudo despachar el correo. Motivo: {str(e)}")

            return Response({
                "message": "✅ Usuario creado con éxito. Revisa tu correo electrónico."
            }, status=status.HTTP_201_CREATED)
        
        print(f"❌ Error en registro: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

# ==========================================
# 9. ASISTENTE VIRTUAL PANDA IA (COTIZACIONES Y PAGOS DIRECTOS)
# ==========================================
class AIChatPublicoView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        api_key_cliente = os.environ.get("GROQ_API_KEY_CLIENTE", "")
        
        if not api_key_cliente:
            return Response(
                {"error": "La API Key de Groq para Clientes no está configurada en las variables de entorno (.env)."}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        mensaje_usuario = request.data.get('mensaje', '')
        if not mensaje_usuario:
            return Response({"error": "El mensaje no puede estar vacío"}, status=status.HTTP_400_BAD_REQUEST)

        # 🧠 El cerebro optimizado y estricto del Panda DJ
        contexto_asistente = """
        Eres 'Panda DJ', el asistente virtual súper carismático e inteligente de 'Bambo Eventos'. Tu único trabajo es orientar a los clientes, cotizar servicios y darles el enlace de pago cuando se decidan por un paquete.

        CUANDO TE PREGUNTEN POR TODOS LOS PRECIOS O PAQUETES EN GENERAL, MOSTRARLOS ASÍ:

        🏡 PARA HOGAR (Hasta 5 horas):
        • PAQUETE BÁSICO 😎 (DJ + Equipo de Sonido + Luces) — S/. 300
        • PAQUETE VIP 🤩⭐ (DJ + Equipo de Sonido + Luces + Animación) — S/. 400
        • PAQUETE PREMIUM 🥳✨ (DJ + Equipo de Sonido + Luces + Animación + Maestro de Ceremonia) — S/. 500

        🏢 PARA LOCALES (Hasta 5 horas):
        • PAQUETE BÁSICO 😎 (DJ + Equipo de Sonido + Luces) — S/. 550
        • PAQUETE VIP 🤩⭐ (DJ + Equipo de Sonido + Luces + Animación) — S/. 650
        • PAQUETE PREMIUM 🥳✨ (DJ + Equipo de Sonido + Luces + Animación + Maestro de Ceremonia) — S/. 750

        REGLAS CRÍTICAS DE COMPORTAMIENTO:
        1. Sé amigable, usa términos de música y pon emojis.
        2. ACCIÓN DIRECTA: Si el cliente ya menciona el paquete y el lugar exacto (ej. "VIP de Hogar", "Básico de Local"), dale su URL de pago correspondiente al instante y dile textualmente: "Haz clic aquí para registrar tu dirección y continuar con tu pago."
        3. REGLA DE FILTRO INCOMPLETO (MUY IMPORTANTE): Si el cliente dice solo el nombre de un paquete a secas sin especificar el lugar (por ejemplo: "vip", "quiero el básico", "premium"), debes responder diciéndole que necesitas saber si es para hogar o local, y mostrarle ÚNICAMENTE las dos opciones de ese paquete específico de la siguiente manera:

           Si dice "VIP", respondes algo como:
           "¡El paquete VIP es una excelente opción! 😎 Pero dime, ¿tu evento será en un hogar o en un local? Aquí tienes las dos opciones para el VIP:
           🏡 VIP Hogar — S/. 400
           🏢 VIP Local — S/. 650"

        4. Obligatorio: Responde ÚNICAMENTE con un objeto JSON válido estructurado con las llaves "respuesta" y "url_pago". No agregues texto fuera del JSON ni uses bloques de código markdown ```json.
        5. El campo "url_pago" será null por defecto a menos que el cliente ya haya elegido paquete y lugar con total precisión.
        
        Mapeo de URLs de redirección (Usa estrictamente estos enlaces en "url_pago" cuando decida comprar con precisión):
        -Hogar Básico -> https://www.bamboeventos.com/pago/1/hogar
        - Hogar VIP -> https://www.bamboeventos.com/pago/2/hogar
        - Hogar Premium -> https://www.bamboeventos.com/pago/3/hogar
        - Local Básico -> https://www.bamboeventos.com/pago/4/local
        - Local VIP -> https://www.bamboeventos.com/pago/5/local
        - Local Premium -> https://www.bamboeventos.com/pago/6/local
        """

        try:
            client_groq_instancia = Groq(api_key=api_key_cliente)

            completion = client_groq_instancia.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": contexto_asistente},
                    {"role": "user", "content": mensaje_usuario}
                ],
                temperature=0.2  # Bajamos un poco la temperatura para que sea más estricto con el JSON
            )

            respuesta_cruda = completion.choices[0].message.content.strip()

            # Sistema de limpieza anti-markdown redundante
            if "```" in respuesta_cruda:
                if "json" in respuesta_cruda:
                    respuesta_cruda = respuesta_cruda.split("```json")[-1].split("```")[0].strip()
                else:
                    respuesta_cruda = respuesta_cruda.split("```")[1].split("```")[0].strip()

            # 🔥 CONTROL DE ERRORES MEJORADO: Si por alguna razón Groq no devuelve JSON válido, lo empaquetamos a la fuerza
            try:
                datos_respuesta = json.loads(respuesta_cruda)
            except json.JSONDecodeError:
                print("⚠️ La IA no devolvió un JSON perfecto, aplicando empaquetado forzado.")
                datos_respuesta = {
                    "respuesta": respuesta_cruda,
                    "url_pago": None
                }

            return Response(datos_respuesta, status=status.HTTP_200_OK)

        except Exception as e:
            print("❌ Error real capturado en Panda IA Chat:", str(e))
            return Response({
                "respuesta": "¡Ups! Tuve un pequeño cruce de cables en mis consolas de DJ. ¿Podrías repetirme la pregunta, por favor?",
                "url_pago": None
            }, status=status.HTTP_200_OK)
            
# ==========================================
# 10. AUTENTICACIÓN CON GOOGLE OAUTH
# ==========================================
class GoogleLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({"error": "Token de Google no proporcionado"}, status=status.HTTP_400_BAD_REQUEST)

        # Validar el token directamente con los servidores de Google
        google_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"
        res = requests.get(google_url)

        if res.status_code != 200:
            return Response({"error": "Token de Google inválido"}, status=status.HTTP_400_BAD_REQUEST)

        user_data = res.json()
        email = user_data.get('email')
        first_name = user_data.get('given_name', '')
        last_name = user_data.get('family_name', '')

        if not email:
            return Response({"error": "No se pudo obtener el correo de Google"}, status=status.HTTP_400_BAD_REQUEST)

        # Buscar o crear el usuario en la base de datos
        with transaction.atomic():
            usu = Usuario.objects.filter(usu_email=email).first()
            if not usu:
                usu = Usuario.objects.create(
                    usu_nombres=first_name,
                    usu_apellidos=last_name,
                    usu_email=email,
                    usu_rol='cliente'
                )

            user_obj = UsuarioSistema.objects.filter(usu=usu).first()
            if not user_obj:
                base_username = email.split('@')[0]
                username = base_username
                counter = 1
                while UsuarioSistema.objects.filter(ususis_username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                user_obj = UsuarioSistema.objects.create(
                    ususis_username=username,
                    usu=usu,
                )
                user_obj.set_unusable_password()
                user_obj.save()

        # Generar tokens JWT del sistema
        refresh = RefreshToken.for_user(user_obj)
        user_role = user_obj.usu.usu_rol.lower() if user_obj.usu.usu_rol else 'cliente'

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'username': user_obj.ususis_username,
            'role': user_role,
            'user_id': user_obj.usu.usu_id
        }, status=status.HTTP_200_OK)
        
        
# ==========================================
# 11. Perfil
# ==========================================
        
class PerfilUsuarioView(APIView):
    permission_classes = [IsAuthenticated]

    def _dni_valido_registrado(self, dni):
        dni_limpio = (dni or '').strip()
        return len(dni_limpio) == 8 and dni_limpio.isdigit() and dni_limpio != '00000000'

    def get(self, request):
        usuario = getattr(request.user, 'usu', None)
        if not usuario:
            return Response(
                {'detail': 'No se encontró un perfil asociado a esta cuenta.'},
                status=status.HTTP_404_NOT_FOUND
            )

        dni_registrado = self._dni_valido_registrado(usuario.usu_numdocumento)
        fecha_registro = (
            usuario.usu_fecharegistro.strftime('%d/%m/%Y')
            if usuario.usu_fecharegistro else ''
        )
        fecha_nacimiento = (
            usuario.usu_fechanacimiento.strftime('%Y-%m-%d')
            if usuario.usu_fechanacimiento else ''
        )

        return Response({
            'nombre': usuario.usu_nombres or '',
            'apellido': usuario.usu_apellidos or '',
            'email': usuario.usu_email or request.user.ususis_username or '',
            'telefono': usuario.usu_telefono or '',
            'dni': usuario.usu_numdocumento.strip() if dni_registrado else '',
            'dni_bloqueado': dni_registrado,
            'fecha_nacimiento': fecha_nacimiento,
            'fecha_nacimiento_bloqueada': bool(usuario.usu_fechanacimiento),
            'fecha_registro': fecha_registro,
            'rol': usuario.usu_rol or 'Cliente',
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        usuario = getattr(request.user, 'usu', None)
        if not usuario:
            return Response(
                {'detail': 'No se encontró un perfil asociado a esta cuenta.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # 1. Teléfono (siempre editable por el cliente)
        if 'telefono' in request.data:
            telefono = str(request.data.get('telefono') or '').strip()
            if telefono and (not telefono.isdigit() or len(telefono) != 9):
                return Response(
                    {'detail': 'El número de teléfono debe tener 9 dígitos numéricos.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            usuario.usu_telefono = telefono or None

        # 2. DNI (8 dígitos, solo editable una vez si aún no está registrado)
        dni_ya_bloqueado = self._dni_valido_registrado(usuario.usu_numdocumento)
        if 'dni' in request.data:
            nuevo_dni = str(request.data.get('dni') or '').strip()
            if dni_ya_bloqueado:
                if nuevo_dni and nuevo_dni != usuario.usu_numdocumento.strip():
                    return Response(
                        {'detail': 'El DNI ya fue registrado y solo puede ser modificado por un administrador.'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            elif nuevo_dni:
                if not (len(nuevo_dni) == 8 and nuevo_dni.isdigit()) or nuevo_dni == '00000000':
                    return Response(
                        {'detail': 'El DNI debe contener exactamente 8 dígitos numéricos.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                if Usuario.objects.filter(usu_numdocumento=nuevo_dni).exclude(usu_id=usuario.usu_id).exists():
                    return Response(
                        {'detail': 'Este número de DNI ya está asociado a otra cuenta.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                usuario.usu_tipodocumento = 'DNI'
                usuario.usu_numdocumento = nuevo_dni

        # 3. Fecha de Nacimiento (solo editable una vez si aún es NULL)
        if 'fecha_nacimiento' in request.data:
            nueva_fecha = str(request.data.get('fecha_nacimiento') or '').strip()
            if usuario.usu_fechanacimiento:
                if nueva_fecha and nueva_fecha != usuario.usu_fechanacimiento.strftime('%Y-%m-%d'):
                    return Response(
                        {'detail': 'La fecha de nacimiento ya fue registrada y solo puede ser modificada por un administrador.'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            elif nueva_fecha:
                try:
                    fecha_parseada = datetime.strptime(nueva_fecha, '%Y-%m-%d').date()
                    if fecha_parseada >= datetime.now().date():
                        return Response(
                            {'detail': 'La fecha de nacimiento no puede ser actual o futura.'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    usuario.usu_fechanacimiento = fecha_parseada
                except ValueError:
                    return Response(
                        {'detail': 'Formato de fecha de nacimiento inválido.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

        usuario.save()

        dni_final_bloqueado = self._dni_valido_registrado(usuario.usu_numdocumento)
        return Response({
            'nombre': usuario.usu_nombres or '',
            'apellido': usuario.usu_apellidos or '',
            'email': usuario.usu_email or '',
            'telefono': usuario.usu_telefono or '',
            'dni': usuario.usu_numdocumento.strip() if dni_final_bloqueado else '',
            'dni_bloqueado': dni_final_bloqueado,
            'fecha_nacimiento': usuario.usu_fechanacimiento.strftime('%Y-%m-%d') if usuario.usu_fechanacimiento else '',
            'fecha_nacimiento_bloqueada': bool(usuario.usu_fechanacimiento),
        }, status=status.HTTP_200_OK)