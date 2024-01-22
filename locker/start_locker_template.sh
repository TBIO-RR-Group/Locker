#!/bin/bash

usable_ports=__USABLE_PORTS__

#The Locker image at your own Docker registry where the Locker image can be pulled from.
#(note that if you already have built it and it is available in your local machine's Docker
#then you won't need to pull from this and this is sort of optional in that case).
LOCKER_IMAGE=__LOCKER_IMAGE__

#If you are running Locker remotely and need to be on VPN or corporate network for that,
#Set a value for this server. This server will be pinged, and if ping returns something
#(doesn't time out) it will be assumed you are on a VPN or organization/corporate network.
CHECK_CORP_NETWORK_VPN_SERVER=__CHECK_CORP_NETWORK_VPN_SERVER__

# Pass in additional variables from config.yml
CONTAINER_USER=__CONTAINER_USER__
http_proxy=__http_proxy__
https_proxy=__https_proxy__
ftp_proxy=__ftp_proxy__
no_proxy=__no_proxy__

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

pull_locker_image() {
    docker pull ${LOCKER_IMAGE}
    EXITCODE=$?
    if ! test $EXITCODE -eq 0
    then
	echo "Error pulling image for Locker (note: you must be connected to VPN or corporate network to pull the image; also make sure you have set proxies in Docker.)"
	exit 1
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

get_creds() {

    PRIVKEY_LOC=""
    PUBKEYKEY_LOC=""
    AWSCREDS_LOC=""

    if [[ -f $USER_HOMEDIR.locker/.ssh/id_privkey ]]
    then
	PRIVKEY_LOC=$USER_HOMEDIR.locker/.ssh/id_privkey
    elif [[ -f $USER_HOMEDIR.ssh/id_privkey ]]
    then
	PRIVKEY_LOC=$USER_HOMEDIR.ssh/id_privkey
    fi

    if [[ -f $USER_HOMEDIR.locker/.ssh/id_privkey.pub ]]
    then
	PUBKEY_LOC=$USER_HOMEDIR.locker/.ssh/id_privkey.pub
    elif [[ -f $USER_HOMEDIR.ssh/id_privkey.pub ]]
    then
	PUBKEY_LOC=$USER_HOMEDIR.ssh/id_privkey.pub
    fi

    if [[ -f $USER_HOMEDIR.locker/.aws/credentials ]]
    then
	AWSCREDS_LOC=$USER_HOMEDIR.locker/.aws/credentials
    elif [[ -f $USER_HOMEDIR.aws/credentials ]]
    then
	AWSCREDS_LOC=$USER_HOMEDIR.aws/credentials
    fi

}

check_locker_already_running() {

    if [ ! -z $(docker ps -q -f "name=^locker_\w+_\d+$") ]; then echo "Error: Locker is already running and should not be started again."; exit 1; fi

}

create_example_init_script() {

if ! [ -e ${USER_HOMEDIR}.locker/init_locker.sh ]
then
cat <<EOF >> ${USER_HOMEDIR}.locker/init_locker.sh
#!/bin/bash

###
# Environment variables interpolated and used below (change these to suit
# yourself):
###
NAME=${USERNAME}
EMAIL=${GIT_EMAIL}
HOMEDIR=${USER_HOMEDIR}


###
# Following lines setup the use of a persistent RStudio preferences file
# (rstudio-prefs.json) on your Docker host:
###

# Create rstudio config dir (if it doesn't exist already) in the container user's
# home directory (rstudio-prefs.json goes in there):
mkdir -p $HOMEDIR/.config/rstudio

# Delete any existing default rstudio-prefs.json file in that location (we're
# going to change to our own that is persistent and saved in the host machine):
test -e $HOMEDIR/.config/rstudio/rstudio-prefs.json && unlink $HOMEDIR/.config/rstudio/rstudio-prefs.json

# Check if the user has a persistent (stored under /host_root, i.e. on the host
# machine) rstudio-prefs.json file; create empty one if not:
test -e /host_root/$HOMEDIR/.locker/rstudio-prefs.json || echo "{}" > /host_root/$HOMEDIR/.locker/rstudio-prefs.json

# Link the user's persistent rstudio-prefs.json file into the continer user home
# dir to set it as the live rstudio-prefs.json file:
test -e /host_root/$HOMEDIR/.locker/rstudio-prefs.json && ln -s /host_root/$HOMEDIR/.locker/rstudio-prefs.json $HOMEDIR/.config/rstudio/


###
#Setup a .gitconfig file (so Git doesn't query you for your username and email):
###
echo -e "[user]\n\tname = $NAME\n\temail = $EMAIL" > $HOMEDIR/.gitconfig
chown ${CONTAINER_USER}:${CONTAINER_USER} $HOMEDIR/.gitconfig
EOF

chmod +x ${USER_HOMEDIR}.locker/init_locker.sh
fi

}

create_example_envvar_file() {

if ! [ -e ${USER_HOMEDIR}.locker/locker.env ]
then
cat <<EOF >> ${USER_HOMEDIR}.locker/locker.env
R_LIBS_USER=/host_root/${USER_HOMEDIR}/.locker/R_LIBS_USER/
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=...
EOF
fi

}

get_username

unameOut=$(uname -s)
case "${unameOut}" in
    Linux*)     PLATFORM=Linux;;
    Darwin*)    PLATFORM=Mac;;
    *)          PLATFORM="${unameOut}"
