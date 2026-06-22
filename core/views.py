import os
import mimetypes
import shutil
import urllib.parse

from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect
from django.conf import settings
from django.http import FileResponse, Http404
from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone

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
    
    # Verifica se o caminho solicitado começa com a raiz do GED ou dos Setores
    if caminho_real.startswith(ged_raiz) or caminho_real.startswith(setores_raiz):
        return True
        
    # Se não estiver em nenhum dos dois, levanta um erro de segurança do Django
    raise PermissionDenied("Acesso negado: Tentativa de violação de diretório detectada.")


# ==========================================
# VIEWS DO SISTEMA
# ==========================================

def inicio(request):
    return render(request, 'core/inicio.html')

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

def visualizar_arquivo(request):
    caminho_completo = request.GET.get('caminho', '')
    caminho_final = urllib.parse.unquote(caminho_completo)

    # Injeção do Passo 12.2
    validar_caminho_seguro(caminho_final)
    
    if os.path.exists(caminho_final) and "ged_teste" in caminho_final:
        content_type, _ = mimetypes.guess_type(caminho_final)
        arquivo = open(caminho_final, 'rb')
        return FileResponse(arquivo, content_type=content_type)
    
    raise Http404("Arquivo não encontrado.")

def baixar_arquivo(request):
    caminho_completo = request.GET.get('caminho', '')
    caminho_final = urllib.parse.unquote(caminho_completo)

    # Injeção do Passo 12.2
    validar_caminho_seguro(caminho_final)
    
    if os.path.exists(caminho_final) and "ged_teste" in caminho_final:
        arquivo = open(caminho_final, 'rb')
        return FileResponse(arquivo, as_attachment=True)
    
    raise Http404("Arquivo não encontrado.")

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

def criar_subpasta(request):
    if request.method == 'POST':
        caminho_atual = request.POST.get('caminho_atual', '').strip()
        nome_pasta = request.POST.get('nome_pasta', '').strip()
        url_retorno = request.POST.get('url_retorno', '/')

        # Injeção do Passo 12.2
        validar_caminho_seguro(caminho_atual)

        if "ged_teste" in caminho_atual:
            for caractere in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                nome_pasta = nome_pasta.replace(caractere, '')

            caminho_nova_pasta = os.path.join(caminho_atual, nome_pasta)

            if os.path.exists(caminho_nova_pasta):
                messages.error(request, f"A subpasta '{nome_pasta}' já existe neste local!")
            elif nome_pasta == "":
                messages.error(request, "O nome da pasta não pode ser vazio.")
            else:
                try:
                    os.makedirs(caminho_nova_pasta)
                    messages.success(request, f"Subpasta '{nome_pasta}' criada com sucesso!")
                except Exception as e:
                    messages.error(request, f"Erro ao criar pasta no servidor: {str(e)}")
        else:
            messages.error(request, "Diretório não autorizado.")

        return redirect(url_retorno)

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

    # Injeção do Passo 12.2
    validar_caminho_seguro(caminho_atual)

    if not caminho_atual.startswith(raiz_modulo):
        caminho_atual = raiz_modulo

    if not os.path.exists(caminho_atual):
        os.makedirs(caminho_atual)

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
            else:
                return render(request, 'core/navegar.html', {'modulo': modulo, 'titulo': titulo_base, 'resultados': [], 'caminho_pasta_atual': caminho_atual})

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
    }
    return render(request, 'core/navegar.html', contexto)

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

@csrf_protect
def restaurar_arquivo(request):
    """Move o arquivo ou pasta da lixeira de volta para a sua origem exata"""
    if request.method == 'POST':
        # Recebe apenas o nome puro do item vindo do formulário do template
        nome_item = request.POST.get('caminho_lixeira', '').strip()
        
        # Monta o caminho absoluto correto dentro da pasta lixeira do servidor
        pasta_lixeira = os.path.join(os.path.dirname(settings.GED_BASE_DIR), 'lixeira')
        caminho_lixeira = os.path.normpath(os.path.join(pasta_lixeira, nome_item))
        
        # Agora a validação de caminho seguro vai passar perfeitamente!
        validar_caminho_seguro(caminho_lixeira)

        # Busca na auditoria usando o nome exato que configuramos na view de apagar
        log = LogAuditoria.objects.filter(acao='APAGAR', descricao=nome_item).first()
        
        if log and log.caminho_item:
            caminho_original = log.caminho_item
            pasta_destino = os.path.dirname(caminho_original)
            
            # Se a árvore de pastas original foi modificada ou excluída, recria o caminho
            if not os.path.exists(pasta_destino):
                os.makedirs(pasta_destino)
                
            try:
                # Move o arquivo ou pasta inteira de volta
                shutil.move(caminho_lixeira, caminho_original)
                messages.success(request, f"'{nome_item}' restaurado com sucesso para a pasta de origem!")
                
                # Grava o log da restauração mantendo o padrão limpo
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