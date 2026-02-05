@echo off
echo Cleaning up old builds...
if exist "venv" (
    echo Virtual environment detected.
)

echo.
echo Installing safe dependencies (Axes, CSP, WhiteNoise)...
pip install django-axes django-csp whitenoise python-dotenv

echo.
echo Attempting to install other requirements...
pip install -r requirements.txt

echo.
echo Running Migrations...
python manage.py migrate

echo.
echo Checking for System Errors...
python manage.py check

echo.
echo If you see "ModuleNotFoundError", the installation failed.
echo If "migrate" executed successfully, you are good to go!
pause
