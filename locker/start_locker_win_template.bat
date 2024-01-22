@ECHO OFF

REM The Locker image at your own Docker registry where the Locker image can be pulled from.
REM (note that if you already have built it and it is available in your local machine's Docker
REM then you won't need to pull from this and this is sort of optional in that case).
SET LOCKER_IMAGE=__LOCKER_IMAGE__

REM If you are running Locker remotely and need to be on VPN or corporate network for that,
REM Set a value for this server. This server will be pinged, and if ping returns something
REM (doesn't time out) it will be assumed you are on a VPN or organization/corporate network.
SET CHECK_CORP_NETWORK_VPN_SERVER=__CHECK_CORP_NETWORK_VPN_SERVER__

For /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c-%%a-%%b)
For /f "tokens=1-2 delims=/:" %%a in ("%TIME%") do (set mytime=%%a%%b)
For /f "tokens=*" %%t in ('tzutil /g') do (set CUR_TZ=%%t)
SET CUR_DATETIME=%mydate%_%mytime%
SET CUR_DATETIME=%CUR_DATETIME: =%
SET HOSTNAME_FQDN=%COMPUTERNAME%.%USERDNSDOMAIN%
set "ROOT=%cd:\="&rem %

Rem Make sure Docker is running first, exit with error if not
docker info > nul
IF %ERRORLEVEL% NEQ 0 (
    ECHO Error: Docker is not running, please Start Docker first.
    EXIT /b 1
) else (
    ECHO Docker is running...
)

Rem If Locker is already running, don't let them start it again
SET CHECK_LOCKER_RUNNING_CMD=docker ps -q -f "name=^locker_\w+_[\d-_]+$"
%CHECK_LOCKER_RUNNING_CMD% > %TEMP%\locker_running_output.txt
SET /p CHECK_LOCKER_RUNNING_RES=<%TEMP%\locker_running_output.txt
DEL %TEMP%\locker_running_output.txt
IF [%CHECK_LOCKER_RUNNING_RES%] NEQ [] (
   ECHO "Error: Locker is already running and should not be started again."
   EXIT /b 1
)

docker images -q %LOCKER_IMAGE% > %TEMP%\check_locker_latest.txt 2> nul
SET /p LOCKER_TAG_INFO=<%TEMP%\check_locker_latest.txt
DEL %TEMP%\check_locker_latest.txt
IF [%LOCKER_TAG_INFO%] == [] (
   ECHO "The Locker image '%LOCKER_IMAGE%' will be pulled now."
   docker pull %LOCKER_IMAGE%
   IF %ERRORLEVEL% NEQ 0 (
      ECHO "Error pulling image for Locker (note: you must be connected to VPN or BMS corporate network to pull the image; also make sure you have set proxies in Docker.)"
      EXIT /b 1
   )
)

SET TRYPULLUPDATEDLOCKERIMAGE=n
IF NOT [%LOCKER_TAG_INFO%] == [] SET /p TRYPULLUPDATEDLOCKERIMAGE=Would you like to try to pull an updated Locker image [y or n]? 
IF "%TRYPULLUPDATEDLOCKERIMAGE%"=="y" (
   ECHO "The Locker image '%LOCKER_IMAGE%' will be pulled now."
   docker pull %LOCKER_IMAGE%
   IF %ERRORLEVEL% NEQ 0 (
      ECHO "Error pulling image for Locker (note: you must be connected to VPN or BMS corporate network to pull the image; also make sure you have set proxies in Docker.)"
      EXIT /b 1
   )
)

set /p RUNASUSER=Run Locker as user [%USERNAME%]: 
IF [%RUNASUSER%] == [] (
   SET RUNASUSER=%USERNAME%
)

:set_user_homedir
SET USER_HOMEDIR=
set /p USER_HOMEDIR=User home directory [%USERPROFILE%]: 
IF [%USER_HOMEDIR%] == [] (
   SET USER_HOMEDIR=%USERPROFILE%
)
IF DEFINED USER_HOMEDIR if not "%USER_HOMEDIR:~-1%"=="\" SET USER_HOMEDIR=%USER_HOMEDIR%\
IF NOT EXIST %USER_HOMEDIR% (
   ECHO %USER_HOMEDIR% does not exist, please set a different location
   GOTO set_user_homedir
)

