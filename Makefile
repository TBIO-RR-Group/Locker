# Import environmental variables
# if an .env file is provided
ifneq ($(wildcard .env),)
include .env
export
ENV_OPTION=--env-file=.env

# Set default values if .env file
# is not provided
else
PORT=5000
SERVER_ADMIN=andrewsmith_97@yahoo.com
NAME=locker_rr
VERSION=locker_devtest
REGISTRY=dockerreg.example.com:443
ECR_REGISTRY=483421617021.dkr.ecr.us-east-1.amazonaws.com
ENV_OPTION=
endif

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
# AWS_ADMIN_KEY, CERT_FILE, and KEY_FILE
# are required for secure file transfer
REQUIRED_FILES := $(and $(AWS_ADMIN_KEY), $(CERT_FILE), $(KEY_FILE))
ifneq ($(REQUIRED_FILES),)
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
ifeq ($(REQUIRED_FILES),)
	@echo "AWS_ADMIN_KEY, CERT_FILE, and KEY_FILE are required for secure file transfer"
	@exit 1
endif
	docker run \
		--name ${VERSION} \
		-d \
		${RUN_ARGS} \
		${LOCAL_TAG}


# Develop interactively
dev: build
ifeq ($(REQUIRED_FILES),)
	@echo "AWS_ADMIN_KEY, CERT_FILE, and KEY_FILE are required for secure file transfer"
	@exit 1
endif
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
	docker run \
		--rm \
		${ENV_OPTION} \
		${LOCAL_TAG} \
		/locker/gen_start_script maclinux > \
		${OUTPUT_FILE}

# Run Locker
run-locker: \
	locker-startscript
	bash ${OUTPUT_FILE}
