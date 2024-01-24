#!/bin/bash

cd /tmp
curl -fsSL https://get.docker.com -o get-docker.sh
chmod +x get-docker.sh
./get-docker.sh
sudo usermod -aG docker $1
echo "Done!"
