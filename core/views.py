import os
import mimetypes
import shutil
import urllib.parse
import re
import json

from django.views.decorators.clickjacking import xframe_options_exempt
from django.db.models import Q
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError


from datetime import datetime

from .models import LogAuditoria

# ==========================================
# TRAVA DE SEGURANÇA (PATH TRAVERSAL)
# ==========================================
def validar_caminho_seguro(caminho_alvo):
    """
    Garante que o caminho solicitado está estritamente dentro das pastas permitidas do projeto.
    Se alguém tentar burlar, o sistema bloqueia na hora.
    """
    if not caminho_alvo:
        raise PermissionDenied("Acesso negado: Caminho vazio.")
        
    # Normaliza os caminhos para evitar truques com barras invertidas ou relativas
    caminho_real = os.path.realpath(caminho_alvo)
    
    # Define os caminhos permitidos no HD
    ged_raiz = os.path.realpath(settings.GED_BASE_DIR)
    setores_raiz = os.path.realpath(os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'setores'))
    lixeira_raiz = os.path.realpath(os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'lixeira')) # INCLUÍDO
    
    # Verifica se o caminho solicitado começa com a raiz do GED, dos Setores ou da Lixeira
    if caminho_real.startswith(ged_raiz) or caminho_real.startswith(setores_raiz) or caminho_real.startswith(lixeira_raiz):
        return True
        
    # Se não estiver em nenhum dos locais permitidos, levanta o erro de segurança
    raise PermissionDenied("Acesso negado: Tentativa de violação de diretório detectada.")
    raise PermissionDenied("Acesso negado: Tentativa de violação de diretório detectada.")


# ==========================================
# VIEWS DO SISTEMA
# ==========================================
@login_required
def inicio(request):
    return render(request, 'core/inicio.html')

def pagina_inicial_direcionamento(request):
    """Se logado, vai para o painel. Se não, vai para o login."""
    if request.user.is_authenticated:
        return redirect('painel_controle')  # Coloque o name da sua view do painel
    return redirect('login')  # Coloque o name da sua view de login (ou auth_login)

@login_required
def busca_crf(request):
    termo_busca = request.GET.get('crf', '').strip()
    resultados = []
    pasta_encontrada = False
    caminho_pf = os.path.join(settings.GED_BASE_DIR, 'pessoa fisica', termo_busca)

    if termo_busca:
        # Aplica a trava de segurança na busca por CRF
        validar_caminho_seguro(caminho_pf)
        
        if os.path.exists(caminho_pf):
            pasta_encontrada = True
            for item in os.listdir(caminho_pf):
                caminho_completo = os.path.join(caminho_pf, item)
                
                if os.path.isfile(caminho_completo):
                    tamanho = round(os.path.getsize(caminho_completo) / 1024, 2)
                    nome_minusculo = item.lower()
                    
                    if nome_minusculo.endswith('.pdf'):
                        tipo_arquivo = 'pdf'
                    elif nome_minusculo.endswith(('.xls', '.xlsx', '.csv')):
                        tipo_arquivo = 'excel'
                    elif nome_minusculo.endswith(('.doc', '.docx')):
                        tipo_arquivo = 'word'
                    elif nome_minusculo.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        tipo_arquivo = 'imagem'
                    else:
                        tipo_arquivo = 'outro'
                        
                    resultados.append({
                        'nome': item,
                        'tipo': tipo_arquivo,
                        'tamanho': f"{tamanho} KB",
                        'caminho': caminho_completo
                    })
                elif os.path.isdir(caminho_completo):
                    resultados.append({
                        'nome': item,
                        'tipo': 'pasta',
                        'tamanho': '-',
                        'caminho': caminho_completo
                    })

    contexto = {
        'resultados': resultados,
        'termo_busca': termo_busca,
        'pasta_encontrada': pasta_encontrada,
        'caminho_pasta_atual': caminho_pf
    }
    return render(request, 'core/busca.html', contexto)

