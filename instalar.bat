@echo off
rem Instala tudo dentro desta pasta (pergunta antes de baixar). Precisa do Python 3.10+ instalado.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 instalar.py %*) || (python instalar.py %*)
pause
