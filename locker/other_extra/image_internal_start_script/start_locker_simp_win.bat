@ECHO OFF

REM If can only run on specific ports, list those here and comment out next line:
REM SET USABLE_PORTS=10000,10001,10002,10003,10004
REM For all ports above 5000
SET USABLE_PORTS=ALL

REM Change this to your own Docker registry where the Locker image can be pulled from.
REM (note that if you already have built it and it is available in your local machine's Docker
REM then you won't need to pull from this and this is sort of optional in that case).
SET LOCKER_IMAGE=docker.rdcloud.bms.com:443/rr:locker_opensource

REM If you are running Locker remotely and need to be on VPN or corporate network for that,
REM Set a value for this server. This server will be pinged, and if ping returns something
REM (doesn't time out) it will be assumed you are on a VPN or organization/corporate network.
SET CHECK_SERVER_VPNCORPNET=proxy-server.bms.com

REM Change to your proxy settings for your network (or set empty if no proxies needed)
SET PROXY_ENV= --env HTTP_PROXY="http://proxy-server.bms.com:8080" --env HTTPS_PROXY="http://proxy-server.bms.com:8080" --env FTP_PROXY="http://proxy-server.bms.com:8080" --env NO_PROXY="*.bms.com,localhost"

SET DOCKER_HOST_FQDN=%COMPUTERNAME%.%USERDNSDOMAIN%
For /f "tokens=*" %%t in ('tzutil /g') do (set CUR_TZ=%%t)

SET "ROOT=%cd:\="&rem %
SET DOCKER_HOST_ROOT=%ROOT::=%
SET DOCKER_HOST_ROOT=/%DOCKER_HOST_ROOT%/

SET PLATFORM=Win

SET HOST_USER_HOMEDIR=%USERPROFILE%
REM convert into Linux-like path for inside the container:
SET HOST_USER_HOMEDIR_ENV=%HOST_USER_HOMEDIR:\=/%
CALL SET HOST_USER_HOMEDIR_ENV=%%HOST_USER_HOMEDIR_ENV:%ROOT%=%%
SET HOST_USER_HOMEDIR=%HOST_USER_HOMEDIR_ENV%

SET CLI_ARGS=" %*"
IF [%CLI_ARGS%]==[" "] (SET CLI_ARGS=) ELSE (SET CLI_ARGS=%CLI_ARGS:"=%)

SET START_SCRIPT_CMD=docker run -it --rm --env DOCKER_HOST_FQDN="%DOCKER_HOST_FQDN%" --env USABLE_PORTS="%USABLE_PORTS%" --env PLATFORM="%PLATFORM%" --env LOCKER_IMAGE="%LOCKER_IMAGE%" --env CUR_TZ="%CUR_TZ%" --env USERNAME="%USERNAME%" --env HOST_USER_HOMEDIR="%HOST_USER_HOMEDIR%" --env DOCKER_HOST_ROOT="%DOCKER_HOST_ROOT%" --env CHECK_SERVER_VPNCORPNET="%CHECK_SERVER_VPNCORPNET%" %PROXY_ENV% -v %ROOT%/:/host_root -v /var/run/docker.sock:/var/run/docker.sock %LOCKER_IMAGE% /locker/image_internal_start_script/start_locker_internal.sh%CLI_ARGS%

REM ECHO %START_SCRIPT_CMD%
%START_SCRIPT_CMD%