:local_or_remote
set /p LOCAL_OR_REMOTE=Run the app local (l) or remote(r)? 
IF NOT "%LOCAL_OR_REMOTE%"=="l" IF NOT "%LOCAL_OR_REMOTE%"=="r" (
   GOTO local_or_remote
)

IF NOT EXIST %USER_HOMEDIR%.locker (
   ECHO %USER_HOMEDIR%.locker does not exist, creating it...
   mkdir %USER_HOMEDIR%.locker
   IF NOT EXIST %USER_HOMEDIR%.locker (
      ECHO Error creating .locker directory in %USER_HOMEDIR%, please try and run the script again.
      EXIT /b 1
   )
)

IF EXIST %USER_HOMEDIR%.locker\.ssh\id_privkey set PRIVKEY_LOC=%USER_HOMEDIR%.locker\.ssh\id_privkey
IF EXIST %USER_HOMEDIR%.ssh\id_privkey set PRIVKEY_LOC=%USER_HOMEDIR%.ssh\id_privkey
IF EXIST %USER_HOMEDIR%.locker\.ssh\id_privkey.pub set PUBKEY_LOC=%USER_HOMEDIR%.locker\.ssh\id_privkey.pub
IF EXIST %USER_HOMEDIR%.ssh\id_privkey.pub set PUBKEY_LOC=%USER_HOMEDIR%.ssh\id_privkey.pub
IF EXIST %USER_HOMEDIR%.locker\.aws\credentials set AWSCREDS_LOC=%USER_HOMEDIR%.locker\.aws\credentials
IF EXIST %USER_HOMEDIR%.aws\credentials set AWSCREDS_LOC=%USER_HOMEDIR%.aws\credentials

rem convert them into Linux-like paths for inside the container:
SET ESC_PRIVKEY_LOC=%PRIVKEY_LOC:\=/%
CALL SET ESC_PRIVKEY_LOC=%%ESC_PRIVKEY_LOC:%ROOT%=%%
SET ESC_PUBKEY_LOC=%PUBKEY_LOC:\=/%
CALL SET ESC_PUBKEY_LOC=%%ESC_PUBKEY_LOC:%ROOT%=%%
SET ESC_AWSCREDS_LOC=%AWSCREDS_LOC:\=/%
CALL SET ESC_AWSCREDS_LOC=%%ESC_AWSCREDS_LOC:%ROOT%=%%
IF NOT EXIST %USER_HOMEDIR%.locker\config.json (
   ECHO {"config_sshPrivKeyFile": "%ESC_PRIVKEY_LOC%", "config_sshPubKeyFile": "%ESC_PUBKEY_LOC%", "config_awsCredsFile": "%ESC_AWSCREDS_LOC%", "config_offlineUsageStorage": ""}> %USER_HOMEDIR%.locker\config.json
)

ECHO RUNASUSER: %RUNASUSER%
ECHO USER_HOMEDIR: %USER_HOMEDIR%
ECHO LOCAL_OR_REMOTE: %LOCAL_OR_REMOTE%
ECHO PRIVKEY_LOC: %PRIVKEY_LOC%
ECHO PUBKEY_LOC: %PUBKEY_LOC%
ECHO AWSCREDS_LOC: %AWSCREDS_LOC%
ECHO LOCKER DIR: %USER_HOMEDIR%.locker

rem convert into Linux-like path for inside the container:
SET USER_HOMEDIR_ENV=%USER_HOMEDIR:\=/%
CALL SET USER_HOMEDIR_ENV=%%USER_HOMEDIR_ENV:%ROOT%=%%

SET LOCKER_PORT=5000

SET DOCKER_HOST_ROOT=%ROOT::=%
SET DOCKER_HOST_ROOT=/%DOCKER_HOST_ROOT%/

