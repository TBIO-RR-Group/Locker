FROM python:3.9.2-slim

# Build args (set values in .env)
ARG PORT
ARG SERVER_ADMIN

USER root

RUN apt-get update -y && \
    apt-get upgrade -y

RUN apt-get install -y \
      apt-transport-https \
      ca-certificates \
      curl \
      gnupg \
      lsb-release \
      sudo \
      procps \
      gettext

#See here for installing Docker on Debian: https://docs.docker.com/engine/install/debian/
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt-get update -y && \
    apt-get install -y \
      docker-ce-cli \
      inetutils-ping \
      libcache-fastmmap-perl \
      libjson-perl

RUN pip install Werkzeug==2.0.3 && \
    pip install flask==2.0.3 && \
    pip install requests && \
    pip install boto3 && \
    pip install docker && \
    pip install requests_unixsocket validators

RUN pip install scp
RUN pip install paramiko
RUN apt-get install gcc libldap2-dev libsasl2-dev -y
RUN pip install python-ldap
RUN pip install pyyaml

RUN apt-get install -y gnutls-bin ssl-cert apache2 libapache2-request-perl
RUN ln -s /etc/apache2/mods-available/ssl.load /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/ssl.conf /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/proxy.load /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/proxy.conf /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/socache_shmcb.load /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/headers.load /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/proxy_http.load /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/cgi.load /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/cgid.load /etc/apache2/mods-enabled/ && \
    ln -s /etc/apache2/mods-available/cgid.conf /etc/apache2/mods-enabled/

# Template substitution for ports.conf
ADD locker_services/ports.conf.template /etc/apache2/ports.conf.template
RUN envsubst < /etc/apache2/ports.conf.template > /etc/apache2/ports.conf

# Template substitution for 000-default.conf
RUN mv /etc/apache2/sites-available/000-default.conf /tmp/000-default.confORIG
ADD locker_services/000-default.conf.template /etc/apache2/sites-available/000-default.conf.template
RUN envsubst < /etc/apache2/sites-available/000-default.conf.template > /etc/apache2/sites-available/000-default.conf
RUN rm -fr /etc/apache2/sites-enabled/000-default.conf && ln -s /etc/apache2/sites-available/000-default.conf /etc/apache2/sites-enabled/

# Add modules to python path
ADD modules /modules
ENV PYTHONPATH=/modules

ADD locker /locker
ADD locker_services /locker_services
ADD config.yml /config.yml
CMD /locker_services/start_services.sh; apachectl -D FOREGROUND

