#!/usr/bin/env python

import csv
import io
import re
import json
import os
import tarfile
import tempfile
import sys
import base64
import boto3
import utils
import DockerRegistry
import docker
import ecr
import requests_unixsocket
from Config import Config

# Load locker configuration
config = Config("/config.yml")

#Returns True if docker is running (i.e. if 'docker info' returns something)
#otherwise return False
def checkDockerRunning():
    """
    Check if the Docker daemon is available/running by doing 'docker info'. Return True
    if Docker is running, and False otherwise.
    """

    is_running = True
    try:
        docker_client = getDockerClient()
        docker_client.info()
    except:
        is_running = False

    return is_running

def getDockerClient(lowLevel=False,timeout=600):
    """
    Get a docker-py client in order to interact with the local Docker daemon.
    If lowLevel is True, a low level docker-py client will be returned (APIClient),
    otherwise docker.from_env() client.
    """

    docker_client = None

    try:
        if lowLevel:
            docker_client = docker.APIClient(timeout=timeout)
        else:
            docker_client = docker.from_env(timeout=timeout)
    except Exception as e:
        raise Exception("Error getting Docker client from env, please make sure Docker is running and any env vars are set: " + e)

    return docker_client

def execContainerAction(contObj, curAction):

    if curAction == 'stop':
        contObj.stop()
    elif curAction == 'remove':
        contObj.remove()
    elif curAction == 'start':
        contObj.start()
    elif curAction == 'restart':
        contObj.restart()
    elif curAction == 'pause':
        contObj.pause()
    elif curAction == 'unpause':
        contObj.unpause()

def removeMyLockerContainer():

    lockerContainerName = os.getenv('LOCKER_CONTAINER_NAME')

    if not utils.empty(lockerContainerName):
        docker_client = getDockerClient()
        containers = docker_client.containers.list(filters={'name':lockerContainerName})
        for curContObj in containers:
            curContObj.remove(force=True)

def stopContainersHavingLabel(labelName, labelValue = None):

    docker_client = getDockerClient()
    containers = docker_client.containers.list()

    for curContObj in containers:
        if not labelName in curContObj.labels:
            continue
        if labelValue is not None:
            if curContObj.labels[labelName] != labelValue:
                continue
        curContObj.stop()
        curContObj.remove()


def getHostPorts(contObj,containerPorts):
    """
    Get the host port bindings for a running Docker container (docker-py contObj). I.e.
    containerPorts should contain ports inside the container as Dict keys, and this
    function will map them to their mapped to host ports (if any).
    """

    if contObj is None or containerPorts is None:
        raise Exception("Error in DockerLocal.getHostPorts: you must pass in both contObj and containerPorts params")

    returnPorts = {}
    if contObj.attrs is not None and 'NetworkSettings' in contObj.attrs and 'Ports' in contObj.attrs['NetworkSettings']:
        ports = contObj.attrs['NetworkSettings']['Ports']
        for curContPort in containerPorts:
            if curContPort + "/tcp" in ports and ports[curContPort + "/tcp"] is not None:
                hostPort = ports[curContPort + "/tcp"][0]['HostPort']
                returnPorts[curContPort] = hostPort
            elif curContPort + "/udp" in ports and ports[curContPort + "/udp"] is not None:
                hostPort = ports[curContPort + "/udp"][0]['HostPort']
                returnPorts[curContPort] = hostPort

    return returnPorts

#This does basically the same thing as previous/old copyIntoContainer (except doesn't support pre-tarred dirs),
#but in a different way. The reason I created this as follows. If you bind mount the host root (i.e. '/')
#dir then old copyIntoContainer threw "out of disk space" errors for some reason (seems to be a bug in Docker;
#see here: https://github.com/moby/moby/issues/38995). I.e. put_archive fails in this case.
#So this was written as a workaround to this bug (based on suggestions from that link).
#If src is a dir then dst should be the dir into which you want src copied.
#E.g.: src = /a/b/c, dst = /d/e/, then c will get copied into container at: /d/e/c
def copyIntoContainer2(contObj=None,srcContent=None, src=None, dst=None):

    #Strangely, if you directly copy a script into the container to be directly executed, executing it fails with 'text is busy' error
    #but if you copy it to a location in /tmp first, then do a 'cp' operation from there to dst, executing it works fine.
    #Not sure what the issue is directly copying, but doing this for all files to be safe.

    tmpRes = execRunWrap(contObj, 'mktemp',raiseExceptionIfExitCodeNonZero=True)
    tmpFile = tmpRes[1]

    if srcContent is not None:
        execCmd = f"sh -c 'cat - > {tmpFile}'"
        _, socket = contObj.exec_run(cmd=execCmd,stdin=True, socket=True)
        #Caller should have called encode() on srcContent if it was text
        socket._sock.sendall(srcContent)
        socket._sock.close()
        execRunWrap(contObj, f'cp {tmpFile} {dst}',raiseExceptionIfExitCodeNonZero=True)
    elif os.path.isfile(src):
        #file
        file = open(src,"r")
        fileContents = file.read()
        file.close()
        execCmd = f"sh -c 'cat - > {tmpFile}'"
        _, socket = contObj.exec_run(cmd=execCmd,stdin=True, socket=True)
        socket._sock.sendall(fileContents.encode())
        socket._sock.close()
        execRunWrap(contObj, f'cp {tmpFile} {dst}',raiseExceptionIfExitCodeNonZero=True)
    else:
        #assumed dir
        if not dst.endswith('/'):
            dst = dst + '/'
        srcFileName = os.path.basename(src)
        with tempfile.NamedTemporaryFile() as tmpTar_f:
            with tarfile.open(fileobj=tmpTar_f, mode='w|gz') as tar:
                tar.add(src, arcname=srcFileName)
            tmpTar_f.flush()
            execCmd = f"sh -c 'cat - > {tmpFile}'"
            _, socket = contObj.exec_run(cmd=execCmd,stdin=True, socket=True)
            tmpTar_f.seek(0)
            socket._sock.sendall(tmpTar_f.read())
            socket._sock.close()
            execRunWrap(contObj, f'cp {tmpFile} {dst}/{srcFileName}.tgz',raiseExceptionIfExitCodeNonZero=True)
        execRunWrap(contObj,f"sh -c 'cd {dst} && tar xfz {srcFileName}.tgz && rm -f {srcFileName}.tgz'",raiseExceptionIfExitCodeNonZero=True)

    execRunWrap(contObj, f"sh -c '[ ! -e {tmpFile} ] || rm -fr {tmpFile}'",raiseExceptionIfExitCodeNonZero=True)

