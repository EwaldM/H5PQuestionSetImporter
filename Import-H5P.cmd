@echo off
setlocal
if "%~1"=="" (
    echo Drag a question .txt file onto a shortcut to this launcher.
    echo.
    pause
    exit /b 2
)
py -3 "%~dp0h5p_question_set.py" "%~1"
set "result=%errorlevel%"
echo.
pause
exit /b %result%