@xframe_options_exempt
@login_required
def visualizar_arquivo(request):
    caminho_usuario = request.GET.get('caminho', '')
    
    try:
        # Tenta validar o caminho
        caminho_seguro = validar_caminho_seguro(caminho_usuario)
    except PermissionDenied:
        # Se for um ataque ou tentativa de sair da pasta, cai aqui
        return HttpResponse("Acesso negado: Tentativa de invasão detectada.", status=403)

    # Verifica se o arquivo existe após validar o caminho
    if not os.path.exists(caminho_seguro):
        raise Http404("Arquivo não encontrado.")
    
    # O caminho vem do link que montamos no HTML
    caminho_arquivo = request.GET.get('caminho', '')
    
    # IMPORTANTE: Garanta que o caminho seja absoluto e seguro
    # Ajuste o caminho base se o seu projeto usa outra pasta raiz
    if os.path.exists(caminho_arquivo):
        with open(caminho_arquivo, 'rb') as pdf:
            response = HttpResponse(pdf.read(), content_type='application/pdf')
            # 'inline' força o navegador a abrir no visualizador, não baixar
            response['Content-Disposition'] = 'inline; filename="%s"' % os.path.basename(caminho_arquivo)
            return response
    
    raise Http404("Arquivo não encontrado no servidor.")

@login_required
def baixar_arquivo(request):
    caminho_completo = request.GET.get('caminho', '')
    caminho_final = urllib.parse.unquote(caminho_completo)

    # Injeção do Passo 12.2
    validar_caminho_seguro(caminho_final)
    
    if os.path.exists(caminho_final) and "ged_teste" in caminho_final:
        arquivo = open(caminho_final, 'rb')
        return FileResponse(arquivo, as_attachment=True)
    
    raise Http404("Arquivo não encontrado.")

@login_required
def renomear_arquivo(request):
    if request.method == 'POST':
        caminho_atual = request.POST.get('caminho_atual', '')
        novo_nome = request.POST.get('novo_nome', '').strip()
        crf = request.POST.get('crf', '')

        # Injeção do Passo 12.2
        validar_caminho_seguro(caminho_atual)

        if not novo_nome.endswith('.pdf') and os.path.isfile(caminho_atual):
            novo_nome += '.pdf'

        pasta_pai = os.path.dirname(caminho_atual)
        caminho_novo = os.path.join(pasta_pai, novo_nome)
        
        # Valida também o destino planejado para o arquivo
        validar_caminho_seguro(caminho_novo)

        if os.path.exists(caminho_atual) and "ged_teste" in caminho_atual:
            try:
                os.rename(caminho_atual, caminho_novo)
                messages.success(request, f"Renomeado para '{novo_nome}' com sucesso!")
            except Exception as e:
                messages.error(request, f"Erro ao renomear: {str(e)}")
        
        if crf == 'bypass':
            url_retorno = request.GET.get('next')
            if url_retorno:
                return redirect(url_retorno)
            return redirect('/inicio/')
            
        return redirect(f"/busca/?crf={crf}")

@login_required
def apagar_arquivo(request):
    if request.method == 'POST':
        caminho_atual = request.POST.get('caminho_atual', '').strip()
        crf = request.POST.get('crf', '').strip()
        
        caminho_atual = os.path.normpath(caminho_atual)
        
        # Validação de Segurança do Passo 12
        validar_caminho_seguro(caminho_atual)
        
        nome_item = os.path.basename(caminho_atual)

        # Define a pasta da lixeira baseada no diretório correto do projeto
        pasta_lixeira = os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'lixeira')
        if not os.path.exists(pasta_lixeira):
            os.makedirs(pasta_lixeira)

        caminho_lixeira = os.path.normpath(os.path.join(pasta_lixeira, nome_item))

        # Ajustado para aceitar tanto ged_teste quanto ged_crfpb de forma segura
        if os.path.exists(caminho_atual) and ("ged_teste" in caminho_atual or "ged_crfpb" in caminho_atual):
            try:
                # Determina se é arquivo ou pasta para gerar a mensagem correta
                tipo_item = "pasta" if os.path.isdir(caminho_atual) else "arquivo"
                
                # Move fisicamente (funciona para arquivos e pastas completas)
                shutil.move(caminho_atual, caminho_lixeira)
                
                # ==========================================
                # INJEÇÃO CRUCIAL: GRAVAÇÃO DO LOG DE AUDITORIA
                # ==========================================
                LogAuditoria.objects.create(
                    usuario=request.user,
                    acao='APAGAR',
                    descricao=nome_item,  # Nome puro usado para o cruzamento de dados
                    caminho_item=caminho_atual  # Guarda o caminho de origem completo para a restauração
                )
                
                messages.success(request, f"O/A {tipo_item} '{nome_item}' foi movido(a) para a lixeira!")
            except Exception as e:
                messages.error(request, f"Erro físico ao mover para a lixeira: {str(e)}")
        else:
            messages.error(request, "Item não encontrado ou fora do diretório permitido.")

        # Fluxo de redirecionamento original mantido
        if crf == 'bypass':
            url_retorno = request.GET.get('next')
            if url_retorno:
                return redirect(url_retorno)
            return redirect('/inicio/')

        return redirect(f"/busca/?crf={crf}")