#Got this function from here: https://stackoverflow.com/questions/46390309/how-to-copy-a-file-from-host-to-container-using-docker-py-docker-sdk
#Also see: https://stackoverflow.com/questions/40009458/how-to-copy-a-file-from-container-to-host-using-copy-in-docker-py
#Then slightly modified it (so you can give a name to the destination)
#Thus, if dst is just a dir make sure to end it with '/'
def copyIntoContainer(contObj,src,dst,srcAlreadyTarred=False):
    """
    Copy a file or dir from the host into a Docker container.
    contObj is the docker-py container object, src is the path
    to the file or dir on the host, and dst is the path to copy
    it to inside the container.
    """

    os.chdir(os.path.dirname(src))
    srcname = os.path.basename(src)

    if not srcAlreadyTarred:
        try:
            tar = tarfile.open(src + '.tar', mode='w')
            tar.add(srcname)
        except Exception as e:
            raise Exception("Error creating tarfile of src in DockerLocal.copyIntoContainer: " + str(e))
        finally:
            tar.close()

    try:
        data = open(src + '.tar', 'rb').read()
        dstdir = os.path.dirname(dst)
        dstname = os.path.basename(dst)
        contObj.put_archive(dstdir, data)
        if not utils.empty(dstname) and not srcname == dstname:
            cmd=f'mv {dstdir}/{srcname} {dstdir}/{dstname}'
            execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
        os.remove(src + '.tar')
    except Exception as e:
        raise Exception("Error copying from src to dst in DockerLocal.copyIntoContainer: " + str(e))


def copyFromContainer(contObj,src,dst,untarDst=True):
    """
    Copy a file or dir from a Docker container into the Docker host.
    contObj is the docker-py container object, src is the path
    to the file or dir in the container, and dst is the path to copy
    it to in the Docker host.

    Note that if dst ends in '/' it is assumed that dst is the directory
    into which you are copying src; otherwise it is assumed that you are
    renaming src with the basename of dst (so the copy will be into the
    dirname of dst)
    """

    srcname = os.path.basename(src)
    dstdir = os.path.dirname(dst)
    dstname = os.path.basename(dst)

    if os.path.exists(dst) and os.path.isdir(dst):
        dstf_path = os.path.join(dst,srcname) + '.tar'
        dstf = open(dstf_path, 'wb')
        extractTo = dst
    elif os.path.exists(dstdir) and os.path.isdir(dstdir):
        dstf_path = dst + '.tar'
        dstf = open(dstf_path, 'wb')
        extractTo = dstdir
    else:
        raise Exception(f'Error in DockerLocal.copyFromContainer: neither {dst} or {dstdir} directories exist in host')

    try:
        bits, stat = contObj.get_archive(src)
        for chunk in bits:
            dstf.write(chunk)
        dstf.close()
    except Exception as e:
        raise Exception(f'Error in DockerLocal.copyFromContainer: failed to copy container {src} to local tarfile: ' + str(e))

    if untarDst:
        try:
            dst_tar = tarfile.open(dstf_path)
            dst_tar.extractall(extractTo)
            dst_tar.close()
            os.remove(dstf_path)
            if not utils.empty(dstname) and not srcname == dstname:
                os.rename(os.path.join(dstdir,srcname),os.path.join(dstdir,dstname))
        except Exception as e:
            raise Exception(f'Error in DockerLocal.copyFromContainer: failed to untar tarfile copied from container {src}: ' + str(e))

#Run an image and set it up for use (mount /stash, home dir, etc.)
def runContainer(docker_client, image, ports=None, environment=None, entrypoint=None, cap_add=['SYS_ADMIN','DAC_READ_SEARCH','NET_ADMIN','NET_RAW'],devices=['/dev/fuse'],security_opt=['apparmor:unconfined'],
                 detach=True, tty=True, remove=False, labels=None,name=None, enableSiblingCont = False, enableGPU = False, hostRoot = None, hostUserUid = None, hostUserGid = None):
    """
    Start a Docker container. docker_client is a docker-py client.
    image is the Docker image to use to start the container. The
    rest of the arguments are the same as passed to docker-py's
    containers.run command, except with default values necessary
    to start our containers. The host machine's root dir is
    also bind mounted into the container at /host_root. The
    started container's docker-py container object is returned.
    """

    #bind mount Docker host's root path (i.e. '/') into the container
    if utils.empty(hostRoot):
        hostRoot = utils.root_path()
    volumes = { hostRoot : { "bind": "/host_root", "mode": "rw" } }

    if enableSiblingCont:
        volumes["/var/run/docker.sock"] = { "bind": "/var/run/docker.sock", "mode": "rw" }
