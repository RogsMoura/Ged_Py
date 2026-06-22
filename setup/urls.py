from django.contrib import admin
from django.urls import path, include # Adicionamos o 'include' aqui

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')), # Isso inclui todas as URLs do seu app core na raiz do site
]