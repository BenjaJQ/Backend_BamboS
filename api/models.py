from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db.models.signals import post_save
from django.dispatch import receiver

# ==========================================
# 1. MANAGER PARA USUARIOSISTEMA
# ==========================================
class UsuarioSistemaManager(BaseUserManager):
    def get_by_natural_key(self, username):
        return self.get(**{self.model.USERNAME_FIELD: username})

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('El username es obligatorio')
        
        # Creamos el objeto sin el password directo para que no choque
        user = self.model(ususis_username=username, **extra_fields)
        
        # set_password encripta la clave y la guarda en el campo 'password' 
        # (que está vinculado a la columna UsuSis_Password)
        if password:
            user.set_password(password)
        
        user.save(using=self._db)
        return user

# ==========================================
# 2. TABLAS BASE
# ==========================================
class Usuario(models.Model):
    usu_id = models.AutoField(db_column='Usu_ID', primary_key=True)
    usu_nombres = models.CharField(db_column='Usu_Nombres', max_length=100)
    usu_apellidos = models.CharField(db_column='Usu_Apellidos', max_length=100)
    usu_tipodocumento = models.CharField(db_column='Usu_TipoDocumento', max_length=3)
    usu_numdocumento = models.CharField(db_column='Usu_NumDocumento', max_length=20)
    # Cambio: Añadido unique=True para permitir login por correo
    usu_email = models.CharField(db_column='Usu_Email', max_length=100, blank=True, null=True, unique=True)
    usu_telefono = models.CharField(db_column='Usu_Telefono', max_length=20, blank=True, null=True)
    usu_rol = models.CharField(db_column='Usu_Rol', max_length=50, default='Cliente')
    usu_fecharegistro = models.DateTimeField(db_column='Usu_FechaRegistro', auto_now_add=True, null=True)

    class Meta:
        managed = True
        db_table = 'usuario'

    def __str__(self):
        return f"{self.usu_nombres} {self.usu_apellidos}"

