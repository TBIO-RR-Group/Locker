#!/bin/sh

#Got from here: https://docs.docker.com/engine/install/ubuntu/

apt-get update

apt-get -y install \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg-agent \
    software-properties-common

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -

apt-key fingerprint 0EBFCD88

add-apt-repository \
   "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
   $(lsb_release -cs) \
   stable"

apt-get update

#apt-get -y install docker-ce docker-ce-cli containerd.io <- This installs all Docker, but we just need the cli to support sibling Docker containers
apt-get -y install docker-ce-cli
