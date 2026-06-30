@echo off
:: Forçar a entrada na pasta do projeto
cd /d C:\GED_CRFPB

:: Ativar a venv explicitamente usando o caminho absoluto
call C:\GED_CRFPB\venv\Scripts\activate.bat

:: Rodar o servidor
python run_server.py