@login_required
def upload_arquivo(request):
    if request.method == 'POST' and request.FILES.get('arquivo_novo'):
        crf = request.POST.get('crf', '').strip()
        arquivo = request.FILES['arquivo_novo']
        
        caminho_destino = os.path.join(settings.GED_BASE_DIR, 'pessoa fisica', crf)
        
        # Injeção do Passo 12.2
        validar_caminho_seguro(caminho_destino)
        
        if not os.path.exists(caminho_destino):
            os.makedirs(caminho_destino)
            
        caminho_completo = os.path.join(caminho_destino, arquivo.name)
        
        if os.path.exists(caminho_completo):
            messages.error(request, f"Já existe um arquivo chamado '{arquivo.name}' nesse prontuário!")
        else:
            try:
                fss = FileSystemStorage(location=caminho_destino)
                fss.save(arquivo.name, arquivo)
                messages.success(request, f"Arquivo '{arquivo.name}' enviado com sucesso!")
            except Exception as e:
                messages.error(request, f"Erro ao salvar o arquivo: {str(e)}")
                
        return redirect(f"/busca/?crf={crf}")
        
    messages.error(request, "Nenhum arquivo foi selecionado.")
    return redirect('inicio')

@login_required
def upload_arquivo_geral(request):
    if request.method == 'POST' and request.FILES.get('arquivo'):
        arquivo = request.FILES['arquivo']
        caminho_pasta_atual = request.POST.get('caminho_atual')
        url_retorno = request.POST.get('url_retorno', '/')

        # Injeção do Passo 12.2
        validar_caminho_seguro(caminho_pasta_atual)

        if not caminho_pasta_atual or not os.path.exists(caminho_pasta_atual):
            messages.error(request, "Diretório de destino inválido.")
            return redirect(url_retorno)

        caminho_final = os.path.join(caminho_pasta_atual, arquivo.name)

        try:
            with open(caminho_final, 'wb+') as destination:
                for chunk in arquivo.chunks():
                    destination.write(chunk)
            messages.success(request, f"Arquivo '{arquivo.name}' enviado com sucesso!")
        except Exception as e:
            messages.error(request, f"Erro ao salvar arquivo: {str(e)}")

        return redirect(url_retorno)
    
    messages.error(request, "Nenhum arquivo enviado.")
    return redirect('/')

@login_required
@csrf_protect
def criar_subpasta(request):
    if request.method == 'POST':
        caminho_atual = request.POST.get('caminho_atual', '').strip()
        nome_pasta = request.POST.get('nome_pasta', '').strip()
        url_retorno = request.POST.get('url_retorno', '/')

        validar_caminho_seguro(caminho_atual)

        if "ged_teste" in caminho_atual:
            # Remove caracteres ilegais para evitar falhas de SO
            for caractere in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                nome_pasta = nome_pasta.replace(caractere, '')

            if nome_pasta == "":
                messages.error(request, "O nome da pasta não pode ser vazio.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))

            # --- VALIDAÇÃO DE NOME RESERVADO (WINDOWS) ANTES DA CRIAÇÃO ---
            try:
                validar_nome_seguro(nome_pasta, eh_arquivo=False)
            except ValidationError as e:
                messages.error(request, str(e))
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))

            caminho_nova_pasta = os.path.join(caminho_atual, nome_pasta)

            if os.path.exists(caminho_nova_pasta):
                messages.error(request, f"A subpasta '{nome_pasta}' já existe neste local!")
            else:
                try:
                    os.makedirs(caminova_pasta)
                    messages.success(request, f"Pasta '{nome_pasta}' criada com sucesso!")
                except Exception as e:
                    messages.error(request, f"Erro ao criar diretório físico: {str(e)}")
                    
            return redirect(request.META.get('HTTP_REFERER', 'inicio'))

