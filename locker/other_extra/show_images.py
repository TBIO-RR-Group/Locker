import DockerLocal
from Config import Config
from pprint import pprint

# Load locker configuration
config = Config("/config.yml")

client = DockerLocal.getDockerClient()
retImagesInfo = {}
DockerLocal.getRegistryImages(None,retImagesInfo)
il = DockerLocal.getImages(client, registryImagesInfo=retImagesInfo)

pprint(il)
