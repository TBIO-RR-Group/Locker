#!/bin/bash

usermod -u $AWS_ADMIN_KEY_UID www-data

# Copy bind-mounted SSL certificates to a location readable by www-data
mkdir -p /ssl_certs
if [ -f /domain.crt ]; then
    cp /domain.crt /ssl_certs/domain.crt
    chmod 644 /ssl_certs/domain.crt
fi
if [ -f /domain.key ]; then
    cp /domain.key /ssl_certs/domain.key
    chown www-data:www-data /ssl_certs/domain.key
    chmod 600 /ssl_certs/domain.key
fi

mkdir -p /locker_services/download
/locker/gen_start_script maclinux prod > /locker_services/download/start_locker.sh
/locker/gen_start_script win prod > /locker_services/download/start_locker_win.bat
chmod -R 0755 /locker_services/download
