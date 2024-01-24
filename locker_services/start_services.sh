#!/bin/bash

usermod -u $AWS_ADMIN_KEY_UID www-data

mkdir -p /locker_services/download
/locker/gen_start_script maclinux prod > /locker_services/download/start_locker.sh
/locker/gen_start_script win prod > /locker_services/download/start_locker_win.bat
chmod -R 0755 /locker_services/download