@login_required
@csrf_protect
def navegar_pastas(request, modulo):
    if modulo == 'pessoa-fisica':
        raiz_modulo = os.path.join(settings.GED_BASE_DIR, 'pessoa fisica')
        titulo_base = "Pessoa Física"
    elif modulo == 'pessoa-juridica':
        raiz_modulo = os.path.join(settings.GED_BASE_DIR, 'pessoa juridica')
        titulo_base = "Pessoa Jurídica"
    elif modulo == 'setores':
        raiz_modulo = os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'setores')
        titulo_base = "Setores"
    else:
        raise Http404("Módulo inválido.")

    caminho_subpasta = request.GET.get('pasta', '').strip()
    caminho_atual = urllib.parse.unquote(caminho_subpasta) if caminho_subpasta else raiz_modulo

    validar_caminho_seguro(caminho_atual)

    if not caminho_atual.startswith(raiz_modulo):
        caminho_atual = raiz_modulo

    if not os.path.exists(caminho_atual):
        os.makedirs(caminho_atual)

    # --- NOVA INTELIGÊNCIA: Verifica de forma definitiva se o usuário está na pasta raiz do módulo ---
    caminho_normalizado = os.path.normpath(caminho_atual)
    raiz_modulo_normalizada = os.path.normpath(raiz_modulo)
    usuario_esta_na_raiz = (caminho_normalizado == raiz_modulo_normalizada)

    usuario_grupos = [grupo.name.lower() for grupo in request.user.groups.all()]
    if modulo == 'setores' and not request.user.is_superuser:
        if caminho_atual == raiz_modulo:
            pasta_autorizada = None
            for item in os.listdir(raiz_modulo):
                if item.lower() in usuario_grupos:
                    pasta_autorizada = os.path.join(raiz_modulo, item)
                    break
            if pasta_autorizada:
                caminho_atual = pasta_autorizada
                # Se o usuário comum foi redirecionado para a subpasta do setor dele, ele NÃO está na raiz geral
                usuario_esta_na_raiz = False 
            else:
                return render(request, 'core/navegar.html', {
                    'modulo': modulo, 
                    'titulo': titulo_base, 
                    'resultados': [], 
                    'caminho_pasta_atual': caminho_atual,
                    'usuario_esta_na_raiz': True
                })

    pastas_lista = []
    arquivos_lista = []

    try:
        for item in os.listdir(caminho_atual):
            caminho_completo = os.path.join(caminho_atual, item)
            if os.path.isdir(caminho_completo):
                pastas_lista.append({
                    'nome': item, 'tipo': 'pasta', 'tamanho': '-', 'caminho': caminho_completo
                })
            elif os.path.isfile(caminho_completo):
                tamanho = round(os.path.getsize(caminho_completo) / 1024, 2)
                arquivos_lista.append({
                    'nome': item, 'tipo': 'arquivo', 'tamanho': f"{tamanho} KB", 'caminho': caminho_completo
                })
    except Exception as e:
        messages.error(request, f"Erro ao acessar diretório: {str(e)}")

    pastas_lista.sort(key=lambda x: x['nome'].lower())
    arquivos_lista.sort(key=lambda x: x['nome'].lower())
    todos_itens = pastas_lista + arquivos_lista

    itens_por_pagina = request.GET.get('por_pagina', '50')
    if itens_por_pagina not in ['25', '50', '100']:
        itens_por_pagina = '50'
    itens_por_pagina = int(itens_por_pagina)

    num_pagina = request.GET.get('page', 1)
    paginator = Paginator(todos_itens, itens_por_pagina)
    pagina_atual = paginator.get_page(num_pagina)

    caminho_relativo = caminho_atual.replace(raiz_modulo, '')
    partes = [p for p in caminho_relativo.replace('\\', '/').split('/') if p]
    partes_pasta = []
    caminho_acumulado = raiz_modulo
    for parte in partes:
        caminho_acumulado = os.path.join(caminho_acumulado, parte)
        partes_pasta.append({'nome': parte, 'caminho': caminho_acumulado})

    pasta_pai = os.path.dirname(caminho_atual)
    exibir_botao_voltar = caminho_atual != raiz_modulo
    if modulo == 'setores' and not request.user.is_superuser:
        if caminho_atual.lower().endswith(tuple(usuario_grupos)):
            exibir_botao_voltar = False

    contexto = {
        'modulo': modulo,
        'titulo': f"{titulo_base} - {os.path.basename(caminho_atual) if caminho_atual != raiz_modulo else 'Raiz'}",
        'resultados': pagina_atual,
        'caminho_pasta_atual': caminho_atual,
        'pasta_pai': pasta_pai,
        'exibir_botao_voltar': exibir_botao_voltar,
        'partes_pasta': partes_pasta,
        'titulo_base': titulo_base,
        'por_pagina': itens_por_pagina,
        'usuario_esta_na_raiz': usuario_esta_na_raiz,  # <-- Enviado com sucesso para o template!
    }
    return render(request, 'core/navegar.html', contexto)

