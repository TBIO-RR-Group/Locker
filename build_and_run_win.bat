@ECHO OFF

SET PORT=5000
SET SERVER_ADMIN=andrewsmith_97@yahoo.com
SET NAME=locker_rr
SET VERSION=locker_devtest
SET REGISTRY=dockerreg.example.com:443
SET ECR_REGISTRY=483421617021.dkr.ecr.us-east-1.amazonaws.com
SET LOCAL_TAG=%REGISTRY%/%NAME%:%VERSION%
SET REGISTRY_TAG=%ECR_REGISTRY%/%NAME%:%VERSION%

REM Build the image
docker build --build-arg PORT=%PORT% --build-arg SERVER_ADMIN=%SERVER_ADMIN% -t %LOCAL_TAG% -t %REGISTRY_TAG% -t %NAME%:%VERSION% -f Dockerfile .

REM Generate start script through docker container
docker run --rm %LOCAL_TAG% /locker/gen_start_script win > start_script.bat
SET START_SCRIPT=start_script.bat

REM Read the raw text into a variable
set /p RAW_STRING=<%START_SCRIPT%

REM Remove Unix-style byte order mark at the beinning of the file by encoding in UTF8
chcp 65001
echo %RAW_STRING% > %START_SCRIPT%

REM Run the start script
call %START_SCRIPT%
