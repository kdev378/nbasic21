@echo off
rem ========================================================================
rem nbc.bat — NBASIC-21 かんたんビルドコマンド (Windows 用)
rem ========================================================================
rem
rem   使い方 (リポジトリのフォルダで):
rem     tools\nbc run  プログラム.bas [引数...]   コンパイルして実行
rem     tools\nbc build プログラム.bas            実行ファイルを作るだけ
rem     tools\nbc check プログラム.bas            エラー検査だけ
rem
rem Python (py または python) と gcc (MinGW-w64) が必要。
rem 入れ方は docs\book\01-setup.md を見てください。
rem ========================================================================

setlocal enabledelayedexpansion

rem --- このスクリプトの場所からリポジトリのルートを求める ---
set "ROOT=%~dp0.."
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"

rem --- Python を探す (py ランチャー優先) ---
set "PY=py"
where py >nul 2>nul || set "PY=python"
where %PY% >nul 2>nul || (
    echo nbc: Python が見つかりません。docs\book\01-setup.md を見てください 1>&2
    exit /b 1
)

rem --- gcc を探す ---
where gcc >nul 2>nul || (
    echo nbc: gcc が見つかりません。docs\book\01-setup.md を見てください 1>&2
    exit /b 1
)

set "MODE=%~1"
set "SRC=%~2"
if "%MODE%"=="" goto :usage
if "%SRC%"=="" goto :usage

rem --- 出力の名前: プログラム.bas → プログラム.exe ---
set "BASE=%~dpn2"

if "%MODE%"=="check" (
    %PY% -m nbasic --check "%SRC%"
    exit /b %errorlevel%
)

if not "%MODE%"=="run" if not "%MODE%"=="build" goto :usage

%PY% -m nbasic -O -o "%BASE%.c" "%SRC%" >nul
if errorlevel 1 exit /b 1
gcc -O2 -I "%ROOT%\runtime" "%BASE%.c" "%ROOT%\runtime\nbrt.c" -o "%BASE%.exe"
if errorlevel 1 exit /b 1
del "%BASE%.c"

if "%MODE%"=="build" (
    echo できました: %BASE%.exe
    exit /b 0
)

rem --- 実行 (3 番目以降の引数をそのまま渡す) ---
shift
shift
set "ARGS="
:collect
if "%~1"=="" goto :runit
set "ARGS=%ARGS% %1"
shift
goto :collect
:runit
"%BASE%.exe"%ARGS%
exit /b %errorlevel%

:usage
echo 使い方: tools\nbc run^|build^|check プログラム.bas [実行時の引数...] 1>&2
exit /b 1
