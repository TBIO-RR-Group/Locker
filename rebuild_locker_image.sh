#!/bin/bash

LOCKER_VERSION=_devtest
export http_proxy=http://proxy-server.bms.com:8080
export https_proxy=http://proxy-server.bms.com:8080
docker rmi 483421617021.dkr.ecr.us-east-1.amazonaws.com/rr:locker${LOCKER_VERSION}
docker rmi docker.rdcloud.bms.com:443/rr:locker${LOCKER_VERSION}
#DATE=`date +"%y-%m-%d"`
DATE=`date +"%y-%m"`
docker build --platform linux/amd64 -t "locker:${DATE}${LOCKER_VERSION}" .
docker tag locker:${DATE}${LOCKER_VERSION} 483421617021.dkr.ecr.us-east-1.amazonaws.com/rr:locker${VERSION}
docker tag locker:${DATE}${LOCKER_VERSION} docker.rdcloud.bms.com:443/rr:locker${LOCKER_VERSION}
#Got from here: http://jimhoskins.com/2013/07/27/remove-untagged-docker-images.html
docker rmi $(docker images | grep "^<none>" | awk "{print $3}")