#                os.path.splitdrive(os.path.abspath(os.path.join(os.sep,"var","run","docker.sock")))[1] = { "bind": "/var/run/docker.sock", "mode": "rw" } }

    if enableGPU:
        #See here for how to specify to use all GPUs: https://github.com/docker/docker-py/issues/2395
        device_requests = []
        device_requests = [docker.types.DeviceRequest(count=-1, capabilities=[['gpu']])]
    
        #To later stop/remove just do: contObj.stop() and contObj.remove()
        contObj = docker_client.containers.run(image=image, cap_add=cap_add,devices=devices,security_opt=security_opt,volumes=volumes,device_requests=device_requests,
                                               ports=ports,environment=environment,entrypoint=entrypoint,labels=labels,detach=detach,tty=tty,remove=remove,name=name)
    else:
        #To later stop/remove just do: contObj.stop() and contObj.remove()
        contObj = docker_client.containers.run(image=image, cap_add=cap_add,devices=devices,security_opt=security_opt,volumes=volumes,
                                               ports=ports,environment=environment,entrypoint=entrypoint,labels=labels,detach=detach,tty=tty,remove=remove,name=name)

    #Change the uid and gid of the containerUser user to match the host (if host values passed in via env vars DOCKER_HOST_USER_UID and DOCKER_HOST_USER_GID).
    #This is so the containerUser user has access to files and dirs under /host_root
    if hostUserUid is not None:
        checkUserCmd = f"/bin/bash -c \"id -u {hostUserUid} 1> /dev/null 2> /dev/null && echo 'Exists'\""
        (exitCode,cmdResStr) = execRunWrap(contObj,checkUserCmd,raiseExceptionIfExitCodeNonZero=False)
        cmdResStr = cmdResStr.strip()
        if cmdResStr != "Exists":
            cmd = f'usermod -u {hostUserUid} {config.containerUser}'
            execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
    if hostUserGid is not None:
        cmd = f'groupadd -g {hostUserGid} {config.containerUser}_host'
        execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=False) #it might fail if the group already exists, but that's okay
        cmd = f'usermod -aG {hostUserGid} {config.containerUser}'
        execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)

    return contObj

def setupApacheProxy(contObj, filesFolder, allowedUsers=[], contStartupScriptTxt=""):
    """
    For a started Docker container, setup the Apache SiteMinder
    proxy inside it (i.e. by copying in necessary conf, startup
    files and the SiteMinderApache.pm mod_perl module, etc.) contObj
    is the docker-py container object. filesFolder is a dir on the host
    where the various conf, startup files are stored. allowedUsers
    is a list of usernames that will be allowed access to the
    primary app and vscode (assuming they can SiteMinder
    authenticate).
    """

    try:
        #install mod_perl and other modules required for SiteMinderApache.pm, after doing apt-get update
        cmd="/bin/bash -c 'apt-get update -y'"
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd="/bin/bash -c 'apt-get -y install apache2 libapache2-mod-perl2 libcache-fastmmap-perl libjson-perl'"
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        
        copyIntoContainer2(contObj=contObj,src=os.path.join(filesFolder,'proxy_conf'),dst='/tmp/')
        cmd='chown -R root:root /tmp/proxy_conf'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd='chmod -R +r /tmp/proxy_conf'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        cmd='cp /tmp/proxy_conf/apache2.conf /etc/apache2/apache2.conf'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd='cp /tmp/proxy_conf/ports.conf /etc/apache2/ports.conf'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd='cp /tmp/proxy_conf/000-default.conf /etc/apache2/sites-enabled/000-default.conf'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd='mkdir -p /perl_mods'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd='cp /tmp/proxy_conf/startup.pl /perl_mods/startup.pl'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        cmd='cp /tmp/proxy_conf/SiteMinderApache.pm /perl_mods/SiteMinderApache.pm'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        cmd='chmod u+w /perl_mods/SiteMinderApache.pm'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        perlDataSectionContent = ""
        if len(allowedUsers) > 0:
            perlDataSectionContent = "\n".join(allowedUsers)
        perlDataSectionContent = perlDataSectionContent + "\n"
        perlDataSectionContent = perlDataSectionContent + "REDIRECT_URL\t" + config.redirect_url + "\n"
        perlDataSectionContent = perlDataSectionContent + "VALIDATE_URL\t" + config.validate_url + "\n"
        perlDataSectionContent = perlDataSectionContent + "SSO_SESSION_COOKIE_NAME\t" + config.SSO_SESSION_COOKIE_NAME + "\n"
        perlDataSectionContent = perlDataSectionContent + "REDIRECT_TARGET_ARGNAME\t" + config.REDIRECT_TARGET_ARGNAME + "\n"
        echoTxt = f'__DATA__\n{perlDataSectionContent}'
        cmd=f'/bin/sh -c \'echo "{echoTxt}" >> /perl_mods/SiteMinderApache.pm\''
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        #finally, start apache
        cmd="apachectl start"
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = False)
    except Exception as e:
        raise Exception("Error setting up Apache SiteMinder proxy in DockerLocal.setupApacheProxy: " + str(e))

    return(contStartupScriptTxt)

def contImageSelfContained(contObj):

    for curImageTag in contObj.image.tags:
        if 'SelfContained' in curImageTag:
            return True

    return False
        