esac

USER_UID=$(id -u $USERNAME)
USER_GID=$(id -g $USERNAME)

#See here for why can't use port 5000 on Mac: https://progressstory.com/tech/port-5000-already-in-use-macos-monterey-issue/
if [[ "$PLATFORM" != "Mac" ]]; then
    RESET_USER_UGIDS='True'
    LOCKER_PORT="5000"
else
    RESET_USER_UGIDS='False'
    LOCKER_PORT="5001"
fi

UIDGID_ENV=" --env DOCKER_HOST_USER_UID=$USER_UID --env DOCKER_HOST_USER_GID=$USER_GID --env RESET_USER_UGIDS=$RESET_USER_UGIDS"

while getopts hu:d:s:pu:e: option; do
    case "${option}" in
        h) HELP="True";;
        u) RUNASUSER=${OPTARG};;
        d) USER_HOMEDIR=${OPTARG};;
        s) LOCAL_OR_REMOTE=${OPTARG};;
        p) TRYPULLUPDATEDLOCKERIMAGE="y";;
        e) GIT_EMAIL=${OPTARG};;
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
    echo "-e <GIT_EMAIL> : <GIT_EMAIL> email for pushing to and pulling from Git."
    exit 0;
fi

CL_ARGS_FLAG=""
[ ! -z "$RUNASUSER" ] && CL_ARGS_FLAG="True"
[ ! -z "$USER_HOMEDIR" ] && CL_ARGS_FLAG="True"
[ ! -z "$LOCAL_OR_REMOTE" ] && CL_ARGS_FLAG="True"
[ ! -z "$TRYPULLUPDATEDLOCKERIMAGE" ] && CL_ARGS_FLAG="True"
[ ! -z "$GIT_EMAIL" ] && CL_ARGS_FLAG="True"


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
    #See: https://stackoverflow.com/questions/2069467/have-to-determine-all-users-home-directories-tilde-scripting-problem/2069835#2069835
    #eval USER_HOMEDIR=~${RUNASUSER}
    eval USER_HOMEDIR="$(printf '~%q' "$RUNASUSER")"

    while :
    do
	read -p "User home directory [$USER_HOMEDIR]: " CLI_USER_HOMEDIR
	if [ -z "$CLI_USER_HOMEDIR" ]
	then
	    break
	fi
	if ! [ -d "$CLI_USER_HOMEDIR" ]
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
   GIT_EMAIL="${USERNAME}@email.com"
   read -p "Git email for locker [$GIT_EMAIL]: " CLI_GIT_EMAIL
   if ! [ -z "$CLI_GIT_EMAIL" ]
   then
       GIT_EMAIL=$CLI_GIT_EMAIL
   fi
fi

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

if [[ $LOCAL_OR_REMOTE = 'r' ]] && [[ ! -z ${CHECK_CORP_NETWORK_VPN_SERVER} ]]; then
    PROXY_REACHABLE=$(ping -c1 ${CHECK_CORP_NETWORK_VPN_SERVER} > /dev/null 2>&1 && echo "TRUE")
    if [ -z $PROXY_REACHABLE ]
    then
	echo "Error: you must be on the organization network or VPN in order to run remote."
	exit 1;
    fi
fi

###Change to your proxy settings for your network (or set empty if no proxies needed)
PROXY_ENV=" --env http_proxy=${http_proxy} --env https_proxy=${https_proxy} --env ftp_proxy=${ftp_proxy} --env no_proxy=${no_proxy}"