@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='inicio')
def ver_lixeira(request):
    """Exibe os arquivos e pastas que estão na lixeira física do sistema com filtros"""
    pasta_lixeira = os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'lixeira')
    if not os.path.exists(pasta_lixeira):
        os.makedirs(pasta_lixeira)
        
    # Captura os parâmetros de busca do formulário
    filtro_nome = request.GET.get('nome', '').strip().lower()
    filtro_tipo = request.GET.get('tipo', '').strip()
        
    arquivos_lixeira = []
    try:
        for item in os.listdir(pasta_lixeira):
            caminho_completo = os.path.join(pasta_lixeira, item)
            
            # Identifica se é arquivo ou pasta
            is_file = os.path.isfile(caminho_completo)
            tipo_item = 'Arquivo' if is_file else 'Pasta'
            
            # Aplica o filtro de Tipo, se selecionado
            if filtro_tipo and filtro_tipo != tipo_item:
                continue
                
            # Aplica o filtro de Nome, se preenchido
            if filtro_nome and filtro_nome not in item.lower():
                continue

            # Calcula o tamanho (se for pasta, calcula o tamanho total de forma simples)
            try:
                if is_file:
                    tamanho_num = os.path.getsize(caminho_completo)
                else:
                    tamanho_num = sum(os.path.getsize(os.path.join(dirpath, filename)) 
                                      for dirpath, _, filenames in os.walk(caminho_completo) 
                                      for filename in filenames)
                tamanho = f"{round(tamanho_num / 1024, 2)} KB"
            except Exception:
                tamanho = "Indisponível"
                
            # Puxamos o último log de auditoria desse item para saber quem apagou
            ultimo_log = LogAuditoria.objects.filter(acao='APAGAR', descricao__contains=item).first()
            
            arquivos_lixeira.append({
                'nome': item,
                'tipo': tipo_item,
                'tamanho': tamanho,
                'caminho': caminho_completo,
                'apagado_por': ultimo_log.usuario.username if ultimo_log and ultimo_log.usuario else "Desconhecido",
                'data_exclusao': ultimo_log.data_hora if ultimo_log else None
            })
            
        # Usa uma data antiga com fuso horário ciente (aware) para evitar o conflito do Python
        data_minima = timezone.make_aware(datetime.min) if settings.USE_TZ else datetime.min
        
        arquivos_lixeira.sort(key=lambda x: x['data_exclusao'] if x['data_exclusao'] else data_minima, reverse=True)
        
    except Exception as e:
        messages.error(request, f"Erro ao acessar lixeira: {str(e)}")

    return render(request, 'core/lixeira.html', {
        'arquivos': arquivos_lixeira,
        'filtro_nome': request.GET.get('nome', ''),
        'filtro_tipo': filtro_tipo
    })

