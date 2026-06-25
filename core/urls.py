from django.urls import path
from . import views

urlpatterns = [
    path('navegar/excluir-multiplos-ajax/', views.excluir_multiplos_ajax, name='excluir_multiplos_ajax'),
    path('navegar/<str:modulo>/', views.navegar_pastas, name='navegar_pastas'),
    path('', views.inicio, name='inicio'),
    path('busca/', views.busca_crf, name='busca_crf'),
    path('visualizar/', views.visualizar_arquivo, name='visualizar_arquivo'), 
    path('baixar/', views.baixar_arquivo, name='baixar_arquivo'), 
    path('renomear/', views.renomear_arquivo, name='renomear_arquivo'),
    path('apagar/', views.apagar_arquivo, name='apagar_arquivo'),
    path('upload/', views.upload_arquivo, name='upload_arquivo'),
    path('upload-geral/', views.upload_arquivo_geral, name='upload_arquivo_geral'),
    path('criar-pasta/', views.criar_subpasta, name='criar_subpasta'),
    path('lixeira/', views.ver_lixeira, name='ver_lixeira'),
    path('lixeira/restaurar/', views.restaurar_arquivo, name='restaurar_arquivo'),
    path('lixeira/esvaziar/', views.esvaziar_lixeira, name='esvaziar_lixeira'),
    path('auditoria/', views.ver_auditoria, name='ver_auditoria'),
    path('upload-multiplo-ajax/', views.upload_multiplo_ajax, name='upload_multiplo_ajax'),
    path('', views.pagina_inicial_direcionamento, name='inicio_sistema'),
]