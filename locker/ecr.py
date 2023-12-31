#!/usr/bin/env python

import csv
import re
import json
import sys
import base64
import boto3
from botocore.config import Config
import requests
import requests_unixsocket
from Config import Config as LockerConfig

# Load locker configuration
config = LockerConfig("/config.yml")


ecr_registry_id = config.ecr_registry_id
aws_default_region = config.aws_region
rr_repo_name = config.ecr_repo_name
rr_repo_domain = config.ecr_domain

proxies = config.proxies

def getEcrClient(accessKey,secretKey,awsRegion=aws_default_region, setProxy=False):

    config = None
    if setProxy:
        config = Config(proxies=proxies)

    client = boto3.client(
        'ecr',
        aws_access_key_id=accessKey,
        aws_secret_access_key=secretKey,
        region_name=awsRegion,
        config=config
        )

    return client

#Note, to get the digest of the image from ECR (not the Manifest digest), you will need to use batch_get_image service:
#https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecr.html#ECR.Client.batch_get_image
def getEcrImages(ecr_client,repoName=rr_repo_name,registryId=ecr_registry_id):

    response_list_images = ecr_client.list_images(
        registryId=registryId,
        repositoryName=repoName
        )

    response_batch_get_image = ecr_client.batch_get_image(
        registryId=registryId,
        repositoryName=repoName,
        imageIds=response_list_images['imageIds']
        )

    for curImageInfo in response_batch_get_image['images']:
        curImageManifestObj = json.loads(curImageInfo['imageManifest'])
        curImageInfo['imageManifest'] = curImageManifestObj

    retVal = response_batch_get_image

    return retVal

#login to ecr so can do normal docker operations, e.g. 'docker images', 'docker ps', etc.
def ecrLogin(docker_client,ecr_client):

    token = ecr_client.get_authorization_token()
    username, password = base64.b64decode(token['authorizationData'][0]['authorizationToken']).decode().split(':')
    registry = re.sub(r'^https?://',r'',token['authorizationData'][0]['proxyEndpoint'])

    docker_client.login(username=username, password=password, registry=registry,reauth=True)

#    auth_creds = {'username': username, 'password': password, "email": "", 'registry': registry}
    auth_creds = {'username': username, 'password': password, "email": "", 'serveraddress': registry}

    return auth_creds

def ecrLoginDirect(ecr_client):

    token = ecr_client.get_authorization_token()
    username, password = base64.b64decode(token['authorizationData'][0]['authorizationToken']).decode().split(':')
    registry = re.sub(r'^https?://',r'',token['authorizationData'][0]['proxyEndpoint'])

    authInfo = {
        "username": username,
        "password": password,
        "email": "",
        "serveraddress": registry
        }

    print(json.dumps(authInfo))

    authInfoJsonStr = json.dumps(authInfo).encode('ascii')
    authInfo_b64 = base64.b64encode(authInfoJsonStr)

    with requests_unixsocket.monkeypatch():
#        r = requests.post('http+unix://%2Fvar%2Frun%2Fdocker.sock/auth',headers={ "X-Registry-Auth": authInfo_b64 })
        r = requests.post('http+unix://%2Fvar%2Frun%2Fdocker.sock/auth',json=authInfo)
#        assert r.status_code == 200
        print(r.json())

    return(authInfo)

def pullImageDirect(ecr_client,authInfo,imageNamePlusTag):

    authInfoJsonStr = json.dumps(authInfo).encode('ascii')
    authInfo_b64 = base64.b64encode(authInfoJsonStr)

    ecrRegistry = authInfo['serveraddress']

    with requests_unixsocket.monkeypatch():
        postUrl = 'http+unix://%2Fvar%2Frun%2Fdocker.sock/images/create?fromImage=' + ecrRegistry + '/' + imageNamePlusTag
        print(postUrl)
        r = requests.post(postUrl,
                          headers={ "X-Registry-Auth": authInfo_b64,
                                    "Content-Type": "application/json"})
#        r = requests.post('http+unix://%2Fvar%2Frun%2Fdocker.sock/auth',json=authInfo)
#        assert r.status_code == 200
        print(r.status_code)
        print(r.text)





def main ():

    print("main")
    ecr_client = getEcrClient()
    images = getEcrImages(ecr_client)

    print(images)

if __name__ == "__main__":
    main();
