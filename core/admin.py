from django.contrib import admin
from .models import Setor, Prontuario, Documento

@admin.register(Setor)
class SetorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'caminho_rede', 'criado_em')
    search_fields = ('nome',)

@admin.register(Prontuario)
class ProntuarioAdmin(admin.ModelAdmin):
    list_display = ('numero_crf', 'tipo', 'caminho_pasta', 'atualizado_em')
    list_filter = ('tipo',)
    search_fields = ('numero_crf',)

@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('nome_arquivo', 'setor', 'prontuario', 'criado_por', 'criado_em')
    search_fields = ('nome_arquivo', 'prontuario__numero_crf')