#!/bin/bash

#usable_ports=("10000" "10001" "10002" "10003" "10004" "10005" "10006" "10007" "10008" "10009") #If can only run on specific ports, list those here and comment out next line
#usable_ports=("ALL") #For all ports above 5000

IFS="," read -a usable_ports <<< $USABLE_PORTS

#Got here: https://stackoverflow.com/questions/53839253/how-can-i-convert-an-array-into-a-comma-separated-string
join_arr() {
  local IFS="$1"
  shift
  echo "$*"
}

#See here: https://stackoverflow.com/questions/23462869/remove-element-from-bash-array-by-content-stored-in-variable-without-leaving-a
remaining_ports_csv() {
    local REMOVE_ELT="$1"
    local new_usable_ports=()
    for value in "${usable_ports[@]}"
    do
	[[ $value != $REMOVE_ELT ]] && new_usable_ports+=($value)
    done

    VAL=$(join_arr , "${new_usable_ports[@]}")
    echo $VAL;
}

#Got here: https://stackoverflow.com/questions/14366390/check-if-an-element-is-present-in-a-bash-array
array_contains () { 
    local array="$1[@]"
    local seeking=$2
    local in=1
    for element in "${!array}"; do
        if [[ $element == "$seeking" ]]; then
            in=0
            break
        fi
    done
    return $in
}

pull_locker_image() {
    docker pull ${LOCKER_IMAGE}
    EXITCODE=$?
    if ! test $EXITCODE -eq 0
    then
	echo "Error pulling image for Locker (note: you must be connected to VPN or corporate network to pull the image; also make sure you have set proxies in Docker.)"
	exit 1
    fi
}

check_locker_already_running() {

    if [ ! -z $(docker ps -q -f "name=^locker_\w+_\d+$") ]; then echo "Error: Locker is already running and should not be started again."; exit 1; fi

}


get_creds() {

    PRIVKEY_LOC=""
    PUBKEYKEY_LOC=""
    AWSCREDS_LOC=""

    if [[ -f /host_root$USER_HOMEDIR.locker/.ssh/id_rsa ]]
    then
	PRIVKEY_LOC=$USER_HOMEDIR.locker/.ssh/id_rsa
    elif [[ -f /host_root$USER_HOMEDIR.ssh/id_rsa ]]
    then
	PRIVKEY_LOC=$USER_HOMEDIR.ssh/id_rsa
    fi

    if [[ -f /host_root$USER_HOMEDIR.locker/.ssh/id_rsa.pub ]]
    then
	PUBKEY_LOC=$USER_HOMEDIR.locker/.ssh/id_rsa.pub
    elif [[ -f /host_root$USER_HOMEDIR.ssh/id_rsa.pub ]]
    then
	PUBKEY_LOC=$USER_HOMEDIR.ssh/id_rsa.pub
    fi

    if [[ -f /host_root$USER_HOMEDIR.locker/.aws/credentials ]]
    then
	AWSCREDS_LOC=$USER_HOMEDIR.locker/.aws/credentials
    elif [[ -f /host_root$USER_HOMEDIR.aws/credentials ]]
    then
	AWSCREDS_LOC=$USER_HOMEDIR.aws/credentials
    fi

}

#See here for why can't use port 5000 on Mac: https://progressstory.com/tech/port-5000-already-in-use-macos-monterey-issue/
if [[ "$PLATFORM" == "Mac" ]]; then
    RESET_USER_UGIDS='False'
    LOCKER_PORT="5001"
fi

if [[ "$PLATFORM" == "Win" ]]; then
    RESET_USER_UGIDS='False'
    LOCKER_PORT="5000"
fi

if [[ "$PLATFORM" == "Linux" ]]; then
    RESET_USER_UGIDS='True'
    LOCKER_PORT="5000"
fi