@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='inicio')
@csrf_protect
def restaurar_arquivo(request):
    """Move o arquivo ou pasta da lixeira de volta para a sua origem exata"""
    if request.method == 'POST':
        # Captura o que veio do formulário (pode vir o caminho ou apenas o nome)
        dado_recebido = request.POST.get('caminho_lixeira', '').strip()
        
        # Extrai APENAS o nome do arquivo/pasta (ex: 'aaaaa.pdf'), ignorando caminhos do Windows
        nome_item = os.path.basename(dado_recebido)
        
        # Monta o caminho absoluto correto dentro da lixeira do servidor
        pasta_lixeira = os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'lixeira')
        caminho_lixeira = os.path.normpath(os.path.join(pasta_lixeira, nome_item))
        
        # Valida o caminho físico na lixeira
        validar_caminho_seguro(caminho_lixeira)

        # Busca na auditoria usando o nome limpo do arquivo
        log = LogAuditoria.objects.filter(acao='APAGAR', descricao=nome_item).first()
        
        if log and log.caminho_item:
            caminho_original = log.caminho_item
            pasta_destino = os.path.dirname(caminho_original)
            
            # Se a árvore de pastas original foi modificada ou excluída, recria o caminho
            if not os.path.exists(pasta_destino):
                os.makedirs(pasta_destino)
                
            try:
                # Move o arquivo ou pasta de volta
                shutil.move(caminho_lixeira, caminho_original)
                messages.success(request, f"'{nome_item}' restaurado com sucesso para a pasta de origem!")
                
                # Grava o log da restauração
                LogAuditoria.objects.create(
                    usuario=request.user,
                    acao='UPLOAD', 
                    descricao=nome_item,
                    caminho_item=caminho_original
                )
            except Exception as e:
                messages.error(request, f"Erro ao restaurar item: {str(e)}")
        else:
            messages.error(request, f"Não encontramos o histórico de origem de '{nome_item}' no banco de dados.")
            
    return redirect('ver_lixeira')

@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='inicio')
def ver_auditoria(request):
    """Exibe o histórico completo de ações realizadas no sistema (Logs de Auditoria)"""
    if not request.user.is_authenticated:
        return redirect('inicio')
        
    filtro_busca = request.GET.get('busca', '').strip()
    filtro_acao = request.GET.get('acao', '').strip()
    
    logs = LogAuditoria.objects.all().order_by('-data_hora')
    
    # Busca combinada corrigida usando Q
    if filtro_busca:
        logs = logs.filter(
            Q(usuario__username__icontains=filtro_busca) | 
            Q(descricao__icontains=filtro_busca)
        )
        
    if filtro_acao:
        logs = logs.filter(acao=filtro_acao)
        
    paginator = Paginator(logs, 50)
    num_pagina = request.GET.get('page', 1)
    pagina_logs = paginator.get_page(num_pagina)
    
    contexto = {
        'logs': pagina_logs,
        'filtro_busca': filtro_busca,
        'filtro_acao': filtro_acao,
    }
    return render(request, 'core/auditoria.html', contexto)

@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='inicio')
@csrf_protect
def esvaziar_lixeira(request):
    """Apaga permanentemente todos os arquivos e pastas que estão na lixeira física"""
    if request.method == 'POST':
        # Só permite que superusuários façam a exclusão definitiva
        if not request.user.is_superuser:
            messages.error(request, "Acesso negado: Apenas administradores podem esvaziar a lixeira.")
            return redirect('ver_lixeira')

        pasta_lixeira = os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'lixeira')
        
        if os.path.exists(pasta_lixeira):
            try:
                contador_itens = 0
                # Varre a pasta para apagar item por item e poder contar
                for item in os.listdir(pasta_lixeira):
                    caminho_completo = os.path.join(pasta_lixeira, item)
                    
                    # Garante que não vai sair deletando caminhos fora da lixeira por acidente
                    validar_caminho_seguro(caminho_completo)
                    
                    if os.path.isfile(caminho_completo) or os.path.islink(caminho_completo):
                        os.unlink(caminho_completo)
                    elif os.path.isdir(caminho_completo):
                        shutil.rmtree(caminho_completo)
                    
                    contador_itens += 1

                # Registra na auditoria que a lixeira foi limpa
                LogAuditoria.objects.create(
                    usuario=request.user,
                    acao='APAGAR',
                    descricao=f"Lixeira esvaziada completamente ({contador_itens} itens removidos).",
                    caminho_item=pasta_lixeira
                )

                if contador_itens > 0:
                    messages.success(request, f"Sucesso! A lixeira foi esvaziada e {contador_itens} itens foram apagados permanentemente do HD.")
                else:
                    messages.info(request, "A lixeira já estava vazia.")

            except Exception as e:
                messages.error(request, f"Erro físico ao esvaziar a lixeira: {str(e)}")
        else:
            messages.error(request, "Pasta da lixeira não encontrada no servidor.")

    return redirect('ver_lixeira')

