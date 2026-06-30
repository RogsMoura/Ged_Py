import os
import mimetypes
import shutil
import urllib.parse
import re
import json
import time

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
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.urls import reverse

from datetime import datetime

from .models import LogAuditoria, RegistroLixeira

# ==========================================
# TRAVA DE SEGURANÇA (PATH TRAVERSAL)
# ==========================================
def validar_caminho_seguro(caminho_solicitado, verificar_existencia=True):
    raizes_autorizadas = [
        os.path.abspath(r'D:\GED'),
        os.path.abspath(r'D:\GED_LIXEIRA'),
        os.path.abspath(r'D:\SETORES')
    ]
    
    if not caminho_solicitado:
        return raizes_autorizadas[0]

    caminho_alvo = os.path.abspath(caminho_solicitado)
    
    # 1. Segurança: Impede Path Traversal (sair das pastas permitidas)
    if not any(caminho_alvo.startswith(base) for base in raizes_autorizadas):
        raise PermissionDenied(f"Acesso negado: {caminho_alvo} fora da área permitida.")
    
    # 2. Verifica existência apenas se solicitado (para novos arquivos ainda não criados)
    if verificar_existencia and not os.path.exists(caminho_alvo):
        raise PermissionDenied("Acesso negado: Caminho não encontrado.")
        
    return caminho_alvo

def secure_filename(filename):
    # Remove qualquer caractere que não seja letra, número, ponto, traço ou underline
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    return filename

# ==========================================
# VIEWS DO SISTEMA
# ==========================================

def inicio(request):
    # Se o usuário já estiver logado, jogue-o direto para o sistema
    if request.user.is_authenticated:
        return redirect('inicio_sistema') 
        
    if request.method == 'POST':
        user = authenticate(request, username=request.POST.get('username'), password=request.POST.get('password'))
        if user is not None:
            login(request, user)
            return redirect('inicio_sistema') # Sucesso: vai pro sistema
        else:
            # Erro de senha
            return render(request, 'core/login.html', {'error': 'Usuário ou senha inválidos'})
            
    return render(request, 'core/login.html')

# ESTA DEVE TER @login_required (ela é o sistema)
@login_required
def pagina_inicial_direcionamento(request):
    # Aqui você renderiza o seu sistema (que usa o base.html)
    return render(request, 'core/inicio.html')

@login_required
def busca_crf(request):
    termo_busca = request.GET.get('crf', '').strip()
    ordem = request.GET.get('ordem', 'az')
    por_pagina = int(request.GET.get('por_pagina', 25))
    pagina = request.GET.get('page', 1)
    
    resultados_totais = []
    
    if termo_busca:
        # Definimos os dois locais de busca
        diretorios_para_buscar = [
            {'nome': 'PF', 'path': os.path.join(settings.GED_BASE_DIR, 'PESSOA FISICA')},
            {'nome': 'PJ', 'path': os.path.join(settings.GED_BASE_DIR, 'PESSOA JURIDICA')}
        ]
        
        for dir_info in diretorios_para_buscar:
            if os.path.exists(dir_info['path']):
                for nome_pasta in os.listdir(dir_info['path']):
                    if termo_busca.lower() in nome_pasta.lower():
                        caminho_completo = os.path.join(dir_info['path'], nome_pasta)
                        
                        if os.path.isdir(caminho_completo):
                            # Identificamos se é PF ou PJ para exibir na interface
                            resultados_totais.append({
                                'nome': nome_pasta,
                                'modulo': 'pessoa-fisica' if dir_info['nome'] == 'PF' else 'pessoa-juridica',
                                'label': 'PF' if dir_info['nome'] == 'PF' else 'PJ',
                                'caminho': caminho_completo
                            })
    
    # Ordenação e Paginação (mesma lógica anterior)
    resultados_totais.sort(key=lambda x: x['nome'].lower(), reverse=(ordem == 'za'))
    paginator = Paginator(resultados_totais, por_pagina)
    resultados_paginados = paginator.get_page(pagina)

    return render(request, 'core/busca.html', {
        'resultados': resultados_paginados,
        'termo_busca': termo_busca,
        'ordem': ordem,
        'por_pagina': por_pagina,
        'pasta_encontrada': len(resultados_totais) > 0
    })