UIDGID_ENV=" --env RESET_USER_UGIDS=\"${RESET_USER_UGIDS}\""
if [ ! -z $USER_UID ]; then
    UIDGID_ENV="${UIDGID_ENV} --env DOCKER_HOST_USER_UID=\"${USER_UID}\""
fi
if [ ! -z $USER_GID ]; then
    UIDGID_ENV="${UIDGID_ENV} --env DOCKER_HOST_USER_GID=\"${USER_GID}\""
fi

while getopts hu:d:s:pu: option
do
case "${option}"
in
h) HELP="True";;
u) RUNASUSER=${OPTARG};;
d) USER_HOMEDIR=${OPTARG};;
s) LOCAL_OR_REMOTE=${OPTARG};;
p) TRYPULLUPDATEDLOCKERIMAGE="y";;
esac
done

if ! [ -z "$HELP" ]
then
    echo "usage: start_locker.sh -h -u <RUNASUSER> -d <HOMEDIR> -s <LOCAL_OR_REMOTE> -p"
    echo "-h : print this help message"
    echo "-u <RUNASUSER> : <RUNASUSER> should be the LDAP id of the user to run as (and make accessible to if running remotely)"
    echo "-d <HOMEDIR> : <HOMEDIR> will be searched for SSH keys, AWS creds, etc."
    echo "-s <LOCAL_OR_REMOTE> : 'l' for local (only localhost connections allowed), 'r' for remote (accessible over internet to <RUNASUSER>"
    echo "-p : try to pull updated Docker image for Locker"
    exit 0;
fi

CL_ARGS_FLAG=""
[ ! -z "$RUNASUSER" ] && CL_ARGS_FLAG="True"
[ ! -z "$USER_HOMEDIR" ] && CL_ARGS_FLAG="True"
[ ! -z "$LOCAL_OR_REMOTE" ] && CL_ARGS_FLAG="True"
[ ! -z "$TRYPULLUPDATEDLOCKERIMAGE" ] && CL_ARGS_FLAG="True"


#Make sure Docker is running first, exit with error if not
docker info > /dev/null 2>&1
EXITCODE=$?
if ! test $EXITCODE -eq 0
then
    echo "Error: Docker is not running, please Start docker first (e.g. 'sudo service docker start' on Linux)."
    exit 1
fi

#Check if Locker is already running, exit if it is
check_locker_already_running

#Make sure the Locker image has been pulled
#https://stackoverflow.com/questions/30543409/how-to-check-if-a-docker-image-with-a-specific-tag-exist-locally
if [[ "$(docker images -q ${LOCKER_IMAGE} 2> /dev/null)" == "" ]]; then
    echo "The Locker image '${LOCKER_IMAGE}' will be pulled now."
    pull_locker_image
else
    if [ -z "$CL_ARGS_FLAG" ]; then
       read -p "Would you like to try to pull an updated Locker image [y or n]? " TRYPULLUPDATEDLOCKERIMAGE
    fi
    if [[ "$TRYPULLUPDATEDLOCKERIMAGE" == "y" ]]; then
	echo "The Locker image '${LOCKER_IMAGE}' will be pulled now."
	pull_locker_image
    fi
fi


if [ -z "$CL_ARGS_FLAG" ]
then
   RUNASUSER=$USERNAME
   read -p "Run Locker as user [$RUNASUSER]: " CLI_RUNASUSER
   if ! [ -z "$CLI_RUNASUSER" ]
   then
       RUNASUSER=$CLI_RUNASUSER
   fi
fi

if [ -z "$CL_ARGS_FLAG" ]
then
    USER_HOMEDIR=$HOST_USER_HOMEDIR
    while :
    do
	read -p "User home directory [$USER_HOMEDIR]: " CLI_USER_HOMEDIR
	if [ -z "$CLI_USER_HOMEDIR" ]
	then
	    break
	fi
	if ! [ -d "/host_root$CLI_USER_HOMEDIR" ]
	then
	    echo "Directory does not exist, please choose again or hit enter to not set."
	else
	    break
	fi
    done

    if ! [ -z "$CLI_USER_HOMEDIR" ]
    then
	USER_HOMEDIR=$CLI_USER_HOMEDIR
    fi