@login_required
@csrf_protect
def upload_multiplo_ajax(request):
    """Recebe arquivos via AJAX do Dropzone e salva no diretório atual com travas de segurança"""
    if request.method == 'POST' and request.FILES.get('file'):
        arquivo = request.FILES['file']
        caminho_pasta_atual = request.POST.get('caminho_atual')

        # --- NOVA TRAVA: Impedir Upload na Raiz ---
        # Verifica se o caminho atual termina exatamente na pasta raiz dos módulos
        caminho_normalizado = os.path.normpath(caminho_pasta_atual)
        base_ged = os.path.normpath(settings.GED_BASE_DIR)
        
        # Lista as pastas raízes permitidas (ex: C:\ged_teste\pessoa-fisica)
        raizes_bloqueadas = [
            os.path.join(base_ged, 'pessoa-fisica'),
            os.path.join(base_ged, 'pessoa-juridica'),
            os.path.join(base_ged, 'setores')
        ]
        
        if caminho_normalizado in raizes_bloqueadas:
            return JsonResponse({'error': 'Não é permitido fazer upload de arquivos diretamente na raiz deste módulo. Crie ou acesse uma pasta primeiro.'}, status=403)

        # Trava de Segurança de Path Traversal anterior
        try:
            validar_caminho_seguro(caminho_pasta_atual)
        except PermissionDenied as e:
            return JsonResponse({'error': str(e)}, status=403)

        # --- NOVA TRAVA: Validar Extensão e Nome Reservado Windows ---
        try:
            validar_nome_seguro(arquivo.name, eh_arquivo=True)
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)

        if not caminho_pasta_atual or not os.path.exists(caminho_pasta_atual):
            return JsonResponse({'error': 'Diretório de destino inválido.'}, status=400)

        caminho_final = os.path.join(caminho_pasta_atual, arquivo.name)

        if os.path.exists(caminho_final):
            return JsonResponse({'error': f"O arquivo '{arquivo.name}' já existe nesta pasta."}, status=400)

        try:
            with open(caminho_final, 'wb+') as destination:
                for chunk in arquivo.chunks():
                    destination.write(chunk)
            
            LogAuditoria.objects.create(
                usuario=request.user,
                acao='UPLOAD',
                descricao=arquivo.name,
                caminho_item=caminho_final
            )
            return JsonResponse({'message': 'Sucesso!'}, status=200)
        except Exception as e:
            return JsonResponse({'error': f"Erro ao salvar arquivo: {str(e)}"}, status=500)
            
    return JsonResponse({'error': 'Nenhum arquivo enviado.'}, status=400)

