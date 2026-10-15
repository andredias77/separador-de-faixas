@echo off
rem Abre a mesa no navegador (o servidor fica rodando nesta janela; feche-a para parar).
cd /d "%~dp0"
".venv\Scripts\python.exe" mixer.py