fi

[[ "${USER_HOMEDIR}" != */ ]] && USER_HOMEDIR="${USER_HOMEDIR}/"

if [ -z "$CL_ARGS_FLAG" ]
then
    echo "Run the app local or remote (choose number)?"
    select LOCAL_OR_REMOTE in local remote;
    do
	case $LOCAL_OR_REMOTE in
	    "local")
		LOCAL_OR_REMOTE='l'
		break
		;;
	    "remote")
		LOCAL_OR_REMOTE='r'
		break
		;;
	    *)
		echo "Invalid entry, please choose again."
		;;
	esac
    done
fi

if [[ $LOCAL_OR_REMOTE = 'r' ]] && [[ ! -z ${CHECK_SERVER_VPNCORPNET} ]]; then
    PROXY_REACHABLE=$(ping -c1 ${CHECK_SERVER_VPNCORPNET} > /dev/null 2>&1 && echo "TRUE")
    if [ -z $PROXY_REACHABLE ]
    then
	echo "Error: you must be on the corporate network or VPN in order to run remote."
	exit 1;
    fi
fi

mkdir -p /host_root${USER_HOMEDIR}.locker
EXITCODE_MKDIR=$?
if [ $EXITCODE_MKDIR != 0 ]
then
    echo "Error creating .locker directory in ${USER_HOMEDIR}, please try and run the script again."
    exit 1
fi

if ! [ -e /host_root${USER_HOMEDIR}.locker/config.json ]
then

    get_creds

    $(echo -n "{\"config_sshPrivKeyFile\": \"${PRIVKEY_LOC}\", \"config_sshPubKeyFile\": \"${PUBKEY_LOC}\", \"config_awsCredsFile\": \"${AWSCREDS_LOC}\", \"config_offlineUsageStorage\": \"${USER_HOMEDIR}.locker\"}" > /host_root${USER_HOMEDIR}.locker/config.json)

    if [ ! -z $USER_UID ]; then
	$(chown -R ${USER_UID} /host_root${USER_HOMEDIR}.locker)
    fi
    if [ ! -z $USER_GID ]; then
	$(chgrp -R ${USER_GID} /host_root${USER_HOMEDIR}.locker)
    fi
    echo "Created initial config file for Locker at ${USER_HOMEDIR}.locker/config.json"
fi

PROXY_ENV=""
if [ ! -z $HTTP_PROXY ]; then
    PROXY_ENV="${PROXY_ENV} --env HTTP_PROXY=\"${HTTP_PROXY}\""
fi
if [ ! -z $HTTPS_PROXY ]; then
    PROXY_ENV="${PROXY_ENV} --env HTTPS_PROXY=\"${HTTPS_PROXY}\""
fi
if [ ! -z $FTP_PROXY ]; then
    PROXY_ENV="${PROXY_ENV} --env FTP_PROXY=\"${FTP_PROXY}\""
fi
if [ ! -z $NO_PROXY ]; then
    PROXY_ENV="${PROXY_ENV} --env NO_PROXY=\"${NO_PROXY}\""
fi

echo "RUNASUSER: $RUNASUSER"
echo "USER_HOMEDIR: $USER_HOMEDIR"
echo "LOCAL_OR_REMOTE: $LOCAL_OR_REMOTE"

if ! [ -z "$USER_HOMEDIR" ]
then
    USER_HOMEDIR_ENV=" --env USER_HOMEDIR=\"${USER_HOMEDIR}\""
else
    USER_HOMEDIR_ENV=""
fi

OTHER_ENV=" --env DOCKER_HOST_USER=\"${USERNAME}\" --env TZ=\"${CUR_TZ}\" --env RUNASUSER=\"${RUNASUSER}\" --env LOCAL_OR_REMOTE=\"${LOCAL_OR_REMOTE}\""