SET PROXY_ENV=--env http_proxy="__http_proxy__" --env https_proxy="__https_proxy__" --env ftp_proxy="__ftp_proxy__" --env no_proxy="__no_proxy__"

:start_locker
IF "%LOCAL_OR_REMOTE%"=="l" (
   ECHO Running Locker locally on port %LOCKER_PORT%...
   SET DOCKER_RUN_CMD=docker run --rm -dt --privileged --env RESET_USER_UGIDS="False" --env DOCKER_HOST_LOCKER_PORT="%LOCKER_PORT%" --env DOCKER_HOST_ROOT="%DOCKER_HOST_ROOT%" --env DOCKER_HOST_USER="%USERNAME%" --env USER_HOMEDIR="%USER_HOMEDIR_ENV%" %PROXY_ENV% --env TZ="%CUR_TZ%" --env RUNASUSER="%RUNASUSER%" --env LOCAL_OR_REMOTE="l" --env LOCKER_CONTAINER_NAME="locker_%RUNASUSER%_%CUR_DATETIME%" -p 127.0.0.1:%LOCKER_PORT%:5000 -v %ROOT%/:/host_root -v /var/run/docker.sock:/var/run/docker.sock --name "locker_%RUNASUSER%_%CUR_DATETIME%" %LOCKER_IMAGE% /locker/exec_locker.sh


)

IF "%LOCAL_OR_REMOTE%"=="r" (
   IF [%CHECK_CORP_NETWORK_VPN_SERVER%]==[""] (
      REM NOOP
   ) ELSE (
      ping -n 1 %CHECK_CORP_NETWORK_VPN_SERVER% > $null
      IF %ERRORLEVEL% NEQ 0 (
      	 ECHO Error: you must be on the corporate network or VPN in order to run remote.
      	 EXIT /b 1
      )
   )

   ECHO Running Locker remotely on port %LOCKER_PORT%...
   SET DOCKER_RUN_CMD=docker run --rm -dt --hostname="%HOSTNAME_FQDN%" --env RESET_USER_UGIDS="False" --env DOCKER_HOST_LOCKER_PORT="%LOCKER_PORT%" --env DOCKER_HOST_ROOT="%DOCKER_HOST_ROOT%" --env DOCKER_HOST_USER="%USERNAME%" --env USER_HOMEDIR="%USER_HOMEDIR_ENV%"  %PROXY_ENV% --env TZ="%CUR_TZ%" --env RUNASUSER="%RUNASUSER%" --env LOCAL_OR_REMOTE="r" --env LOCKER_CONTAINER_NAME="locker_%RUNASUSER%_%CUR_DATETIME%" -p %LOCKER_PORT%:5000 -v %ROOT%/:/host_root -v /var/run/docker.sock:/var/run/docker.sock --name "locker_%RUNASUSER%_%CUR_DATETIME%" %LOCKER_IMAGE% /locker/exec_locker.sh
)

%DOCKER_RUN_CMD% > %TEMP%\docker_run_output.txt
SET EXITCODE=%ERRORLEVEL%
IF %EXITCODE% NEQ 0 (
   SET /a "LOCKER_PORT=%LOCKER_PORT%+1"
   GOTO start_locker
)

SET /p DOCKER_CONT_ID=<%TEMP%\docker_run_output.txt
SET ACCESS_LOCKER_URL=http://localhost:%LOCKER_PORT%
DEL %TEMP%\docker_run_output.txt

IF "%LOCAL_OR_REMOTE%"=="r" (
   docker exec %DOCKER_CONT_ID% python /locker/access_locker_info.py > %TEMP%\access_locker_info.txt
   SET /p ACCESS_LOCKER_URL=<%TEMP%\access_locker_info.txt
   DEL %TEMP%\access_locker_info.txt
   SET ACCESS_LOCKER_URL=%ACCESS_LOCKER_URL%:%LOCKER_PORT%
)

ECHO DOCKER RUN COMMAND: %DOCKER_RUN_CMD%
ECHO Successfully started locker as Docker container (id %DOCKER_CONT_ID%)
ECHO Access Locker at: %ACCESS_LOCKER_URL%