def containerStartup(contObj,sshPubKey=None, sshPubKeyFile=None, sshPrivKey=None, sshPrivKeyFile=None, user=None,
                     localRepoPath=None, networkSshfsMounts=None,localSshfsMounts=None, contStartupScriptTxt=None):
    """
    Setup a started container to have the primary app (RStudio, Jupyter,
    Jupyterlab, VScode) and optionally (separately) VScode started and
    made available to users to access; also sshd is started --- this is
    expected to all be done via supervisord. Also copy in user's private/public
    SSH keys to enable passwordless access. If smountUserHomeDir is True, the
    user's home directory (on stash.pri.bms.com) will be mounted in containerUserHomedir
    using sshfs (via smount command using user's SSH private key). If localStashPath
    is not None, /stash will be symlinked to this path inside the container (it is
    assumed desired parts of stash had been rsynced there), otherwise /stash will be
    mounted using sshfs via smount (via user's SSH private key). contObj is the docker-py
    container object. The next four args are for public key and private key (can either pass
    the values of these in directly or file paths to them). user is the username
    of the user who will be the one accessing/using the container. Certain images have
    much of their software packages installed not in the image, but rather in a separate
    drive to be mounted; if localImagePath is not None then it is assumed it specifies a
    local path where the image content has been copied and that path will be symlinked to
    /opt (otherwise the EFS drive containing the offline image content will be mounted at
    /opt/tbio); in either case, a setup.sh script in the offline content mount will be
    run and its output added to the user's .bashrc inside the container. finalExecCmd
    is a final cmd to execute inside the container, expected to be supervisord usually
    (to start all the services such as sshd, RStudio, etc.)
    """

    if contStartupScriptTxt is None:
        contStartupScriptTxt = containerStartupScript()

    if user is None:
        user = utils.getUser()

    #Only mount network drive content, and EFS drive if on VPN or corporate network
    onVpnOrCorpNetwork = False
    if utils.checkOnVpnOrOrgOrCorporateNetwork(host=config.checkCorpNetworkVPNServer):
        onVpnOrCorpNetwork = True

    cmd="rm -fr /containerUserHomedirORIG"
    contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
    cmd=f"cp -r {config.containerUserHomedir} /containerUserHomedirORIG"; #if later do commit (anonymized), reset back to this before the commit
    contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

    if not contImageSelfContained(contObj):
        localImagePath = None
        if not utils.empty(config.imageDriveLocalPath):
            localImagePath = config.imageDriveLocalPath
            if not localImagePath.startswith('/host_root'):
                localImagePath = '/host_root' + localImagePath

        if localImagePath is not None:
            #link the local copy of offline image content to /opt
            cmd='mkdir -p /opt/tbio'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = False)
            #See here: https://askubuntu.com/questions/243380/how-to-create-a-read-only-link-to-a-directory
            cmd=f'mount --bind -r {localImagePath} /opt/tbio'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = False)
        else:
            if onVpnOrCorpNetwork and not utils.empty(config.imageDriveNetwork):
                #Mount shared drive which is an EFS:
                #sudo mount -t nfs4 -o ro,nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport fs-bd05875f.efs.us-east-1.amazonaws.com:/ /tmp/tbio
                #us-east-1 IP:172.25.135.163
                #Other region (us-west-1?) IP: 172.25.141.175
                cmd="mkdir -p /opt/tbio"
                contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = False)
                try:
                    mountCmd=f'mount -t nfs4 -o ro,nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport {config.imageDriveNetwork} /opt/tbio'
                    contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = mountCmd, asUser = None, notOnRestartFlag = False)
                except Exception as e:
                    print(f'Error mounting shared drive: {e}')

    try:
        #See here: https://stackoverflow.com/questions/3557037/appending-a-line-to-a-file-only-if-it-does-not-already-exist
        lineToAdd = 'test -f $BUILD_PREFIX/setup.sh && source $BUILD_PREFIX/setup.sh'
        echoCmdTxt = f'echo "{lineToAdd}" >> {config.containerUserHomedir}/.bashrc'
        theCmd = f'/bin/sh -c \'grep -qxF "{lineToAdd}" {config.containerUserHomedir}/.bashrc || ({echoCmdTxt})\''
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = theCmd, asUser = None, notOnRestartFlag = True)
    except Exception as e:
        print(f'Error adding setup script exec to .bashrc: {e}')


    if not utils.empty(sshPrivKey) or not utils.empty(sshPrivKeyFile):
        if not utils.empty(sshPrivKey):
            #See here: https://stackoverflow.com/questions/26843625/how-to-send-to-stdin-of-a-docker-py-container
            #And here: https://github.com/docker/docker-py/issues/2255
            execCmd = f"sh -c 'cat - > {config.containerUserHomedir}/.ssh/id_privkey_{user}'"
            _, socket = contObj.exec_run(cmd=execCmd,stdin=True, socket=True)
            socket._sock.sendall(sshPrivKey.encode())
            socket._sock.close()
        else:
            copyIntoContainer2(contObj=contObj,src=sshPrivKeyFile,dst=f'{config.containerUserHomedir}/.ssh/id_privkey_{user}')

        cmd=f'chmod 0600 {config.containerUserHomedir}/.ssh/id_privkey_{user}'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd=f'chown {config.containerUser}:{config.containerUser} {config.containerUserHomedir}/.ssh/id_privkey_{user}'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        sshConfig = f'host {config.githubUrl}\nHostName {config.githubUrl}\nIdentityFile {config.containerUserHomedir}/.ssh/id_privkey_{user}\nUser git\nStrictHostKeyChecking no\n'
        sshConfigTemp_f = tempfile.NamedTemporaryFile('w+t',delete=False)
        sshConfigTemp_f.write(sshConfig)
        sshConfigTemp_fname = sshConfigTemp_f.name
        sshConfigTemp_f.close()
        copyIntoContainer2(contObj=contObj,src=sshConfigTemp_fname,dst=f'{config.containerUserHomedir}/.ssh/config')
        os.remove(sshConfigTemp_fname)

        cmd=f'chmod 0644 {config.containerUserHomedir}/.ssh/config'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd=f'chown {config.containerUser}:{config.containerUser} {config.containerUserHomedir}/.ssh/config'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        if localRepoPath is not None:
            cmd='rm -fr /repos'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
            cmd=f'mkdir -p {localRepoPath}'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
            cmd=f'chown {config.containerUser}:{config.containerUser} {localRepoPath}'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
            cmd=f'ln -s {localRepoPath} /repos'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        if networkSshfsMounts is not None:
            for curSshfsMount in networkSshfsMounts:
                hostname = curSshfsMount[2]
                pathAtHostname = curSshfsMount[3]
                contMountPoint = curSshfsMount[4]
                userAtHostName = curSshfsMount[5]
                vpnOrCorpNetworkRequiredToMount = curSshfsMount[6]
                if not vpnOrCorpNetworkRequiredToMount or onVpnOrCorpNetwork:
                    cmd=f'mkdir -p {contMountPoint}'
                    contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = config.containerUser, notOnRestartFlag = False)
                    cmd=f'smount -i {config.containerUserHomedir}/.ssh/id_privkey_{user} -m {contMountPoint} -r {userAtHostName}@{hostname}:{pathAtHostname}'
                    contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = config.containerUser, notOnRestartFlag = False)

        if localSshfsMounts is not None:
            for curSshfsMount in localSshfsMounts:
                curLocalSshfsMount_local_path = curSshfsMount[0]
                curLocalSshfsMount_container_mount_point = curSshfsMount[1]
                #link the local copy to the container mount point
                cmd=f'rm -fr {curLocalSshfsMount_container_mount_point}'
                contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
                cmd=f'ln -s {curLocalSshfsMount_local_path} {curLocalSshfsMount_container_mount_point}'
                contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        sshfsHostMounts = []
        try:
            sshfsHostMounts = config.sshfsHostMounts
        except:
            pass
        cmd='printenv DOCKER_HOST_SERVER'
        dockerHostRes = execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
        dockerHost = dockerHostRes[1]
        cmd='printenv DOCKER_HOST_USER'
        dockerHostUserRes = execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
        dockerHostUser = dockerHostUserRes[1]
        if not utils.empty(dockerHost) and not dockerHost == 'localhost' and not dockerHost == '127.0.0.1' and sshfsHostMounts is not None and len(sshfsHostMounts) > 0:
            for curSshfsHostMount in sshfsHostMounts:
                hostPath = curSshfsHostMount[0]
                contPath = curSshfsHostMount[1]
                cmd=f'mkdir -p {contPath}'
                contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = False)
                cmd=f'smount -i {config.containerUserHomedir}/.ssh/id_privkey_{user} -m {contPath} -r {dockerHostUser}@{dockerHost}:{hostPath}'
                contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = config.containerUser, notOnRestartFlag = False)

    if not utils.empty(sshPubKey) or not utils.empty(sshPubKeyFile):
        if not utils.empty(sshPubKey):
            execCmd = f"sh -c 'cat - >> {config.containerUserHomedir}/.ssh/authorized_keys'"
            _, socket = contObj.exec_run(cmd=execCmd,stdin=True, socket=True)
            socket._sock.sendall(sshPubKey.encode())
            socket._sock.close()
        else:
            copyIntoContainer2(contObj=contObj,src=sshPubKeyFile,dst='/tmp/id_privkey.pub')
            cmd=f'chown {config.containerUser}:{config.containerUser} /tmp/id_privkey.pub'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
            cmd=f"sh -c 'cat /tmp/id_privkey.pub >> {config.containerUserHomedir}/.ssh/authorized_keys'"
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
            cmd='rm -fr /tmp/id_privkey.pub'
            contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        cmd=f'chown {config.containerUser}:{config.containerUser} {config.containerUserHomedir}/.ssh/authorized_keys'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)
        cmd=f'chmod 0644 {config.containerUserHomedir}/.ssh/authorized_keys'
        contStartupScriptTxt = containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = None, notOnRestartFlag = True)

        return(contStartupScriptTxt)

