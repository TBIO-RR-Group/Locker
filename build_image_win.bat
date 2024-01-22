@ECHO OFF

SET PORT=5000
SET SERVER_ADMIN=andrewsmith_97@yahoo.com
SET NAME=rr
SET VERSION=locker_devtest
SET REGISTRY=docker.rdcloud.bms.com:443
SET ECR_REGISTRY=483421617021.dkr.ecr.us-east-1.amazonaws.com
SET LOCAL_TAG=%REGISTRY%/%NAME%:%VERSION%
SET REGISTRY_TAG=%ECR_REGISTRY%/%NAME%:%VERSION%

docker build --build-arg PORT=%PORT% --build-arg SERVER_ADMIN=%SERVER_ADMIN% -t %LOCAL_TAG% -t %REGISTRY_TAG% -t %NAME%:%VERSION% -f Dockerfile .