exec 2> /dev/null #redirect stderr to /dev/null for the rest of the program, see here: https://stackoverflow.com/questions/447101/temporary-redirection-of-stderr-in-a-bash-script
while true; do
    CONT_FLAG="false"
    array_contains usable_ports "ALL" || array_contains usable_ports $LOCKER_PORT || CONT_FLAG="true"
    if [[ $CONT_FLAG == "true" ]]; then
	LOCKER_PORT=$[$LOCKER_PORT+1]	
	continue
    fi
    USABLE_HOST_PORTS = ""
    array_contains usable_ports "ALL" || USABLE_HOST_PORTS=" --env DOCKER_HOST_USABLE_PORTS=\"$(remaining_ports_csv $LOCKER_PORT)\""
    if [ $LOCAL_OR_REMOTE == 'l' ]
    then
	EPOCH_SECS=`date +"%s"`
	CMD="docker run -dt ${UIDGID_ENV} --env DOCKER_HOST_LOCKER_PORT=\"${LOCKER_PORT}\" --env DOCKER_HOST_ROOT=\"${DOCKER_HOST_ROOT}\"${OTHER_ENV}${USER_HOMEDIR_ENV}${USABLE_HOST_PORTS}${PROXY_ENV} --env LOCKER_CONTAINER_NAME=\"locker_${RUNASUSER}_${EPOCH_SECS}\" -p 127.0.0.1:${LOCKER_PORT}:5000 -v ${DOCKER_HOST_ROOT}:/host_root -v /var/run/docker.sock:/var/run/docker.sock --name \"locker_${RUNASUSER}_${EPOCH_SECS}\" ${LOCKER_IMAGE} /locker/exec_locker.sh"
	DOCKER_CONT_ID=$(eval $CMD)
	EXITCODE=$?
	ACCESS_LOCKER_URL="http://localhost:${LOCKER_PORT}"
    else
	EPOCH_SECS=`date +"%s"`
	CMD="docker run -dt --hostname=\"${DOCKER_HOST_FQDN}\" ${UIDGID_ENV} --env DOCKER_HOST_LOCKER_PORT=\"${LOCKER_PORT}\" --env DOCKER_HOST_ROOT=\"${DOCKER_HOST_ROOT}\"${OTHER_ENV}${USER_HOMEDIR_ENV}${USABLE_HOST_PORTS}${PROXY_ENV} --env LOCKER_CONTAINER_NAME=\"locker_${RUNASUSER}_${EPOCH_SECS}\" -p ${LOCKER_PORT}:5000 -v ${DOCKER_HOST_ROOT}:/host_root -v /var/run/docker.sock:/var/run/docker.sock --name \"locker_${RUNASUSER}_${EPOCH_SECS}\" ${LOCKER_IMAGE} /locker/exec_locker.sh"
	DOCKER_CONT_ID=$(eval $CMD)
	EXITCODE=$?
	ACCESS_LOCKER_URL="${DOCKER_HOST_FQDN}:${LOCKER_PORT}"
    fi
    test $EXITCODE -eq 0 && break
    LOCKER_PORT=$[$LOCKER_PORT+1]
done

#Here is how to pipe a string into a file in a running Docker container:
#PIPERES=$(echo "{\"config_sshPrivKeyFile\": \"${PRIVKEY_LOC}\", \"config_sshPubKeyFile\": \"${PUBKEY_LOC}\", \"config_offlineUsageStorage\": \"${OFFLINE_STORAGE_LOC}\"}" | docker exec -i ${DOCKER_CONT_ID} sh -c 'cat - > /locker/config.json')

echo "DOCKER RUN COMMAND: $CMD"
echo "Successfully started locker as Docker container (id ${DOCKER_CONT_ID})"
echo "Access Locker at: ${ACCESS_LOCKER_URL}"

exit