class Administrador(models.Model):
    adm_id = models.AutoField(db_column='Adm_ID', primary_key=True)
    usu = models.ForeignKey(Usuario, models.DO_NOTHING, db_column='Usu_ID')
    adm_rol = models.CharField(db_column='Adm_Rol', max_length=50, blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'administrador'

class Cliente(models.Model):
    cli_id = models.AutoField(db_column='Cli_ID', primary_key=True)
    usu = models.ForeignKey(Usuario, models.DO_NOTHING, db_column='Usu_ID')
    cli_observaciones = models.TextField(db_column='Cli_Observaciones', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'cliente'

class Dj(models.Model):
    dj_id = models.AutoField(db_column='DJ_ID', primary_key=True)
    usu = models.ForeignKey(Usuario, models.DO_NOTHING, db_column='Usu_ID')
    dj_especialidad = models.CharField(db_column='DJ_Especialidad', max_length=100, blank=True, null=True)
    dj_activo = models.IntegerField(db_column='DJ_Activo', blank=True, null=True, default=1)

    class Meta:
        managed = True
        db_table = 'dj'

# ==========================================
# 3. SISTEMA DE AUTENTICACIÓN (CORREGIDO PARA MySQL)
# ==========================================
class UsuarioSistema(AbstractBaseUser):
    objects = UsuarioSistemaManager()

    ususis_id = models.AutoField(db_column='UsuSis_ID', primary_key=True)
    usu = models.ForeignKey(Usuario, models.DO_NOTHING, db_column='Usu_ID')
    ususis_username = models.CharField(db_column='UsuSis_Username', max_length=100, unique=True)
    
    # SOLUCIÓN AL ERROR 1054: 
    # Definimos el campo 'password' que Django busca internamente, 
    # pero apuntando a tu columna real 'UsuSis_Password'
    password = models.CharField(db_column='UsuSis_Password', max_length=255)
    
    ususis_estado = models.CharField(db_column='UsuSis_Estado', max_length=8, default='Activo')

    USERNAME_FIELD = 'ususis_username'
    REQUIRED_FIELDS = []

    last_login = None 

    @property
    def id(self): return self.ususis_id

    @property
    def is_staff(self): return True

    @property
    def is_active(self): return self.ususis_estado == 'Activo'

    class Meta:
        managed = True
        db_table = 'usuario_sistema'

    def has_perm(self, perm, obj=None): return True
    def has_module_perms(self, app_label): return True

# ==========================================
# 4. TABLAS DE NEGOCIO (LOCAL, PAQUETE, VENTA, etc.)
# ==========================================
class Local(models.Model):
    loc_id = models.AutoField(db_column='Loc_ID', primary_key=True)
    loc_nombre = models.CharField(db_column='Loc_Nombre', max_length=100)
    loc_direccion = models.CharField(db_column='Loc_Direccion', max_length=150, blank=True, null=True)
    loc_distrito = models.CharField(db_column='Loc_Distrito', max_length=100, blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'local'

class Paquete(models.Model):
    paq_id = models.AutoField(db_column='Paq_ID', primary_key=True)
    paq_nombre = models.CharField(db_column='Paq_Nombre', max_length=100)
    paq_precio = models.DecimalField(db_column='Paq_Precio', max_digits=10, decimal_places=2)
    paq_descripcion = models.TextField(db_column='Paq_Descripcion', blank=True, null=True)
    paq_maxinvitados = models.IntegerField(db_column='Paq_MaxInvitados', blank=True, null=True)
    paq_tiempohoras = models.IntegerField(db_column='Paq_TiempoHoras', blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'paquete'

class Venta(models.Model):
    ven_id = models.AutoField(db_column='Ven_ID', primary_key=True)
    cli = models.ForeignKey(Cliente, models.DO_NOTHING, db_column='Cli_ID')
    dj = models.ForeignKey(Dj, models.DO_NOTHING, db_column='DJ_ID')
    adm = models.ForeignKey(Administrador, models.DO_NOTHING, db_column='Adm_ID')
    loc = models.ForeignKey(Local, models.DO_NOTHING, db_column='Loc_ID')
    paq = models.ForeignKey(Paquete, models.DO_NOTHING, db_column='Paq_ID')
    ven_fechaevento = models.DateField(db_column='Ven_FechaEvento')
    ven_duracionhoras = models.IntegerField(db_column='Ven_DuracionHoras')
    ven_montototal = models.DecimalField(db_column='Ven_MontoTotal', max_digits=10, decimal_places=2)
    ven_estado = models.CharField(db_column='Ven_Estado', max_length=10, blank=True, null=True)
    ven_fecharegistro = models.DateTimeField(db_column='Ven_FechaRegistro', blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'venta'

class Documento(models.Model):
    doc_id = models.AutoField(db_column='Doc_ID', primary_key=True)
    ven = models.ForeignKey(Venta, models.DO_NOTHING, db_column='Ven_ID')
    doc_tipo = models.CharField(db_column='Doc_Tipo', max_length=7)
    doc_serie = models.CharField(db_column='Doc_Serie', max_length=10)
    doc_correlativo = models.IntegerField(db_column='Doc_Correlativo')
    doc_fechaemision = models.DateTimeField(db_column='Doc_FechaEmision', blank=True, null=True)
    doc_monto = models.DecimalField(db_column='Doc_Monto', max_digits=10, decimal_places=2)
    doc_estado = models.CharField(db_column='Doc_Estado', max_length=7, blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'documento'
        unique_together = (('doc_serie', 'doc_correlativo'),)

class Boleta(models.Model):
    bol_id = models.AutoField(db_column='Bol_ID', primary_key=True)
    doc = models.ForeignKey(Documento, models.DO_NOTHING, db_column='Doc_ID')
    bol_tipodocumento = models.CharField(db_column='Bol_TipoDocumento', max_length=3)
    bol_numdocumento = models.CharField(db_column='Bol_NumDocumento', max_length=20)
    bol_nombrecliente = models.CharField(db_column='Bol_NombreCliente', max_length=150)
    class Meta:
        managed = True
        db_table = 'boleta'

class Factura(models.Model):
    fac_id = models.AutoField(db_column='Fac_ID', primary_key=True)
    doc = models.ForeignKey(Documento, models.DO_NOTHING, db_column='Doc_ID')
    fac_ruc = models.CharField(db_column='Fac_RUC', max_length=20)
    fac_razonsocial = models.CharField(db_column='Fac_RazonSocial', max_length=150)
    fac_direccionfiscal = models.CharField(db_column='Fac_DireccionFiscal', max_length=200, blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'factura'

class MetodoPago(models.Model):
    metpag_id = models.AutoField(db_column='MetPag_ID', primary_key=True)
    metpag_descripcion = models.CharField(db_column='MetPag_Descripcion', max_length=50)
    class Meta:
        managed = True
        db_table = 'metodo_pago'

class Pago(models.Model):
    pag_id = models.AutoField(db_column='Pag_ID', primary_key=True)
    ven = models.ForeignKey(Venta, models.DO_NOTHING, db_column='Ven_ID')
    metpag = models.ForeignKey(MetodoPago, models.DO_NOTHING, db_column='MetPag_ID')
    pag_monto = models.DecimalField(db_column='Pag_Monto', max_digits=10, decimal_places=2)
    pag_referencia = models.CharField(db_column='Pag_Referencia', max_length=100, blank=True, null=True)
    pag_estado = models.CharField(db_column='Pag_Estado', max_length=9, blank=True, null=True)
    pag_fecha = models.DateTimeField(db_column='Pag_Fecha', blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'pago'

class RegistroEvento(models.Model):
    regeve_id = models.AutoField(db_column='RegEve_ID', primary_key=True)
    ven = models.ForeignKey(Venta, models.DO_NOTHING, db_column='Ven_ID')
    regeve_nombrelugar = models.CharField(db_column='RegEve_NombreLugar', max_length=100, blank=True, null=True)
    regeve_fecha = models.DateField(db_column='RegEve_Fecha', blank=True, null=True)
    regeve_duracionhoras = models.IntegerField(db_column='RegEve_DuracionHoras', blank=True, null=True)
    regeve_cliente = models.CharField(db_column='RegEve_Cliente', max_length=150, blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'registro_evento'

class Evaluacion(models.Model):
    eva_id = models.AutoField(db_column='Eva_ID', primary_key=True)
    ven = models.ForeignKey(Venta, models.DO_NOTHING, db_column='Ven_ID')
    eva_tipo = models.CharField(db_column='Eva_Tipo', max_length=7)
    eva_calificacion = models.JSONField(db_column='Eva_Calificacion', blank=True, null=True)
    eva_comentario = models.TextField(db_column='Eva_Comentario', blank=True, null=True)
    class Meta:
        managed = True
        db_table = 'evaluacion'

# ==========================================
# 5. SIGNALS AUTOMÁTICOS
# ==========================================
@receiver(post_save, sender=Usuario)
def crear_perfil_segun_rol(sender, instance, created, **kwargs):
    if created:
        if instance.usu_rol == 'Cliente':
            Cliente.objects.get_or_create(usu=instance)
        elif instance.usu_rol == 'DJ':
            Dj.objects.get_or_create(usu=instance)
        elif instance.usu_rol in ['Admin', 'Asistente']:
            Administrador.objects.get_or_create(usu=instance, adm_rol=instance.usu_rol)