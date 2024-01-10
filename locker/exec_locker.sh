#!/bin/bash

#Execute this inside the container before starting Locker:
#First get the owner and group of /var/run/docker.sock INSIDE THE CONTAINER; they might be numeric if no corresponding group exists in container
# --> call thse CONT_DOCKER_SOCK_OWNER_UID and CONT_DOCKER_SOCK_GROUP_GID (these are the IDs of the groups)
#If doesn't already exist, create a new user for DOCKER_HOST_USER with user ID DOCKER_HOST_USER_UID (will try to run Locker under this account if has rw access to /var/run/docker.sock)
#If the group of /var/run/docker.sock was numeric, create group docker having group ID of CONT_DOCKER_SOCK_GROUP_GID
#Add DOCKER_HOST_USER to the docker group just created (or existing one if already existed).
#Check if DOCKER_HOST_USER has write access to /var/run/docker.sock (e.g. sudo -u DOCKER_HOST_USER test -w /var/run/docker.sock && echo "YES")
#If DOCKER_HOST_USER does have write access to /var/run/docker.sock, then it is via the docker group they were added to
# ---> go ahead and run Locker under DOCKER_HOST_USER: sudo -E -u $DOCKER_HOST_USER python /locker/app.py --local_or_remote $LOCAL_OR_REMOTE --run_as_user $RUNASUSER
# ---> this should be the case and work on Linux (but maybe not Mac)
#If DOCKER_HOST_USER does not have write access to /var/run/docker.sock via their membership in docker group, just need to run Locker as the user who owns /var/run/docker.sock
#Find the user corresponding to CONT_DOCKER_SOCK_OWNER_ID (create new user docker_user with this ID if doesn't exist) and run Locker under that user:
#--> sudo -E -u $CONT_DOCKER_SOCK_OWNER python /locker/app.py --local_or_remote $LOCAL_OR_REMOTE --run_as_user $RUNASUSER
#--> This should be the case and work on Mac; not sure about how Windows will work, need to check and test that later

CONT_DOCKER_SOCK_OWNER=`stat -c '%U' /var/run/docker.sock`
CONT_DOCKER_SOCK_OWNER_UID=`stat -c '%u' /var/run/docker.sock`
CONT_DOCKER_SOCK_GROUP=`stat -c '%G' /var/run/docker.sock`
CONT_DOCKER_SOCK_GROUP_GID=`stat -c '%g' /var/run/docker.sock`

if [ $CONT_DOCKER_SOCK_OWNER == "UNKNOWN" ]
then
   useradd -u $CONT_DOCKER_SOCK_OWNER_UID docker_owner
   CONT_DOCKER_SOCK_OWNER="docker_owner"
fi

if [ $CONT_DOCKER_SOCK_GROUP == "UNKNOWN" ]
then
   groupadd -g $CONT_DOCKER_SOCK_GROUP_GID docker_group
   CONT_DOCKER_SOCK_GROUP="docker_group"
fi

#See if there is an existing user with host user id:
CORRESPONDING_USER_NAME=`id -un $DOCKER_HOST_USER_UID`

if [ -z "$CORRESPONDING_USER_NAME" ]
then
    useradd -u $DOCKER_HOST_USER_UID $DOCKER_HOST_USER
    CORRESPONDING_USER_NAME=$DOCKER_HOST_USER
fi


usermod -aG $CONT_DOCKER_SOCK_GROUP $CORRESPONDING_USER_NAME
chown -R $CORRESPONDING_USER_NAME:$CORRESPONDING_USER_NAME /locker

CANWRITE=`sudo -u $CORRESPONDING_USER_NAME test -w /var/run/docker.sock && echo "YES"`

#See here: https://www.petefreitag.com/item/877.cfm for passing environment to sudo
if [ -z $CANWRITE ]
then
   sudo -E -u $CONT_DOCKER_SOCK_OWNER python /locker/app.py --local_or_remote $LOCAL_OR_REMOTE --run_as_user $RUNASUSER
else
   sudo -E -u $CORRESPONDING_USER_NAME python /locker/app.py --local_or_remote $LOCAL_OR_REMOTE --run_as_user $RUNASUSER
fi