#Execute this to enable "sibling Docker containers"
def setupDockerCli(contObj,filesFolder):

    cmd="sh -c 'ls -la /var/run/docker.sock'"
    cmdRes = execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
    dockerSockGroup = cmdRes[1].strip().split()[3]
    addUserToGroup = dockerSockGroup
    #If the group of /var/run/docker.sock inside the container is a digit, then the group doesn't exist in the container yet, need to create it
    if dockerSockGroup.isdigit():
        cmd=f'addgroup --gid {dockerSockGroup} docker'
        execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
        addUserToGroup = 'docker'
    cmd=f'usermod -aG {addUserToGroup} {config.containerUser}'
    execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)

    #See here: https://docs.datadoghq.com/security_platform/default_rules/cis-docker-1.2.0-3.16/
    cmd=f'chmod 660 /var/run/docker.sock'
    execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)

    #Actually install docker (just cli) inside the container

    cmd="sh -c 'command -v docker'"
    cmdRes = execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=False)
    if cmdRes[0] != 0:
        copyIntoContainer2(contObj=contObj,src=os.path.join(filesFolder,'install_docker_ubuntu.sh'),dst='/tmp/install_docker_ubuntu.sh')
        cmd="/tmp/install_docker_ubuntu.sh"
        execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)

