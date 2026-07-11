@echo off
cd /d "%~dp0"
echo === Race Engineer Bawel — ACC ===
echo.
echo  [1] Mode GUI (Desktop App)   ^<-- DIREKOMENDASIKAN
echo  [2] Mode Console (terminal biasa)
echo.
set /p MODE="Pilih mode (1/2): "

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
