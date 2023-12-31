#!/bin/bash

#USABLE_PORTS=10000,10001,10002,10003,10004 #If can only run on specific ports, list those here and comment out next line
USABLE_PORTS=ALL #For all ports above 5000

#Change this to your own Docker registry where the Locker image can be pulled from.
#(note that if you already have built it and it is available in your local machine's Docker
#then you won't need to pull from this and this is sort of optional in that case).
LOCKER_IMAGE='docker.rdcloud.bms.com:443/rr:locker_opensource'

###Change to your proxy settings for your network (or set empty if no proxies needed)
PROXY_ENV=" --env HTTP_PROXY='http://proxy-server.bms.com:8080' --env HTTPS_PROXY='http://proxy-server.bms.com:8080' --env FTP_PROXY='http://proxy-server.bms.com:8080' --env NO_PROXY='*.bms.com,localhost'"

#If you are running Locker remotely and need to be on VPN or corporate network for that,
#Set a value for this server. This server will be pinged, and if ping returns something
#(doesn't time out) it will be assumed you are on a VPN or organization/corporate network.
CHECK_SERVER_VPNCORPNET=proxy-server.bms.com

DOCKER_HOST_FQDN=`hostname -f`

get_timezone() {

#Got from here and slightly modified: https://superuser.com/questions/309034/how-to-check-which-timezone-in-linux
if filename=$(readlink /etc/localtime); then
    # /etc/localtime is a symlink as expected
    CUR_TZ=${filename#*zoneinfo/}
    if [[ $CUR_TZ = "$filename" || ! $CUR_TZ =~ ^[^/]+/[^/]+$ ]]; then
        # not pointing to expected location or not Region/City
	CUR_TZ=""
    fi
fi

if [ -z $CUR_TZ ]; then
    if command -v timedatectl &> /dev/null
    then
	CUR_TZ=`timedatectl status | grep "zone" | sed -e 's/^[ ]*Time zone: \(.*\) (.*)$/\1/g'`
    fi
fi

# compare files by contents
if [ -z $CUR_TZ ]; then
    # https://stackoverflow.com/questions/12521114/getting-the-canonical-time-zone-name-in-shell-script#comment88637393_12523283
    CUR_TZ=$(find /usr/share/zoneinfo -type f ! -regex ".*/Etc/.*" -exec \
	       cmp -s {} /etc/localtime \; -print | sed -e 's@.*/zoneinfo/@@' | head -n1)
fi

if [ -z $CUR_TZ ]; then
    CUR_TZ=`date +%Z`
fi
}

get_username() {
    USERNAME=$USER
    if [ -z "$USERNAME" ]
    then
	USERNAME=$(id -u -n)
    fi
    if [ -z "$USERNAME" ]
    then
	USERNAME=$(whoami)
    fi
}

get_timezone
get_username

unameOut=$(uname -s)
case "${unameOut}" in
    Linux*)     PLATFORM=Linux;;
    Darwin*)    PLATFORM=Mac;;
    *)          PLATFORM="${unameOut}"
esac

USER_UID=$(id -u $USERNAME)
USER_GID=$(id -g $USERNAME)

eval HOST_USER_HOMEDIR="$(printf '~%q' "$USERNAME")"
DOCKER_HOST_ROOT=/

function join_by { local IFS="$1"; shift; echo "$*"; }

#See here: https://stackoverflow.com/questions/1527049/how-can-i-join-elements-of-a-bash-array-into-a-delimited-string
CLI_ARGS=$(printf " %s" "$@")
CLI_ARGS=${CLI_ARGS:1}
if ! [ -z $CLI_ARGS ]; then
    CLI_ARGS=" ${CLI_ARGS}"
else
    CLI_ARGS=""
fi

START_SCRIPT_CMD="docker run -it --rm --env DOCKER_HOST_FQDN=\"${DOCKER_HOST_FQDN}\" --env USABLE_PORTS=\"${USABLE_PORTS}\" --env PLATFORM=\"${PLATFORM}\" --env LOCKER_IMAGE=\"${LOCKER_IMAGE}\" --env CUR_TZ=\"${CUR_TZ}\" --env USERNAME=\"${USERNAME}\" --env HOST_USER_HOMEDIR=\"${HOST_USER_HOMEDIR}\" --env USER_UID=\"${USER_UID}\" --env USER_GID=\"${USER_GID}\" --env DOCKER_HOST_ROOT=\"/\" --env CHECK_SERVER_VPNCORPNET=\"${CHECK_SERVER_VPNCORPNET}\" ${PROXY_ENV} -v /:/host_root -v /var/run/docker.sock:/var/run/docker.sock ${LOCKER_IMAGE} /locker/image_internal_start_script/start_locker_internal.sh${CLI_ARGS}"

echo $START_SCRIPT_CMD
eval ${START_SCRIPT_CMD}