def getRegistryImages(config_file_path,retImagesInfo):
    """
    Get images info from private Docker registry or ECR (to
    later be combined with local images). Long operation to fetch these,
    so good to cache. Updates retImagesInfo with the registry images info.
    """

    if not utils.checkOnVpnOrOrgOrCorporateNetwork(host=config.checkCorpNetworkVPNServer):
        if 'ecr_images' in retImagesInfo:
            del retImagesInfo['ecr_images']
        if 'private_registry_images' in retImagesInfo:
            del retImagesInfo['private_registry_images']
        if 'ret_messages' in retImagesInfo:
            del retImagesInfo['ret_messages']
        return

    registryUrl = config.registryUrl
    repoName = config.repo_name
    ecrRegistryId = config.ecr_registry_id
    aws_region = config.aws_region
    ecrRepoName = config.ecr_repo_name
    ecrRepoDomain = config.ecr_domain

    ecr_client = None
    try:
        if not utils.empty(config_file_path):
            config_values = utils.readUserConfigValues(config_file_path=config_file_path)
            if config.useEcrFlag and 'aws_access_key_id' in config_values and 'aws_secret_access_key' in config_values:
                ecr_client = ecr.getEcrClient(accessKey=config_values['aws_access_key_id'],secretKey=config_values['aws_secret_access_key'],awsRegion=aws_region)
    except:
        pass

    retMessages = []

    if not ecr_client is None:
        ecrIl = { 'images': [] }
        try:
            ecrIl = ecr.getEcrImages(ecr_client,repoName=ecrRepoName,registryId=ecrRegistryId)
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Could not fetch images from ECR, repo {ecrRepoName}, registryId {ecrRegistryId} in DockerLocal.getImages',
                                               ": Details: " + str(e),"getImagesErr1")
            retMessages.append(fullMsg)
        retImagesInfo['ecr_images'] = ecrIl
    elif not utils.empty(registryUrl):
        regIl = []
        try:
            regIl = DockerRegistry.getImagesInfo(registryUrl=registryUrl,repo=repoName)
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Could not fetch registry images from { registryUrl } in DockerLocal.getImages (make sure connected to corporate network/VPN)',
                                               ": Details: " + str(e),"getImagesErr2")
            retMessages.append(fullMsg)
        retImagesInfo['private_registry_images'] = regIl

    retImagesInfo['ret_messages'] = retMessages;

    return

def checkLockerRunnableRegex(curCheckRegex,curImageName):

    lockerRunnableFlag = False
    
    if config.lockerRunnableImageRegexesIgnoreCase:
        if re.match(curCheckRegex,curImageName,re.IGNORECASE):
            lockerRunnableFlag = True
    else:
        if re.match(curCheckRegex,curImageName):
            lockerRunnableFlag = True

    return(lockerRunnableFlag)

def isLockerRunnableImage(imageNames=None):

    if imageNames is None:
        imageNames = []

    lockerRunnableFlag = False
    devtestFlag = False

    for curImageName in imageNames:
        for curCheckRegex in config.lockerRunnableImageRegexes:
            if checkLockerRunnableRegex(curCheckRegex,curImageName):
                lockerRunnableFlag = True
                break
        if not utils.empty(config.lockerRunnableImageDevtestRegex):
            if re.match(config.lockerRunnableImageDevtestRegex,curImageName):
                devtestFlag = True

    return(lockerRunnableFlag, devtestFlag)

def sortImages(lockerRunnableImageNames_pulled,lockerRunnableImageNames_other,otherImageNames_pulled,otherImageNames_other):

    orderedByRegex_pulled = []
    orderedByRegex_other = []    

    for curCheckRegex in config.lockerRunnableImageRegexes:
        orderedByRegex_pulled_cur = sorted([i for i in lockerRunnableImageNames_pulled if checkLockerRunnableRegex(curCheckRegex,i)],reverse=True)
        orderedByRegex_pulled.extend(orderedByRegex_pulled_cur)
        orderedByRegex_other_cur = sorted([i for i in lockerRunnableImageNames_other if checkLockerRunnableRegex(curCheckRegex,i)],reverse=True)
        orderedByRegex_other.extend(orderedByRegex_other_cur)

    otherImageNames_pulled.sort(reverse=True)
    otherImageNames_other.sort(reverse=True)
    defaultSortedImageNames = orderedByRegex_pulled + orderedByRegex_other + otherImageNames_pulled + otherImageNames_other

    return(defaultSortedImageNames)

def addPullingOfflineConfigInfoToImageDict(curImage=None,pullImageProgress=None,offlineImageConfigInfo=None):

    if curImage is None:
        return

    if pullImageProgress is not None and 'full_tags' in curImage and curImage['full_tags'] is not None and len(curImage['full_tags']) > 0:
        for curFullTag in curImage['full_tags']:
            if curFullTag in pullImageProgress:
                curImage['pulling_full_tag'] = curFullTag
    if offlineImageConfigInfo is not None and 'full_tags' in curImage and curImage['full_tags'] is not None and len(curImage['full_tags']) > 0 and curImage['full_tags'][0] in offlineImageConfigInfo:
        curImage['offline_config'] = 'Configuring'
    else:
        curImage['offline_config'] = 'Config'