echo "RUNASUSER: $RUNASUSER"
echo "USER_HOMEDIR: $USER_HOMEDIR"
echo "GIT_EMAIL: $GIT_EMAIL"
echo "LOCAL_OR_REMOTE: $LOCAL_OR_REMOTE"

if ! [ -z "$USER_HOMEDIR" ]
then
    USER_HOMEDIR_ENV=" --env USER_HOMEDIR=${USER_HOMEDIR}"
else
    USER_HOMEDIR_ENV=""
fi

if ! mkdir -p ${USER_HOMEDIR}.locker
then
    echo "Error creating .locker directory in ${USER_HOMEDIR}, please try and run the script again."
    exit 1
fi

if ! [ -e ${USER_HOMEDIR}.locker/config.json ]
then

    get_creds

    $(echo -n "{\"config_sshPrivKeyFile\": \"${PRIVKEY_LOC}\", \"config_sshPubKeyFile\": \"${PUBKEY_LOC}\", \"config_awsCredsFile\": \"${AWSCREDS_LOC}\", \"config_offlineUsageStorage\": \"${USER_HOMEDIR}.locker\"}" > ${USER_HOMEDIR}.locker/config.json)
fi

create_example_init_script
create_example_envvar_file

get_timezone
OTHER_ENV=" --env DOCKER_HOST_USER=${USERNAME} --env TZ=${CUR_TZ} --env RUNASUSER=${RUNASUSER} --env LOCAL_OR_REMOTE=${LOCAL_OR_REMOTE}"

exec 2> /dev/null #redirect stderr to /dev/null for the rest of the program, see here: https://stackoverflow.com/questions/447101/temporary-redirection-of-stderr-in-a-bash-script
while true; do
    CONT_FLAG="false"
    array_contains usable_ports "ALL" || array_contains usable_ports $LOCKER_PORT || CONT_FLAG="true"
    if [[ $CONT_FLAG == "true" ]]; then
	LOCKER_PORT=$[$LOCKER_PORT+1]	
	continue
    fi
    USABLE_HOST_PORTS = ""
    array_contains usable_ports "ALL" || USABLE_HOST_PORTS=" --env DOCKER_HOST_USABLE_PORTS=$(remaining_ports_csv $LOCKER_PORT)"
    if [ $LOCAL_OR_REMOTE == 'l' ]
    then
	EPOCH_SECS=`date +"%s"`
	CMD="docker run -dt ${UIDGID_ENV} --env DOCKER_HOST_LOCKER_PORT=${LOCKER_PORT} --env DOCKER_HOST_ROOT=/${OTHER_ENV}${USER_HOMEDIR_ENV}${USABLE_HOST_PORTS}${PROXY_ENV} --env LOCKER_CONTAINER_NAME=locker_${RUNASUSER}_${EPOCH_SECS} -p 127.0.0.1:${LOCKER_PORT}:5000 -v /:/host_root -v /var/run/docker.sock:/var/run/docker.sock --name locker_${RUNASUSER}_${EPOCH_SECS} ${LOCKER_IMAGE} /locker/exec_locker.sh"
	DOCKER_CONT_ID=$($CMD)	
	EXITCODE=$?
	ACCESS_LOCKER_URL="http://localhost:${LOCKER_PORT}"
    else
	EPOCH_SECS=`date +"%s"`
	CMD="docker run -dt --hostname=`hostname -f` ${UIDGID_ENV} --env DOCKER_HOST_LOCKER_PORT=${LOCKER_PORT} --env DOCKER_HOST_ROOT=/${OTHER_ENV}${USER_HOMEDIR_ENV}${USABLE_HOST_PORTS}${PROXY_ENV} --env LOCKER_CONTAINER_NAME=locker_${RUNASUSER}_${EPOCH_SECS} -p ${LOCKER_PORT}:5000 -v /:/host_root -v /var/run/docker.sock:/var/run/docker.sock --name locker_${RUNASUSER}_${EPOCH_SECS} ${LOCKER_IMAGE} /locker/exec_locker.sh"
	DOCKER_CONT_ID=$($CMD)
	EXITCODE=$?
	ACCESS_LOCKER_URL=`docker exec ${DOCKER_CONT_ID} python /locker/access_locker_info.py`
	ACCESS_LOCKER_URL="${ACCESS_LOCKER_URL}:${LOCKER_PORT}"
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
