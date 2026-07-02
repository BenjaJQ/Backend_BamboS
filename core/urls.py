"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

# Importamos todas las vistas necesarias desde api.views
from api.views import (
    CustomTokenObtainPairView, 
    RegistroUsuarioView, 
    ListaUsuariosView,
    ListaVentasView,  
    ListaPagosView,   
    IAVistaPreviaView,        
    IADescargarExcelView,
    AIChatPublicoView  # 👈 Asegúrate de agregar esta coma y la vista aquí
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Ruta para el Login (JWT + Roles)
    path('api/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    
    # Ruta para refrescar el token de acceso
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Ruta para procesar el registro desde tu formulario de React
    path('api/registro/', RegistroUsuarioView.as_view(), name='registro_usuario'),
    
    # Rutas para la Gestión de Usuarios
    path('api/usuarios/', ListaUsuariosView.as_view(), name='lista_usuarios'),
    path('api/usuarios/<int:pk>/', ListaUsuariosView.as_view(), name='detalle_usuario'),
    
    # NUEVAS RUTAS: Para solucionar el error 404 en el Dashboard
    path('api/ventas/', ListaVentasView.as_view(), name='lista_ventas'),
    path('api/pagos/', ListaPagosView.as_view(), name='lista_pagos'),
    path('api/reportes/ia-vista-previa/', IAVistaPreviaView.as_view(), name='ia_vista_previa'),
    path('api/reportes/ia-descargar-excel/', IADescargarExcelView.as_view(), name='ia_descargar_excel'),
    path('api/chat-publico/', AIChatPublicoView.as_view(), name='chat_publico'),
]