def getImages(docker_client, registryImagesInfo=None, pullImageProgress=None, offlineImageConfigInfo=None):
    """
    Get the list of images from the local Docker daemon, and combine
    (based on common image digest) with images available at a private registry or
    AWS ECR. docker_client is a docker-py Docker client object. ecr_client is an AWS
    ECR client. registryUrl is the domain for the private private registry.
    ecrRepoDomain, ecrRepoName and ecrRegistryId
    are the AWS ECR params from which to fetch ECR images. Returns a tuple of 2
    elements: list of images (each list item is a hash with info about a specific
    image), plus a list of info messages (e.g. failure messages if can't connect to
    the private registry or ECR, i.e. if not connected to the corporate network or VPN)
    that can be, e.g. flashed by Flask.
    """

    ecrRepoDomain=ecr.rr_repo_domain
    registryUrl = config.registryUrl
    registry = re.sub(r'^https?://',r'',registryUrl)

    try:
        dockerIl = docker_client.images.list()
    except Exception as e:
        raise Exception("Error getting local Docker images in DockerLocal.getImages: " + str(e))

    seenImageIds = set()
    imagesDict = {}
    lockerRunnableImageNames_pulled = []
    lockerRunnableImageNames_other = []
    otherImageNames_pulled = []
    otherImageNames_other = []
    for curImage in dockerIl:
        tags = [re.sub(r'^.+/', r'', curTag) for curTag in curImage.tags]
        lockerRunnableFlag, devtestFlag = isLockerRunnableImage(imageNames=curImage.tags)
        fullImageInfoDict = { 'tags': tags, 'full_tags': curImage.tags, 'id': curImage.id, 'labels': curImage.labels, 'short_id': curImage.short_id, 'pulled': True, 'locker_runnable': lockerRunnableFlag, 'devtest': devtestFlag }
        addPullingOfflineConfigInfoToImageDict(curImage=fullImageInfoDict,pullImageProgress=pullImageProgress,offlineImageConfigInfo=offlineImageConfigInfo)
        for curFullTag in curImage.tags:
            imagesDict[curFullTag] = fullImageInfoDict
            if lockerRunnableFlag:
                lockerRunnableImageNames_pulled.append(curFullTag)
            else:
                otherImageNames_pulled.append(curFullTag)
        seenImageIds.add(curImage.id)

    if registryImagesInfo is not None and 'ecr_images' in registryImagesInfo:
        ecrIl = registryImagesInfo['ecr_images']
        ecrIl = ecrIl['images']
        for curImage in ecrIl:
            if curImage['imageManifest']['config']['digest'] in seenImageIds:
                continue
            if 'imageId' not in curImage or 'imageTag' not in curImage['imageId']:
                continue;
            seenImageIds.add(curImage['imageManifest']['config']['digest'])
            fullTags = [ecrRepoDomain + "/" + "rr:" + curImage['imageId']['imageTag']]
            lockerRunnableFlag, devtestFlag = isLockerRunnableImage(imageNames=fullTags)
            fullImageInfoDict = { 'tags': ["rr:" + curImage['imageId']['imageTag']],
                                  'full_tags': fullTags,
                                  'id': curImage['imageManifest']['config']['digest'],
                                  'short_id': curImage['imageManifest']['config']['digest'][0:17],
                                  'labels': [],
                                  'locker_runnable': lockerRunnableFlag,
                                  'devtest': devtestFlag,
                                  'pulled': False }
            addPullingOfflineConfigInfoToImageDict(curImage=fullImageInfoDict,pullImageProgress=pullImageProgress,offlineImageConfigInfo=offlineImageConfigInfo)            
            for curFullTag in fullTags:
                imagesDict[curFullTag] = fullImageInfoDict
                if lockerRunnableFlag:
                    lockerRunnableImageNames_other.append(curFullTag)
                else:
                    otherImageNames_other.append(curFullTag)                
    elif registryImagesInfo is not None and 'private_registry_images' in registryImagesInfo:
        regIl = registryImagesInfo['private_registry_images']
        for curImage in regIl:
            if curImage['id'] in seenImageIds:
                continue
            seenImageIds.add(curImage['id'])
            curImage['labels'] = []
            fullTags = [registry + "/" + curImageTag for curImageTag in curImage["tags"]]
            lockerRunnableFlag, devtestFlag = isLockerRunnableImage(imageNames=fullTags)
            curImage['locker_runnable'] = lockerRunnableFlag
            curImage['devtest'] = devtestFlag
            curImage['full_tags'] = fullTags
            curImage['pulled'] = False
            addPullingOfflineConfigInfoToImageDict(curImage=curImage,pullImageProgress=pullImageProgress,offlineImageConfigInfo=offlineImageConfigInfo)
            for curFullTag in fullTags:
                imagesDict[curFullTag] = curImage
                if lockerRunnableFlag:
                    lockerRunnableImageNames_other.append(curFullTag)
                else:
                    otherImageNames_other.append(curFullTag)                

    defaultSortedImageNames = sortImages(lockerRunnableImageNames_pulled,lockerRunnableImageNames_other,otherImageNames_pulled,otherImageNames_other)
    return imagesDict, defaultSortedImageNames

#Note that repo_w_tag has to be the full repo/tag spec, including ECR domain, e.g.:
#483421617021.dkr.ecr.us-east-1.amazonaws.com/rr:alpine
def pullFromEcr(docker_client,accessKey,secretKey,repo_w_tag,awsRegion=config.aws_region):
    """
    Pull an image from AWS ECR. docker_client is a docker-py client. repo_w_tag is the
    image to pull (including ECR domain --- e.g. 483421617021.dkr.ecr.us-east-1.amazonaws.com/rr:latest).
    accessKey and secretKey are the required AWS credentials (these must allow
    read/pull access from ECR). awsRegion is the AWS region to use.
    """

    try:
        ecr_client = ecr.getEcrClient(accessKey,secretKey,awsRegion)
        auth_creds = ecr.ecrLogin(docker_client,ecr_client)
        docker_client.images.pull(repo_w_tag, auth_config=auth_creds)
    except Exception as e:
        raise Exception("Error pulling image from ecr in DockerLocal.pullFromEcr: " + str(e))

