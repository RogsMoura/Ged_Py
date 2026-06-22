from django.db import models
from django.contrib.auth.models import User

# 1. Cadastro dos 12 Setores do CRF-PB
class Setor(models.Model):
    nome = models.CharField(max_length=100, unique=True, verbose_name="Nome do Setor")
    caminho_rede = models.CharField(max_length=255, verbose_name="Caminho na Rede (UNC)") # Ex: \\ti-pc02\GED D\SETORES\ALMOXARIFADO
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Setor"
        verbose_name_plural = "Setores"

    def __str__(self):
        return self.nome

# 2. Pastas dos Prontuários (Pessoa Física e Jurídica)
class Prontuario(models.Model):
    TIPO_CHOICES = [
        ('PF', 'Pessoa Física'),
        ('PJ', 'Pessoa Jurídica'),
    ]
    numero_crf = models.CharField(max_length=20, unique=True, verbose_name="Número do CRF") # Ex: 08360
    tipo = models.CharField(max_length=2, choices=TIPO_CHOICES, verbose_name="Tipo de Inscrição")
    caminho_pasta = models.CharField(max_length=255, verbose_name="Caminho da Pasta") # Ex: \\ti-pc02\GED D\GED\PESSOA FISICA\08360
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Prontuário"
        verbose_name_plural = "Prontuários"

    def __str__(self):
        return f"CRF {self.numero_crf} ({self.get_tipo_display()})"

# 3. Registro dos Arquivos/Documentos
class Documento(models.Model):
    nome_arquivo = models.CharField(max_length=255, verbose_name="Nome do Arquivo")
    caminho_arquivo = models.CharField(max_length=255, verbose_name="Caminho do Arquivo") # Caminho completo até o PDF
    tamanho_bytes = models.BigIntegerField(null=True, blank=True, verbose_name="Tamanho (Bytes)")
    
    # O documento pode pertencer a um Setor OU a um Prontuário de CRF
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, null=True, blank=True, related_name="documentos")
    prontuario = models.ForeignKey(Prontuario, on_delete=models.CASCADE, null=True, blank=True, related_name="documentos")
    
    # Log básico acoplado ao documento
    criado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Inserido por")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data de Inclusão")

    class Meta:
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"

    def __str__(self):
        return self.nome_arquivo

# 4. Registro de Logs  
class LogAuditoria(models.Model):
    ACOES_CHOICES = [
        ('UPLOAD', 'Upload de Arquivo'),
        ('CRIAR_PASTA', 'Criação de Subpasta'),
        ('RENOMEAR', 'Renomear Item'),
        ('APAGAR', 'Mover para Lixeira'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Usuário")
    acao = models.CharField(max_length=20, choices=ACOES_CHOICES, verbose_name="Ação")
    descricao = models.TextField(verbose_name="Descrição do Evento")
    data_hora = models.DateTimeField(auto_now_add=True, verbose_name="Data e Hora")
    caminho_item = models.TextField(verbose_name="Caminho do Arquivo/Pasta", null=True, blank=True)

    class Meta:
        verbose_name = "Log de Auditoria"
        verbose_name_plural = "Logs de Auditoria"
        ordering = ['-data_hora'] # Mostra sempre os mais recentes primeiro

    def __str__(self):
        user_str = self.usuario.username if self.usuario else "Sistema"
        return f"{user_str} - {self.get_acao_display()} ({self.data_hora.strftime('%d/%m/%Y %H:%M')})"