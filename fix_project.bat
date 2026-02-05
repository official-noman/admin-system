@echo off
echo Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Error installing dependencies!
    exit /b %errorlevel%
)

echo.
echo Running migrations...
python manage.py migrate
if %errorlevel% neq 0 (
    echo Error running migrations!
    exit /b %errorlevel%
)

echo.
echo Checking system...
python manage.py check
if %errorlevel% neq 0 (
    echo System check failed!
    exit /b %errorlevel%
)

echo.
echo Setup complete! You can now run the server.
pause