def execRunWrap(cont_obj,cmd,user='',detach=False,stream=False,environment=None,raiseExceptionIfExitCodeNonZero=False,raiseExceptionIfResNonEmpty=False, workdir=None):

    (exitCode,res) = cont_obj.exec_run(cmd=cmd,detach=detach,stream=stream,environment=environment,user=user,workdir=workdir)

    cmdResStr = res
    try:
        # cmdResStr = res.decode('ascii').strip()
        cmdResStr = res.decode()
    except:
        pass

    if (raiseExceptionIfExitCodeNonZero and exitCode is not None and exitCode != 0) or (raiseExceptionIfResNonEmpty and not utils.empty(cmdResStr)):
        raise Exception("Error executing command: '" + cmd + "': exitCode = " + str(exitCode) + ", res = " + cmdResStr)
    else:
        return(exitCode,cmdResStr)

def containerStartupScript(startupScriptTxt = None, commandToAdd = None, asUser = None, notOnRestartFlag = False):

    if utils.empty(startupScriptTxt):
        startupScriptTxt = """#!/bin/bash

RESTART_FLAG="F";

while getopts r option
do
case "${option}"
in
r) RESTART_FLAG="T";;
esac
done"""
    elif not utils.empty(commandToAdd):
        if not utils.empty(asUser):
            commandToAdd = f'sudo -u {asUser} {commandToAdd}'
        if notOnRestartFlag:
            commandToAdd = f'if [[ "$RESTART_FLAG" == "F" ]]; then {commandToAdd}; fi'
        startupScriptTxt = startupScriptTxt + "\n" + commandToAdd

    return(startupScriptTxt)

##format of each record is: [<DESCRIPTIVE_NAME>,<ID>,<HOSTNAME>,<PATH_AT_HOSTNAME>,<CONTAINER_MOUNT_POINT>,<USER_AT_HOSTNAME>,<VPN_OR_CORPORATE_NETWORK_REQUIRED_TO_MOUNT>,<SHOW_MOUNT_OPTION_CHECKBOX>,<MOUNT_OPTION_DEFAULT>]
#<DESCRIPTIVE_NAME>: If empty or none, will default to <HOSTNAME>; label of checkbox where user can check to mount or not (e.g. 'mount Stash?')
#<ID>: Unique value (among all the sshfsMounts) identifying this record; will be used as the name of the checkbox in the start container form
#<HOSTNAME>: remote host from which you want to sshfs mount a directory
#<SHOW_MOUNT_OPTION_CHECKBOX>: Set to true value (e.g. 1) to show the "mount <DESCRIPTIVE_NAME>?" checkbox (in templates/start_container_form.html); setting to false value (e.g. 0) hides it. Whether hidden or shown, the checkbox will still be in the page and its value submitted with the form (see <MOUNT_OPTION_DEFAULT> where you can set it default checked or not).
#<MOUNT_OPTION_DEFAULT>: Set to empty string to not have the "mount <DESCRIPTIVE_NAME>?" checkbox (in templates/start_container_form.html) checked by default; 'checked' causes it to be checked by default.
#<PATH_AT_HOSTNAME>: The path to mount at <HOSTNAME>; note that any occurence of __REMOTE_USER__ will be replaced with <USER_AT_HOSTNAME> and any occurence of __DOCKER_HOST_USER__ will be replaced by the Docker host user and any occurence of __RUNASUSER__ will be replaced with runAsUser (user inside container)
#<CONTAINER_MOUNT_POINT>: The path to mount inside the container; note that any occurence of __REMOTE_USER__ will be replaced with <USER_AT_HOSTNAME> and any occurence of __DOCKER_HOST_USER__ will be replaced by the Docker host user and any occurence of __RUNASUSER__ will be replaced with runAsUser (user inside container)
#<USER_AT_HOSTNAME>: The remote user at the host where the drive to be mounted is located, __RUNASUSER__ will be replaced by runAsUser and __DOCKER_HOST_USER__ will be replaced by the Docker host machine username --- if empty value or None then default is just the Docker host machine username
def processSshfsMounts(sshfsMounts, hostUser, runAsUser):

    if sshfsMounts is None:
        return(None)

    processedSshfsMounts = []
    processedSshfsMountsDict = {}

    for curSshfsMountRef in sshfsMounts:
        curSshfsMount = curSshfsMountRef.copy()
        if utils.empty(curSshfsMount[0]):
            curSshfsMount[0] = curSshfsMount[2]
        if utils.empty(curSshfsMount[5]):
            curSshfsMount[5] = hostUser
        curSshfsMount[5] = curSshfsMount[5].replace("__DOCKER_HOST_USER__",hostUser)
        curSshfsMount[5] = curSshfsMount[5].replace("__RUNASUSER__",runAsUser)
        
        curSshfsMount[3] = curSshfsMount[3].replace("__REMOTE_USER__",curSshfsMount[5])
        curSshfsMount[3] = curSshfsMount[3].replace("__DOCKER_HOST_USER__",hostUser)
        curSshfsMount[3] = curSshfsMount[3].replace("__RUNASUSER__",runAsUser)
        curSshfsMount[3] = curSshfsMount[3].rstrip('/')
        curSshfsMount[4] = curSshfsMount[4].replace("__REMOTE_USER__",curSshfsMount[5])
        curSshfsMount[4] = curSshfsMount[4].replace("__DOCKER_HOST_USER__",hostUser)
        curSshfsMount[4] = curSshfsMount[4].replace("__RUNASUSER__",runAsUser)
        curSshfsMount[4] = curSshfsMount[4].rstrip('/')
        processedSshfsMounts.append(curSshfsMount)
        processedSshfsMountsDict[curSshfsMount[1]] = curSshfsMount

    return processedSshfsMounts, processedSshfsMountsDict

def main ():

    docker_client = getDockerClient()
    images, retMessages = getImages(docker_client,registryUrl=config.registryUrl)

    print(images)
    print(retMessages)

if __name__ == "__main__":
    main();
