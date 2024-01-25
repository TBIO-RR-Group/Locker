REM Build image
docker build --platform linux/amd64 -t rr:LockerSimpleImage -f "%~dp0/Dockerfile" "%~dp0."