@login_required
@csrf_protect
def excluir_multiplos_ajax(request):
    """Move múltiplos arquivos ou pastas para uma lixeira segura e auditada"""
    
    # TRAVA 1: Controle de Permissão por Grupo
    # Permite apenas usuários do grupo 'GED_Administrador' ou superusuários do sistema
    if not request.user.groups.filter(name='GED_Administrador').exists() and not request.user.is_superuser:
        return JsonResponse({
            'error': 'Operação não permitida. Apenas administradores do GED podem excluir itens.'
        }, status=403)

    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            itens_para_excluir = dados.get('itens', [])
            
            if not itens_para_excluir:
                return JsonResponse({'error': 'Nenhum item foi selecionado.'}, status=400)
                
            sucessos = 0
            erros = 0
            ultimo_erro = ""
            
            # Define o caminho base da lixeira (ajuste o caminho base se necessário)
            # Mantendo o padrão do seu ambiente Windows C:\ged_teste
            DIRETORIO_RAIZ = r"C:\ged_teste"
            PASTA_LIXEIRA = os.path.join(DIRETORIO_RAIZ, ".lixeira")
            
            # Garante que a pasta da lixeira exista fisicamente no HD
            if not os.path.exists(PASTA_LIXEIRA):
                os.makedirs(PASTA_LIXEIRA)
            
            for caminho_item in itens_para_excluir:
                try:
                    validar_caminho_seguro(caminho_item)
                    
                    if os.path.exists(caminho_item):
                        nome_base = os.path.basename(caminho_item)
                        
                        # Evita que o usuário tente excluir a própria lixeira
                        if caminho_item.lower() == PASTA_LIXEIRA.lower():
                            continue
                            
                        # Tratamento de conflito de nomes na lixeira:
                        # Se arquivo.pdf já existir lá, vira arquivo_20260625_111800.pdf
                        timestamp = datetime.now().strftime("%Y%m%d_%H%m%S")
                        nome_destino = nome_base
                        caminho_destino = os.path.join(PASTA_LIXEIRA, nome_destino)
                        
                        if os.path.exists(caminho_destino):
                            nome_sem_ext, ext = os.path.splitext(nome_base)
                            nome_destino = f"{nome_sem_ext}_{timestamp}{ext}"
                            caminho_destino = os.path.join(PASTA_LIXEIRA, nome_destino)
                        
                        # --- TRAVA 2: LIXEIRA REAL (shutil.move ao invés de remover) ---
                        shutil.move(caminho_item, caminho_destino)
                            
                        # Registra no Log de Auditoria do CRF-PB
                        LogAuditoria.objects.create(
                            usuario=request.user,
                            acao='EXCLUSAO_MUTIPLA',
                            descricao=f"Item movido para a lixeira: {nome_base} (Destino: {nome_destino})",
                            caminho_item=caminho_item
                        )
                        sucessos += 1
                except Exception as e:
                    erros += 1
                    ultimo_erro = str(e)
                    continue
            
            # --- FORMATAÇÃO DA MENSAGEM DINÂMICA ---
            if sucessos == 1:
                msg_sucesso = "1 item foi movido para a lixeira."
            elif sucessos > 1:
                msg_sucesso = f"{sucessos} itens foram movidos para a lixeira."
            else:
                msg_sucesso = "Nenhum item foi movido."

            msg_erro = ""
            if erros > 0:
                msg_erro = f" Houve {erros} falha{'s' if erros > 1 else ''} no processamento."

            mensagem_final = f"{msg_sucesso}{msg_erro}"
                    
            return JsonResponse({
                'message': mensagem_final,
                'sucessos': sucessos,
                'erros': erros,
                'detalhe_erro': ultimo_erro
            }, status=200)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Dados JSON inválidos.'}, status=400)
            
    return JsonResponse({'error': 'Método não permitido.'}, status=405)

def validar_nome_seguro(nome_item, eh_arquivo=False):
    """Valida se o nome do arquivo ou pasta é seguro para sistemas Windows e políticas do GED"""
    
    # 1. Lista de nomes reservados do Windows (case-insensitive)
    nomes_reservados = {
        'CON', 'PRN', 'AUX', 'NUL', 
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    }
    
    # Extrai o nome sem a extensão para verificar contra os nomes reservados
    nome_puro = os.path.splitext(nome_item)[0].upper().strip()
    if nome_puro in nomes_reservados:
        raise ValidationError(f"O nome '{nome_item}' é reservado pelo sistema operacional Windows e não pode ser usado.")
    
    # 2. Lista de extensões perigosas ou bloqueadas (Malwares/Executáveis)
    if eh_arquivo:
        extensoes_proibidas = {
            '.exe', '.bat', '.cmd', '.msi', '.vbs', '.vbe', '.js', '.jse', 
            '.wsf', '.wsh', '.ps1', '.scr', '.com', '.pif', '.hta', '.sh'
        }
        extensao = os.path.splitext(nome_item)[1].lower()
        if extensao in extensoes_proibidas:
            raise ValidationError(f"Arquivos com a extensão '{extensao}' são bloqueados por motivos de segurança.")
        
def validar_caminho_seguro(caminho_solicitado):
    # Se o caminho for vazio, é a raiz do GED, permitido
    if not caminho_solicitado:
        return os.path.abspath(settings.MEDIA_ROOT)
    
    # Se o caminho for apenas um nome de pasta (sem '../'), permitimos
    # Isso resolve o problema de módulos como 'pessoa-fisica' ou 'setores'
    if '..' not in caminho_solicitado:
        # Se for um nome simples, apenas checamos se existe
        caminho_alvo = os.path.abspath(os.path.join(settings.MEDIA_ROOT, caminho_solicitado))
        return caminho_alvo

    # Se contiver '..', aí sim aplicamos a regra rígida de segurança
    base_dir = os.path.abspath(settings.MEDIA_ROOT)
    caminho_alvo = os.path.abspath(os.path.join(base_dir, caminho_solicitado))
    
    if not caminho_alvo.startswith(base_dir):
        raise PermissionDenied("Acesso a pasta não autorizada!")
    
    return caminho_alvo

