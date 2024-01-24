#FROM ubuntu:20.04
FROM rocker/rstudio

ARG CONTAINER_USER=domino
USER root

# Set up Environment
ARG http_proxy=http://proxy-server.bms.com:8080
ARG https_proxy=http://proxy-server.bms.com:8080
ARG ftp_proxy=http://proxy-server.bms.com:8080
ARG no_proxy=.bms.com,169.254.169.254,localhost,.celgene.com

ARG DEBIAN_FRONTEND=noninteractive

# UPDATE and UPGRADE
RUN apt-get update -y && apt-get -y upgrade

#create a container User
RUN groupadd -g 12574 ${CONTAINER_USER} && useradd -u 12574 -g 12574 -m -N -s /bin/bash ${CONTAINER_USER} && mkdir -p /home/${CONTAINER_USER}/.ssh && sudo chown -R ${CONTAINER_USER}:${CONTAINER_USER} /home/${CONTAINER_USER} && sudo chmod 0700 /home/${CONTAINER_USER}/.ssh

RUN apt-get -y install build-essential cmake python3 python3-dev python3-pip wget sudo curl apt-utils git openssh-server nano
RUN apt-get -y install passwd supervisor sshfs nfs-common
RUN mkdir -p /var/log/supervisor && mkdir -p /etc/supervisor/conf.d && mkdir -p /var/run/sshd

ADD smount /usr/local/bin/smount
ADD sumount /usr/local/bin/sumount
ADD dmount /usr/local/bin/dmount
ADD dumount /usr/local/bin/dumount
RUN chmod 755 /usr/local/bin/smount && chmod 755 /usr/local/bin/sumount && chmod 755 /usr/local/bin/dmount && chmod 755 /usr/local/bin/dumount

# Give sudo to containre user
RUN echo "${CONTAINER_USER} ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

#Dirs where start scripts go
RUN mkdir -p /var/opt/workspaces

#RUN pip install jupyter jupyterlab==3.6.4 ipython ipykernel ipywidgets && ipython kernel install
#RUN jupyter nbextension enable --py widgetsnbextension

RUN pip install jupyter jupyterlab ipython ipykernel ipywidgets notebook==6.4.12 && ipython kernel install
#See here about next line: https://github.com/microsoft/azuredatastudio/issues/24436
RUN pip uninstall --yes traitlets && pip install traitlets==5.9.0
RUN jupyter nbextension enable --py widgetsnbextension

#Install VScode code-server: https://www.digitalocean.com/community/tutorials/how-to-set-up-the-code-server-cloud-ide-platform-on-ubuntu-20-04
#RUN mkdir /code-server && cd /code-server && wget https://github.com/cdr/code-server/releases/download/v3.7.3/code-server-3.7.3-linux-amd64.tar.gz && tar -xzvf code-server-3.7.3-linux-amd64.tar.gz && cp -r code-server-3.7.3-linux-amd64 /usr/lib/code-server && ln -s /usr/lib/code-server/bin/code-server /usr/bin/code-server
RUN mkdir /code-server && cd /code-server && wget https://github.com/cdr/code-server/releases/download/v4.8.2/code-server-4.8.2-linux-amd64.tar.gz && tar -xzvf code-server-4.8.2-linux-amd64.tar.gz && cp -r code-server-4.8.2-linux-amd64 /usr/lib/code-server && ln -s /usr/lib/code-server/bin/code-server /usr/bin/code-server
