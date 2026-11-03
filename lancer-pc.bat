@echo off
rem Moniteur Pokemon 30 ans : lancement direct sur ce PC (double-clic).
rem Surveille les grandes enseignes qui bloquent les serveurs GitHub
rem (Carrefour, King Jouet, Cultura, Amazon...). Ajoute "tout" pour
rem surveiller aussi toutes les boutiques : lancer-pc.bat tout
chcp 65001 >nul
title Moniteur Pokemon 30 ans
cd /d "%~dp0"

set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || (
  echo Python est introuvable.
  echo Installe Python 3.12 depuis https://www.python.org/downloads/
  echo en cochant "Add python.exe to PATH", puis relance ce fichier.
  pause
  exit /b 1
)

set "OPTION="
if /i "%~1"=="tout" set "OPTION=--tout"

rem Mise a jour automatique si le dossier vient de "git clone".
where git >nul 2>nul && if exist ".git" git pull --ff-only --quiet

:boucle
%PY% moniteur.py --pc %OPTION%
echo.
echo Le moniteur s'est arrete. Nouveau depart dans 30 secondes (ferme la fenetre pour l'arreter).
timeout /t 30 /nobreak >nul
goto boucle