@xframe_options_exempt
@login_required
def visualizar_arquivo(request):
    caminho_usuario = request.GET.get('caminho', '')
    
    # Valida e recebe o caminho já seguro
    try:
        caminho_seguro = validar_caminho_seguro(caminho_usuario)
    except Exception:
        return HttpResponse("Acesso negado.", status=403)

    if not os.path.isfile(caminho_seguro):
        raise Http404("Arquivo não encontrado.")
    
    # Usa FileResponse para performance e stream de dados (evita carregar tudo na RAM)
    response = FileResponse(open(caminho_seguro, 'rb'), content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="%s"' % os.path.basename(caminho_seguro)
    return response

@login_required
def baixar_arquivo(request):
    caminho_completo = request.GET.get('caminho', '')
    caminho_final = urllib.parse.unquote(caminho_completo)

    # A validação centralizada já garante a segurança
    caminho_seguro = validar_caminho_seguro(caminho_final)
    
    if os.path.isfile(caminho_seguro):
        return FileResponse(open(caminho_seguro, 'rb'), as_attachment=True)
    
    raise Http404("Arquivo não encontrado.")

@login_required
def renomear_arquivo(request):
    if request.method == 'POST':
        caminho_atual = request.POST.get('caminho_atual', '')
        # 1. Pega o nome base original e a extensão original
        nome_base_original, ext = os.path.splitext(os.path.basename(caminho_atual))
        
        # 2. Pega o input do usuário e garante que é apenas o nome (sem caminho e sem extensão)
        nome_bruto = request.POST.get('novo_nome', '').strip()
        nome_limpo = os.path.splitext(os.path.basename(nome_bruto))[0]
        
        # 3. Monta o nome final unindo o que ele digitou com a extensão original
        novo_nome = f"{nome_limpo}{ext}"
        
        crf = request.POST.get('crf', '')

        # Validação centralizada e segura
        caminho_origem = validar_caminho_seguro(caminho_atual, verificar_existencia=True)
        
        # Mantém a extensão original se o usuário não digitar uma nova
        nome_base, ext = os.path.splitext(novo_nome)
        if not ext and os.path.isfile(caminho_origem):
            _, ext_original = os.path.splitext(caminho_origem)
            novo_nome = f"{nome_base}{ext_original}"

        pasta_pai = os.path.dirname(caminho_origem)
        caminho_novo = os.path.join(pasta_pai, novo_nome)

        validar_caminho_seguro(caminho_novo, verificar_existencia=False)

        if os.path.exists(caminho_origem):
            if os.path.exists(caminho_novo):
                messages.error(request, "Já existe um arquivo com esse nome.")
            else:
                try:
                    os.rename(caminho_origem, caminho_novo)
                    messages.success(request, "Renomeado com sucesso!")
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
        
        # Validação
        caminho_seguro = validar_caminho_seguro(caminho_atual)
        nome_item = os.path.basename(caminho_seguro)
        
        # Preparar Lixeira
        pasta_lixeira = settings.LIXEIRA_DIR
        if not os.path.exists(pasta_lixeira):
            os.makedirs(pasta_lixeira)

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        caminho_lixeira = os.path.join(pasta_lixeira, f"{timestamp}_{nome_item}")

        nome_arquivo_na_lixeira = os.path.basename(caminho_lixeira)

        RegistroLixeira.objects.create(
            nome_na_lixeira=nome_arquivo_na_lixeira,
            caminho_original=caminho_seguro,
            apagado_por=request.user
        )

        # Lógica de Retry (Tentar mover até 3 vezes)
        tentativas = 0
        sucesso = False
        erro_final = ""

        while tentativas < 3 and not sucesso:
            try:
                shutil.move(caminho_seguro, caminho_lixeira)
                sucesso = True
            except (PermissionError, OSError) as e:
                tentativas += 1
                erro_final = str(e)
                time.sleep(0.5) # Espera meio segundo antes de tentar de novo

        if sucesso:
            # Log de auditoria
            LogAuditoria.objects.create(
                usuario=request.user,
                acao='APAGAR',
                descricao=nome_item,
                caminho_item=caminho_seguro
            )
            messages.success(request, f"Item '{nome_item}' movido para a lixeira!")
        else:
            messages.error(request, f"Erro ao mover o item após tentativas: {erro_final}")

        # Redirecionamento
        if crf == 'bypass':
            return redirect(request.GET.get('next') or '/inicio/')
        return redirect(f"/busca/?crf={crf}")

@login_required
@csrf_protect
def excluir_multiplos_ajax(request):
    """Move múltiplos arquivos ou pastas para uma lixeira segura e auditada"""
    
    # TRAVA: Permite se for superusuário, administrador GED, 
    # ou se o grupo do usuário for parte do caminho (setor)
    user_groups = [g.name.lower() for g in request.user.groups.all()]
    is_admin = request.user.is_superuser or 'ged_administrador' in user_groups

    # Vamos verificar se o primeiro item da lista pertence ao setor do usuário
    # (assumindo que você sempre envia itens do mesmo setor)
    dados = json.loads(request.body)
    itens = dados.get('itens', [])
    
    if not is_admin and itens:
        # Pega a primeira pasta do caminho do arquivo
        primeiro_item = itens[0]
        # Extrai o setor (ex: 'TI') do caminho
        setor_do_item = os.path.normpath(os.path.relpath(primeiro_item, settings.SETORES_BASE_DIR)).split(os.sep)[0].lower()
        
        if setor_do_item not in user_groups:
             return JsonResponse({'error': 'Você não tem permissão para excluir arquivos deste setor.'}, status=403)

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
            PASTA_LIXEIRA = settings.LIXEIRA_DIR

            # Garante que a pasta da lixeira exista
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
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        nome_destino = nome_base
                        caminho_destino = os.path.join(PASTA_LIXEIRA, nome_destino)
                        
                        if os.path.exists(os.path.join(PASTA_LIXEIRA, nome_destino)):
                            nome_sem_ext, ext = os.path.splitext(nome_base)
                            nome_destino = f"{nome_sem_ext}_{timestamp}{ext}"

                        caminho_destino = os.path.join(PASTA_LIXEIRA, nome_destino)

                        if not caminho_destino.startswith(PASTA_LIXEIRA):
                            raise Exception("Erro de segurança: Tentativa de mover item para fora da lixeira.")
                        
                        nome_arquivo_na_lixeira = os.path.basename(caminho_destino)

                        RegistroLixeira.objects.create(
                            nome_na_lixeira=nome_arquivo_na_lixeira, # ou nome_base, o que for o nome final no arquivo
                            caminho_original=caminho_item,
                            apagado_por=request.user # <--- O segredo para não ficar "Desconhecido"
                        )
                        
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
            if sucessos > 0:
                msg_sucesso = f"{sucessos} item(s) movido(s) para a lixeira."
                messages.success(request, msg_sucesso) # <--- ISSO VAI APARECER NO SEU HTML
            
            if erros > 0:
                msg_erro = f"Houve {erros} falha(s) no processamento: {ultimo_erro}"
                messages.error(request, msg_erro) # <--- ISSO VAI APARECER EM VERMELHO

            # Retorne apenas a confirmação de que o processo terminou
            return JsonResponse({'status': 'success'}, status=200)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Dados JSON inválidos.'}, status=400)
            
    return JsonResponse({'error': 'Método não permitido.'}, status=405)

@login_required
def upload_arquivo(request, modulo):
    if request.method == 'POST':
        caminho_destino = request.POST.get('caminho_destino') # Passado via input hidden
        arquivo = request.FILES.get('arquivo')
        
        # 1. Validação de segurança do caminho (O mesmo que fizemos na exclusão)
        validar_caminho_seguro(caminho_destino)
        
        # 2. Impedir upload na raiz (se essa for sua regra)
        if os.path.normpath(caminho_destino) == os.path.normpath(config['raiz']):
            return JsonResponse({'error': 'Não é permitido subir arquivos na raiz.'}, status=403)
            
        # 3. Validação de permissão (O mesmo check que fizemos no acesso)
        # Verifique se o caminho_destino começa com a pasta autorizada do usuário
        if not caminho_autorizado_para_usuario(request.user, caminho_destino):
            return JsonResponse({'error': 'Sem permissão para esta pasta.'}, status=403)
            
        # 4. Salvar com nome seguro
        nome_seguro = secure_filename(arquivo.name) # Use uma função para limpar caracteres estranhos
        caminho_completo = os.path.join(caminho_destino, nome_seguro)
        
        # Salva o arquivo...
        with open(caminho_completo, 'wb+') as destination:
            for chunk in arquivo.chunks():
                destination.write(chunk)
                
        # 5. Log de Auditoria
        LogAuditoria.objects.create(usuario=request.user, acao='UPLOAD', descricao=f"Upload: {nome_seguro}")
        
        return JsonResponse({'message': 'Upload realizado com sucesso!'})

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

        nome_arquivo_seguro = os.path.basename(arquivo.name)
        caminho_completo = os.path.join(caminho_pasta_atual, nome_arquivo_seguro)

        try:
            with open(caminho_completo, 'wb+') as destination:
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

        nome_arquivo_seguro = os.path.basename(arquivo.name)
        caminho_final = os.path.join(caminho_pasta_atual, nome_arquivo_seguro)

        if os.path.exists(caminho_final):
             return JsonResponse({'error': f"O arquivo '{nome_arquivo_seguro}' já existe nesta pasta."}, status=400)

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
def criar_subpasta(request):
    if request.method == 'POST':
        caminho_atual = request.POST.get('caminho_atual', '').strip()
        nome_pasta_input = request.POST.get('nome_pasta', '').strip()

        # 1. Validação centralizada do diretório pai
        caminho_seguro = validar_caminho_seguro(caminho_atual)

        # 2. SANITIZAÇÃO SEGURA: os.path.basename garante que 
        # o nome seja apenas uma pasta, ignorando qualquer tentativa de caminho.
        nome_pasta = os.path.basename(nome_pasta_input)

        # 3. Remover caracteres inválidos (o seu filtro já era bom, mas 
        # o basename protege contra a estrutura de diretórios)
        for caractere in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            nome_pasta = nome_pasta.replace(caractere, '')

        if not nome_pasta:
            messages.error(request, "O nome da pasta é inválido.")
            return redirect(request.META.get('HTTP_REFERER', 'inicio'))

        # 4. Valida nomes reservados do Windows
        try:
            validar_nome_seguro(nome_pasta, eh_arquivo=False)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect(request.META.get('HTTP_REFERER', 'inicio'))

        # 5. Montagem do caminho final
        caminho_nova_pasta = os.path.join(caminho_seguro, nome_pasta)

        if os.path.exists(caminho_nova_pasta):
            messages.error(request, f"A subpasta '{nome_pasta}' já existe neste local!")
        else:
            try:
                os.makedirs(caminho_nova_pasta)
                messages.success(request, f"Pasta '{nome_pasta}' criada com sucesso!")
            except Exception as e:
                messages.error(request, f"Erro ao criar diretório: {str(e)}")
                
        return redirect(request.META.get('HTTP_REFERER', 'inicio'))

@login_required
@csrf_protect
def navegar_pastas(request, modulo):
    # 1. Mapeamento de Módulos (mais limpo que vários IFs)
    configuracoes_modulo = {
        'pessoa-fisica': {'raiz': os.path.join(settings.GED_BASE_DIR, 'PESSOA FISICA'), 'titulo': "Pessoa Física"},
        'pessoa-juridica': {'raiz': os.path.join(settings.GED_BASE_DIR, 'PESSOA JURIDICA'), 'titulo': "Pessoa Jurídica"},
        'setores': {'raiz': settings.SETORES_BASE_DIR, 'titulo': "Setores"}
    }
    
    config = configuracoes_modulo.get(modulo)
    if not config:
        raise Http404("Módulo inválido.")
    
    raiz_modulo = config['raiz']
    titulo_base = config['titulo']

    # 2. Sanitização de caminho
    caminho_subpasta = request.GET.get('pasta', '').strip()
    caminho_atual = urllib.parse.unquote(caminho_subpasta) if caminho_subpasta else raiz_modulo
    
    # Validação rigorosa
    validar_caminho_seguro(caminho_atual)
    if not caminho_atual.startswith(raiz_modulo):
        caminho_atual = raiz_modulo

    # 1. Defina a variável logo no início para evitar o erro de 'UnboundLocal'
    relativo = "." 
    
    # 2. Calcule o relativo SOMENTE se o caminho for válido
    if caminho_atual.startswith(raiz_modulo):
        relativo = os.path.normpath(os.path.relpath(caminho_atual, raiz_modulo))

    # 3. Agora aplique a lógica de permissão com segurança
    if modulo == 'setores' and not request.user.is_superuser:
        pastas_permitidas = [g.name.lower() for g in request.user.groups.all()]
        
        # Se não estiver na raiz, verifica a primeira pasta
        if relativo != ".":
            primeira_pasta = relativo.split(os.sep)[0].lower()
            if primeira_pasta not in pastas_permitidas:
                return render(request, 'core/navegar.html', {
                    'modulo': modulo, 
                    'erro_permissao': "Você não tem permissão para acessar esta pasta."
                })

    # 3. Lógica de Permissão de Setores (Unificada)
    if modulo == 'setores' and not request.user.is_superuser:
        pastas_permitidas = [g.name.lower() for g in request.user.groups.all()]
        
        # Obtém o caminho relativo apenas se estiver abaixo da raiz
        relativo = os.path.normpath(os.path.relpath(caminho_atual, raiz_modulo))
        
        # Se não estiver na raiz, verifica se o usuário tem permissão para a pasta pai (o setor)
        if relativo != ".":
            primeira_pasta = relativo.split(os.sep)[0].lower()
            if primeira_pasta not in pastas_permitidas:
                return render(request, 'core/navegar.html', {
                    'modulo': modulo, 
                    'erro_permissao': "Você não tem permissão para acessar esta pasta."
                })

    # 4. Listagem e Filtro de Permissão
    itens = []
    usuario_grupos = [g.name.lower() for g in request.user.groups.all()]
    
    try:
        with os.scandir(caminho_atual) as it:
            for entry in it:
                if entry.name == '.lixeira': continue
                
                # --- LÓGICA DE FILTRO (AGORA MAIS SEGURA) ---
                if modulo == 'setores' and not request.user.is_superuser:
                    # Se estiver na raiz, filtra pelo nome da pasta (que deve ser igual ao grupo)
                    if os.path.normpath(caminho_atual) == os.path.normpath(raiz_modulo):
                        if entry.is_dir() and entry.name.lower() not in usuario_grupos:
                            continue # Pula pastas que não são do grupo do usuário
                
                # --- ADICIONA ITENS ---
                if entry.is_dir():
                    itens.append({'nome': entry.name, 'tipo': 'pasta', 'tamanho': '-', 'caminho': entry.path, 'ordem': 0})
                
                elif entry.is_file():
                    if os.path.normpath(caminho_atual) != os.path.normpath(raiz_modulo):
                        tamanho = round(entry.stat().st_size / 1024, 2)
                        itens.append({'nome': entry.name, 'tipo': 'arquivo', 'tamanho': f"{tamanho} KB", 'caminho': entry.path, 'ordem': 1})
                        
    except (PermissionError, OSError) as e:
        print(f"DEBUG ERRO: {e}") # Importante: olhe seu terminal para ver se há erro aqui!
        messages.error(request, f"Erro de acesso: {str(e)}")

    # 5. Ordenação e Filtro
    ordem = request.GET.get('ordem', 'az')
    reverse_sort = (ordem == 'za')
    
    # Separa pastas de arquivos para garantir a integridade da estrutura
    pastas = [i for i in itens if i['tipo'] == 'pasta']
    arquivos = [i for i in itens if i['tipo'] == 'arquivo']
    
    # Ordena ambos
    pastas.sort(key=lambda x: x['nome'].lower(), reverse=reverse_sort)
    arquivos.sort(key=lambda x: x['nome'].lower(), reverse=reverse_sort)
    
    # Une novamente com pastas sempre no topo
    itens = pastas + arquivos

    # Paginação
    # 1. Tenta capturar o valor
    valor_raw = request.GET.get('por_pagina')

    # 2. Converte apenas se for um número válido, caso contrário usa o padrão 50
    try:
        por_pagina = int(valor_raw)
        if por_pagina not in [25, 50, 100]:
            por_pagina = 50
    except (TypeError, ValueError):
        por_pagina = 50

    # 3. Agora o paginator recebe o valor garantidamente inteiro
    paginator = Paginator(itens, por_pagina)
    pagina_atual = paginator.get_page(request.GET.get('page', 1))

    # Breadcrumbs (Navegação)
    relativo = os.path.relpath(caminho_atual, raiz_modulo)
    partes_pasta = []
    if relativo != ".":
        acumulado = raiz_modulo
        for parte in relativo.split(os.sep):
            acumulado = os.path.join(acumulado, parte)
            partes_pasta.append({'nome': parte, 'caminho': acumulado})

    contexto = {
        'modulo': modulo,
        'titulo': f"{titulo_base} - {os.path.basename(caminho_atual) if caminho_atual != raiz_modulo else 'Raiz'}",
        'resultados': pagina_atual,
        'caminho_pasta_atual': caminho_atual,
        'partes_pasta': partes_pasta,
        'exibir_botao_voltar': caminho_atual != raiz_modulo and not (modulo == 'setores' and not request.user.is_superuser and caminho_atual.lower().endswith(tuple(usuario_grupos))),
        'usuario_esta_na_raiz': os.path.normpath(caminho_atual) == os.path.normpath(raiz_modulo)
    }
    
    return render(request, 'core/navegar.html', contexto)

@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='inicio')
def ver_lixeira(request):
    """Exibe os arquivos e pastas que estão na lixeira física do sistema com filtros"""
    pasta_lixeira = settings.LIXEIRA_DIR
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
                
            # Busca o registro da lixeira
            item_lixeira = RegistroLixeira.objects.filter(nome_na_lixeira__iexact=item.strip()).first()
            if not item_lixeira:
                print(f"DEBUG: Não achei registro para o item: '{item.strip()}'")

            arquivos_lixeira.append({
                'nome': item,
                'tipo': tipo_item,
                'tamanho': tamanho,
                'caminho': caminho_completo,
                # Aqui usamos o ForeignKey 'apagado_por' definido no model
                'apagado_por': item_lixeira.apagado_por.username if item_lixeira and item_lixeira.apagado_por else "Desconhecido",
                # Aqui usamos o campo de data criado no model
                'data_exclusao': item_lixeira.data_exclusao if item_lixeira else None
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
    if request.method == 'POST':
        nome_na_lixeira = os.path.basename(request.POST.get('caminho_lixeira', '').strip())
        caminho_lixeira = os.path.join(settings.LIXEIRA_DIR, nome_na_lixeira)
        
        # BUSCA NOVO REGISTRO
        registro = RegistroLixeira.objects.filter(nome_na_lixeira=nome_na_lixeira).first()
        
        if registro:
            caminho_original = registro.caminho_original
            pasta_destino = os.path.dirname(caminho_original)
            
            if not os.path.exists(pasta_destino):
                os.makedirs(pasta_destino)
                
            try:
                shutil.move(caminho_lixeira, caminho_original)
                
                # Sucesso! Remove o registro da lixeira
                registro.delete() 
                
                messages.success(request, f"Restaurado com sucesso para: {caminho_original}")
            except Exception as e:
                messages.error(request, f"Erro ao restaurar: {str(e)}")
        else:
            messages.error(request, "Não encontramos o registro de origem no banco de dados.")
            
    return redirect('ver_lixeira')

@login_required
@user_passes_test(lambda u: u.is_superuser, login_url='inicio')
def ver_auditoria(request):
    """Exibe o histórico completo de ações realizadas no sistema (Logs de Auditoria)"""
    
    filtro_busca = request.GET.get('busca', '').strip()
    filtro_acao = request.GET.get('acao', '').strip()
    
    logs_list = LogAuditoria.objects.select_related('usuario').all()
    
    if filtro_busca:
        logs_list = logs_list.filter(descricao__icontains=filtro_busca)
    if filtro_acao:
        logs_list = logs_list.filter(acao=filtro_acao)
        
    paginator = Paginator(logs_list, 20)
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

        pasta_lixeira = settings.LIXEIRA_DIR
        
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
        
# No seu views.py
def exportar_auditoria(request):
    # Aqui vai a lógica que você usa para gerar o arquivo Excel
    # Por enquanto, para não dar erro, você pode apenas retornar um texto:
    return HttpResponse("Em desenvolvimento...")