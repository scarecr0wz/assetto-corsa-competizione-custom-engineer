@echo off
cd /d "%~dp0"
echo === ACC - Custom Race Engineer ===
echo.
echo  [1] Mode GUI (Desktop App)   ^<-- Recommended
echo  [2] Mode Console (Terminal)
echo.
set /p MODE="Mode select (1/2): "

REM Inject broadcasting.json with correct password
powershell -Command "$path='C:\Users\USER\Documents\Assetto Corsa Competizione\Config\broadcasting.json'; $content=\"{\`n    \`\"updListenerPort\`\": 9000,\`n    \`\"connectionPassword\`\": \`\"asd\`\",\`n    \`\"commandPassword\`\": \`\"\`\"\`n}\"; [System.IO.File]::WriteAllText($path, $content, [System.Text.Encoding]::Unicode); Write-Host 'broadcasting.json OK (port 9000, password asd)'"

echo.

if "%MODE%"=="2" (
    echo Starting engineer ^(console mode^)...
    echo.
    "C:\Users\USER\AppData\Local\Python\bin\python3.14.exe" main.py
) else (
    echo Starting engineer ^(GUI mode^)...
    echo.
    "C:\Users\USER\AppData\Local\Python\bin\python3.14.exe" gui_app.py
)

pause
