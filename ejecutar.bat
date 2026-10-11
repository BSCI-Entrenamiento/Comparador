@echo off
rem Ejecuta la comparacion de todas las categorias. Doble clic o desde el Programador de tareas.
rem Para una sola categoria: ejecutar.bat laptops
cd /d "%~dp0"
python -m comparador %*
