#!/bin/bash

## Replicate "realpath" function since
## MacOS does not have it by default
realpath () {
  # If the path is absolute, print it verbatim
  [[ $1 = /* ]] && echo "$1" && return

  # Otherwise, prepend the current working directory and remove any . or .. references
  oldpwd=$PWD
  cd "$(dirname "$1")"
  echo "$PWD/$(basename "$1")" | sed -E 's|/\./|/|g;s|/([^/]+)/\.\./|/|g'
  cd "$oldpwd"
}

## Get full path and parent directory
FULL_PATH=$(realpath $0)
DIR=$(dirname $FULL_PATH)
docker build --platform linux/amd64 -t rr:LockerSimpleImage -f "${DIR}/Dockerfile" "${DIR}/."


