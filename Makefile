# Clear $NAME env variable
undefine NAME

# Import environmental variables
-include .env
export

# Set default values if no .env file is provided
PORT ?= 5000
SERVER_ADMIN ?= andrewsmith_97@yahoo.com
NAME ?= locker_rr
VERSION ?= locker_devtest
REGISTRY ?= dockerreg.example.com:443
ECR_REGISTRY ?= 483421617021.dkr.ecr.us-east-1.amazonaws.com

# Image build-time arguments
LOCAL_TAG=${REGISTRY}/${NAME}:${VERSION}
REGISTRY_TAG=${ECR_REGISTRY}/${NAME}:${VERSION}
BUILD_ARGS=\
	--build-arg PORT=${PORT} \
	--build-arg SERVER_ADMIN=${SERVER_ADMIN} \
	-t ${LOCAL_TAG} \
	-t ${REGISTRY_TAG} \
	-t ${NAME}:${VERSION} \
	-f Dockerfile .

# Container run-time arguments
ifneq ($(wildcard .env),)
AWS_ADMIN_KEY_FILE="/$(shell basename ${AWS_ADMIN_KEY})"
RUN_ARGS=\
	--rm \
	-p ${PORT}:${PORT} \
	--env-file .env \
	-e AWS_ADMIN_KEY_UID=$(shell ls -n ${AWS_ADMIN_KEY} | awk '{print $$3}') \
	-e AWS_ADMIN_KEY_FILE=${AWS_ADMIN_KEY_FILE} \
	-v ${AWS_ADMIN_KEY}:${AWS_ADMIN_KEY_FILE} \
	-v ${CERT_FILE}:/etc/ssl/certs/domain.crt \
	-v ${KEY_FILE}:/etc/ssl/certs/domain.key
endif

# Build image
build: 
	docker build ${BUILD_ARGS}

# Build without cache
buildfresh: 
	docker build --no-cache ${BUILD_ARGS}

# Run locker services
run-locker-services:
	docker run \
		--name ${VERSION} \
		-d \
		${RUN_ARGS} \
		${LOCAL_TAG}

# Develop interactively
dev: build
	docker run \
		--name ${VERSION} \
		-d \
		${RUN_ARGS} \
		-v ${PWD}/.vscode:/.vscode \
		-v ${PWD}/locker:/locker \
		-v ${PWD}/locker_services:/locker_services \
		-v ${PWD}/modules:/modules \
		-v ${PWD}/config.yml:/config.yml \
		${LOCAL_TAG}

# Generate locker start script
OUTPUT_FILE := /tmp/start_script
locker-startscript: build
ifeq ($(wildcard .env),)
	docker run \
		--rm \
		${LOCAL_TAG} \
		/locker/gen_start_script maclinux > \
		${OUTPUT_FILE}
else
	docker run \
		--rm \
		--env-file=.env \
		${LOCAL_TAG} \
		/locker/gen_start_script maclinux > \
		${OUTPUT_FILE}
endif

# Run Locker
run-locker: \
	build \
	locker-startscript
	bash ${OUTPUT_FILE}
