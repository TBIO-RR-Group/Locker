#!/usr/bin/env python

import requests
import json
import re
from Config import Config

# Load locker configuration
config = Config("/config.yml")

configRegistryUrl = config.registryUrl
requests_timeout = 25 #25 seconds

#Get details for a single image
#getting the created date of the image requires an additional http request,
#so getting that is made optional, specify to get by setting getCreated=True
def getImageInfo(repo,registryUrl=configRegistryUrl,tag=None,getCreated=False):
    """
    Get details (image id and short id) for a single image from a Docker registry.
    If tag is None, a value of 'latest' will be used for it. registryUrl is the url
    of the registry server. Getting the created date of the image requires an additional http request,
    so getting that is made optional, specify to get by setting getCreated=True
    """

    if tag is None:
        tag = 'latest'
    url = registryUrl + '/v2/' + repo + '/manifests/' + tag
    headers = { 'Accept': 'application/vnd.docker.distribution.manifest.v2+json' }
    try:
        resp = requests.get(url, headers=headers, timeout=requests_timeout)
        respObj = resp.json()
    except Exception as e:
        raise Exception("Error fetching image manifest in DockerRegistry.getImageInfo: " + str(e))

    if 'errors' in respObj:
        raise Exception("Error fetching image manifest in DockerRegistry.getImageInfo: " + str(respObj))

    try:
        imageId = respObj['config']['digest']
        shortId = imageId[0:17]

        retVal = { 'id': imageId, 'short_id': shortId }

        if 'Docker-Content-Digest' in resp.headers:
            retVal['Docker-Content-Digest'] = resp.headers['Docker-Content-Digest']
    except Exception as e:
        raise Exception("Error parsing return results in DockerRegistyr.getImageInfo: " + str(e))

    if getCreated:
        try:
            resp = requests.get(url, timeout=requests_timeout)
        except Exception as e:
            raise Exception("Error fetching image created info in DockerRegistry.getImageInfo: " + str(e))
        respObj = resp.json()
        imageCreated = json.loads(respObj['history'][0]['v1Compatibility'])['created']
        retVal['created'] = imageCreated

    return(retVal)

#Get info about all images in the registry (or only the ones in repo if that is given)
def getImagesInfo(registryUrl=configRegistryUrl,repo=None,getCreated=False):
    """
    Get details (tags, image id and short id) for all images in a Docker registry (or only
    the ones in repo if a value for that is given). registryUrl is the url
    of the registry server. Getting the created date of the images requires an additional http request
    per image, so getting that is made optional, specify to get by setting getCreated=True
    """

    repos = []
    if repo is None:
        url = registryUrl + '/v2/_catalog'
        while True:
            try:
                resp = requests.get(url, timeout=requests_timeout)
                curRepos = resp.json()['repositories']
                repos.extend(curRepos)
                if resp.links and 'next' in resp.links and 'url' in resp.links['next']:
                    url = resp.links['next']['url']
                    if not url.startswith(registryUrl):
                        url = registryUrl + url
                else:
                    break
            except Exception as e:
                raise Exception("Error getting registry catalog in DockerRegistry.getImagesInfo: " + str(e))
    else:
        repos = [repo]

    images = []
    for curRepo in repos:
        url = registryUrl + '/v2/' + curRepo + '/tags/list'
        while True:
            try:
                resp = requests.get(url, timeout=requests_timeout)
                if 'tags' in resp.json():
                    curRepoTags = resp.json()['tags']
                    for curTag in curRepoTags:
                        curInfo = getImageInfo(curRepo,registryUrl=registryUrl,tag=curTag,getCreated=getCreated)
                        curInfo['tags'] = [curRepo + ':' + curTag]
                        curInfo['repo'] = curRepo
                        images.append(curInfo)
                if resp.links and 'next' in resp.links and 'url' in resp.links['next']:
                    url = resp.links['next']['url']
                    if not url.startswith(registryUrl):
                        url = registryUrl + url
                else:
                    break
            except Exception as e:
                raise Exception("Error getting tags list in DockerRegistry.getImagesInfo: " + str(e))

    return(images)

#Actually, this will just delete the specific tag. Even if you delete all tags for the repo,
#the repo will still show up in the registry (e.g. if you fetch /v2/_catalog). To fully remove
#a repo from a registry (after removing all tags using this function)
#see here: https://stackoverflow.com/questions/43666910/remove-docker-repository-on-remote-docker-registry
#and here also: https://azizunsal.github.io/blog/post/delete-images-from-private-docker-registry/
#However, the last step where you actually delete the repo is different for us since we're using
#S3 storage for the repos. In this case you need to delete from S3, e.g. for my-busybox repo:
#aws s3 rm s3://bmsrd-smitha26/docker/registry/v2/repositories/my-busybox --recursive
#Also see here for where I got the below code to delete the repo tag:
#https://stackoverflow.com/questions/54109362/docker-how-to-delete-image-from-a-private-registry
def deleteImage(repo,registryUrl=configRegistryUrl,tag=None):

    fullRepo = repo
    if tag is None:
        fullRepo = fullRepo + ':latest'
    else:
        fullRepo = fullRepo + ':' + tag

    imageInfo = getImageInfo(repo,registryUrl=registryUrl,tag=tag)

    if 'Docker-Content-Digest' in imageInfo:
        contentDigest = imageInfo['Docker-Content-Digest']
        print(f'DELETING image {fullRepo}: ' + contentDigest)
        requests.delete(f'{registryUrl}/v2/{repo}/manifests/{contentDigest}')

def deleteAllImages(registryUrl=configRegistryUrl):

    images = getImagesInfo()

    for curImageDict in images:
        if 'Docker-Content-Digest' in curImageDict and 'repo' in curImageDict:
            curContentDigest = curImageDict['Docker-Content-Digest']
            curRepo = curImageDict['repo']
            delUrl = f'{registryUrl}/v2/{curRepo}/manifests/{curContentDigest}'
            print('DELETE: ' + delUrl)
            requests.delete(delUrl)
            

def registryLogin(docker_client,registryUrl=configRegistryUrl,username=None,password=None):
    """
    Login to a Docker registry server; this can be required in order to pull images from it.
    Pass values for username and password if the registry server requires authentication.
    Must pass in a docker-py client.
    """

    registry = re.sub(r'^https?://',r'',registryUrl)

    resp = docker_client.login(username=username, password=password, registry=registry,reauth=True)

    auth_creds = {'username': username, 'password': password, "email": "", 'serveraddress': registry}

    return auth_creds


def main ():

    images = getImagesInfo()
    print(images)

if __name__ == "__main__":
    main();
