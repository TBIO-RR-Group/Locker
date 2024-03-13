from flask import Flask, render_template, request, redirect, url_for, flash, abort, session, jsonify, send_from_directory
from io import BytesIO
import json
import os
import posixpath
import re
import platform
import copy
import requests
import threading
import time
import datetime
import sys
sys.path.append("/modules")
import argparse
import tempfile
import shutil
import DockerLocal
import DockerRegistry
import utils
import ecr
from werkzeug.utils import secure_filename
from pathlib import Path
from Config import Config
import SiteMinder
import textwrap
#import logging

# Load locker configuration
config = Config("/config.yml")

if not DockerLocal.checkDockerRunning():
    print("Error: Docker is not running, please start Docker before using this app.")
    sys.exit()

tzEnv = os.getenv('TZ')
tzLoc = datetime.datetime.now().astimezone().tzinfo
lockerStartTime = str(datetime.datetime.now(tzLoc).strftime("%Y-%m-%d %H:%M"))
if not utils.empty(tzEnv):
    lockerStartTime = lockerStartTime + ' (' + tzEnv + ')'

LOCKER_VERSION = config.LOCKER_VERSION
configRegistryName = config.registryName
configRegistryUrl = config.registryUrl
ecr_domain = config.ecr_domain
ecr_rr_registry_id = config.ecr_registry_id
aws_region = config.aws_region
ecr_rr_repo_name = config.ecr_repo_name
useEcrFlag = config.useEcrFlag
proxyHandling = config.proxyHandling
configCheckProxyServer = config.checkCorpNetworkVPNServer
configProxies = config.proxies
locker_admins = config.locker_admins
if locker_admins is None:
    locker_admins = []
containerUserHomedir = config.containerUserHomedir
containerUser = config.containerUser
MAX_RECOMMENDED_RUNNING_CONTAINERS = config.MAX_RECOMMENDED_RUNNING_CONTAINERS
appsInIframe = config.appsInIframe

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('--local_or_remote', help="Whether to run the app locally ('l') allowing only localhost connections, or remotely ('r') allowing internet connections.", type=str)
parser.add_argument('--run_as_user', help="The username to run the app as", type=str)

cli_local_or_remote = None
cli_run_as_user = None
try:
    args = parser.parse_args()
    cli_local_or_remote = args.local_or_remote
    cli_run_as_user = args.run_as_user
except argparse.ArgumentError as arg_error:
    raise Exception("Error in command line arguments: " + arg_error)

if not utils.empty(cli_local_or_remote):
    cli_local_or_remote = cli_local_or_remote.strip()
if not utils.empty(cli_run_as_user):
    cli_run_as_user = cli_run_as_user.strip()

#The app can be run either locally (i.e. only accessible via localhost) or remotely
#(accesible over the internet) --- containers started (and the services running in them
#such as sshd, RStudio, Jupyter, VSCode, etc.) in each mode will similarly
#be accesible only locally or remotely over the internet. Containers started when running
#in remote mode will in addition have an Apache-based mod_perl SiteMinder proxy setup to
#only allow access to the user starting the container, for security (i.e. the user will
#need to SiteMinder authenticate and any SiteMinder cookies they present must validate as
#cookies belonging to them in order to access the started services in the container).
#When the app is run locally, the app and started containers can only be accessed on
#localhost and a regular "heartbeat" message from the browser will be tracked, with the app
#automatically shutting down after 3 minutes of not receiving a new heartbeat request
#(unless the user specifies not to do this by passing True for --no-timeout-shutdown).
#The automatic shutdown is for the case, e.g. where the user closes the app browser
#window without first shutting down the app). When the app is run remotely, no heartbeats
#will be tracked (and thus no automatic shutting down of the app). After starting the user
#will just be told the URL at which to access the app, and they can then manually access
#that URL in a browser. If the user didn't enter values for --local_or_remote and --run_as_user
#via cli args, then query the user for those values.
local_or_remote = 'l'
host = 'localhost'
while True:
    if utils.empty(cli_local_or_remote):
        local_or_remote = input("Do you want to access the app remotely or just locally [rL]?").strip()
    else:
        local_or_remote = cli_local_or_remote
    if local_or_remote != 'r' and local_or_remote != 'l':
        local_or_remote = 'l'
    break

if local_or_remote == 'r':
    host = utils.get_my_global_host_or_ip()
    if host is None:
        host = 'localhost'

runAsUser = utils.getUser()
if utils.empty(cli_run_as_user):
    enteredUser = input(f'User to run as [default:  \'{runAsUser}\']: ').strip()
else:
    enteredUser = cli_run_as_user
if not utils.empty(enteredUser):
    runAsUser = enteredUser

#If DOCKER_HOST_USABLE_PORTS set, then only those ports can be used on host,
#so cannot just let Docker pick random ports, need to use these
hostUsablePorts = None
hostUsablePorts_env = os.getenv('DOCKER_HOST_USABLE_PORTS')
if not utils.empty(hostUsablePorts_env):
    hostUsablePorts = hostUsablePorts_env.split(",")

hostUser = os.getenv('DOCKER_HOST_USER')
sshfsMounts = None
sshfsMountsDict = None
try:
    sshfsMounts = config.sshfsMounts
except Exception:
    pass
if sshfsMounts is not None:
    sshfsMounts, sshfsMountsDict = DockerLocal.processSshfsMounts(config.sshfsMounts, hostUser, runAsUser)
else:
    sshfsMounts = []
    sshfsMountsDict = {}
    
hostLockerPort = os.getenv('DOCKER_HOST_LOCKER_PORT')
if utils.empty(hostLockerPort):
    #should never get here, but guess 5000 in case
    hostLockerPort = 5000

mainAppContainerPort = config.mainAppContainerPort_local
vscodeContainerPort = config.vscodeContainerPort_local
if local_or_remote == 'r':
    #For remote use, these ports will be used to access the main app and vscode and will be
    #Apache proxy servers (which will SiteMinder authenticate and then proxy to the backend
    #actual services):
    mainAppContainerPort = config.mainAppContainerPort_remote
    vscodeContainerPort = config.vscodeContainerPort_remote

try:
    DockerLocal.stopContainersHavingLabel('__FOR_OFFLINE_IMAGE_ENABLE__', labelValue = 'True')
except Exception as e:
    print("Error stopping offline configuring containers: " + str(e))
    sys.exit()

print(f'>>>>>>>>>>\nAccess the app at: http://{host}:5000\n<<<<<<<<<<\n')

pullImageProgress = {}
offlineImageConfigInfo = {}
terminateOfflineImageConfigThreadSignals = {}
cachedImageInfo = {}

#At these request endpoints, don't try to stop offline enabling containers that have not started doing the actual offlining but weren't explicitly canceled
dontStopNonConfiguringOfflineEnableContsRequestEndpoints = { 'exec_offline_image', 'cancel_offline_enable', 'heartbeat', 'static', 'favicon', 'paths_ac', 'locker_status' }

app = Flask(__name__)
base_folder = app.root_path
files_folder = os.path.join(app.root_path,'files')
fonts_folder = os.path.join(app.root_path,'fonts')

#see here: https://www.askpython.com/python-modules/flask/flask-logging
#logging.basicConfig(level=logging.DEBUG, format=f'%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')

#configure proxy env vars based on config.proxyHandling
utils.unsetProxies()
if proxyHandling == 'check':
    if (utils.checkOnVpnOrOrgOrCorporateNetwork(host=configCheckProxyServer)):
        print("On VPN or corporate Network, so setting proxies.")
        utils.setProxies(proxiesHash=configProxies)
    else:
        print("Not on VPN or corporate Network, no proxies set.")
elif proxyHandling == 'set':
    print("Setting proxies.")
    utils.setProxies(proxiesHash=configProxies)
elif proxyHandling == 'unset':
    print("No proxies will be set.")

app.secret_key = 'h432hi5ohi3h5i5hi3o2hi'
app.config['last_hb'] = int(time.time())

app.config['FONTS_PATH']=fonts_folder
app.config['FILES_PATH']=files_folder
running_os = platform.system() #See here: https://stackoverflow.com/questions/1854/what-os-am-i-running-on

##See here: https://stackoverflow.com/questions/4028904/how-to-get-the-home-directory-in-python
##Also here: https://stackoverflow.com/questions/2668909/how-to-find-the-real-user-home-directory-using-python
##and here: https://stackoverflow.com/questions/54396141/how-to-persist-store-data-in-executable-compiled-with-pyinstaller
#user_homedir = str(Path.home())
if 'USER_HOMEDIR' in os.environ:
    env_homedir = os.environ['USER_HOMEDIR']
    user_homedir = '/host_root' + env_homedir
else:
    user_homedir = '/locker'

if not os.path.exists(os.path.join(user_homedir, config.userConfigDirName)):
    try:
        os.makedirs(os.path.join(user_homedir, config.userConfigDirName))
    except Exception as e:
        print(f'Error creating {config.userConfigDirName} directory to store app information: ' + str(e))
        sys.exit()
config_dir = os.path.join(user_homedir, config.userConfigDirName)
config_file_path = os.path.join(config_dir,'config.json')
print("Running on: " + running_os)
print("User homedir at: " + user_homedir)
print("Configuration file at: " + config_file_path)

validatedCookies = {}

#See here: https://pythonise.com/series/learning-flask/python-before-after-request
#Do SiteMinder authentication before all requests if running remotely. Returning
#None means allow the request to go forward and get processed, otherwise display/
#enact what is returned without processing the actual request.
@app.before_request
def before_request_func():

    req_ep = ''
    if not utils.empty(request.endpoint):
        req_ep = request.endpoint
    print('In before_request_func, endpoint: ' + req_ep)
    if req_ep not in dontStopNonConfiguringOfflineEnableContsRequestEndpoints:
        stopNonConfiguringOfflineEnableConts()

    if local_or_remote == 'r':
        runAsUsers = { runAsUser: True }
        for curU in locker_admins:
            runAsUsers[curU] = True
        return SiteMinder.smAuth(request, runAsUsers, validatedCookies)
    else:
        return None

def getAvailablePort(lockerUsedContPorts):

    for curPort in hostUsablePorts:
        if not curPort in lockerUsedContPorts:
            return(curPort)

    return(None)

def getUsedLockerContainerPorts():

    try:
        docker_client = DockerLocal.getDockerClient()
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error connecting to Docker',": Details: " + str(e),"getUserConfigErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    try:
        containers = docker_client.containers.list(all=True)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error fetching container list from Docker',": Details: " + str(e),"getUserConfigErr2")
        flash(fullMsg, "error")
        return render_template('error.html');

    lockerUsedPorts = set()

    viewConts = []
    curRunningContainerCt = 0
    for curContObj in containers:
        try:
            portsInfo = DockerLocal.getHostPorts(curContObj,{"22":"",mainAppContainerPort:"",vscodeContainerPort:""})
        except Exception as e:
            continue

        for contPort,hostPort in portsInfo.items():
            lockerUsedPorts.add(hostPort)

    return(lockerUsedPorts)

def getLockerContainers():

    try:
        docker_client = DockerLocal.getDockerClient()
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error connecting to Docker',": Details: " + str(e),"getUserConfigErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    try:
        containers = docker_client.containers.list(all=True)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error fetching container list from Docker',": Details: " + str(e),"getUserConfigErr2")
        flash(fullMsg, "error")
        return render_template('error.html');

    viewConts = []
    curRunningContainerCt = 0
    for curContObj in containers:
        if '__FOR_OFFLINE_IMAGE_ENABLE__' in curContObj.labels and curContObj.labels['__FOR_OFFLINE_IMAGE_ENABLE__'] == 'True':
            continue
        if not '__LOCKER_WORKSPACE_CONTAINER__' in curContObj.labels or not curContObj.labels['__LOCKER_WORKSPACE_CONTAINER__'] == 'True':
            continue

        try:
            main_app = curContObj.labels['MAIN_APP']
            portsInfo = DockerLocal.getHostPorts(curContObj,{"22":"",mainAppContainerPort:"",vscodeContainerPort:""})
        except Exception as e:
            continue

        #SSH port
        if "22" in portsInfo:
            curContObj.sshLink = '<a href="' + url_for('ssh_access') + f'?user={containerUser}&host={host}&port={portsInfo["22"]}">SSH</a>'

        if mainAppContainerPort in portsInfo:
            if appsInIframe:
                curContObj.mainAppLink = f'<a href="http://{host}:{hostLockerPort}/iniframe?port={portsInfo[mainAppContainerPort]}&title={curContObj.name}:{main_app}" title="{curContObj.name}:{main_app}">{main_app}</a>'
            else:
                curContObj.mainAppLink = f'<a href="http://{host}:{portsInfo[mainAppContainerPort]}" title="http://{host}:{portsInfo[mainAppContainerPort]}">{main_app}</a>'
        if vscodeContainerPort in portsInfo:
            if main_app == 'vscode':
                if appsInIframe:                
                    curContObj.mainAppLink = f'<a href="http://{host}:{hostLockerPort}/iniframe?port={portsInfo[vscodeContainerPort]}&title={curContObj.name}:VSCode" title="{curContObj.name}:VSCode">VSCode</a>'
                else:
                    curContObj.mainAppLink = f'<a href="http://{host}:{portsInfo[vscodeContainerPort]}" title="http://{host}:{portsInfo[vscodeContainerPort]}">VSCode</a>'
            else:
                if appsInIframe:                
                    curContObj.vscodeLink = f'<a href="http://{host}:{hostLockerPort}/iniframe?port={portsInfo[vscodeContainerPort]}&title={curContObj.name}:VSCode" title="{curContObj.name}:VSCode">VSCode</a>'
                else:
                    curContObj.vscodeLink = f'<a href="http://{host}:{portsInfo[vscodeContainerPort]}" title="http://{host}:{portsInfo[vscodeContainerPort]}">VSCode</a>'
        if curContObj.status == "running":
            curRunningContainerCt = curRunningContainerCt + 1
        viewConts.append(curContObj)

    return viewConts, curRunningContainerCt

#Default route just shows any started containers in a table, with links to access the various
#services (RStudio, Jupyter, VScode, SSH, etc.) in the containers.
@app.route('/')
def home():

    if not utils.empty(configRegistryUrl) and utils.checkOnVpnOrOrgOrCorporateNetwork(host=configCheckProxyServer):
        if cachedImageInfo is None or not ('ecr_images' in cachedImageInfo or 'private_registry_images' in cachedImageInfo):
            return render_template('server_starting.html');

    viewConts, curRunningContainerCt = getLockerContainers()
    return render_template('home.html', info={ 'containers': viewConts })

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'logo.jpg', mimetype='image/jpeg')

@app.route('/locker_status',methods=['GET','POST'])
def locker_status():
    retVal = f'Locker {LOCKER_VERSION} started {lockerStartTime} for user {runAsUser}'
    return(retVal)

#Displays an HTML page that gives instructions on how to SSH into
#a started container
@app.route('/ssh_access',methods=['GET','POST'])
def ssh_access():

    user = request.values.get('user')
    if utils.empty(user):
        user = containerUser
    host = request.values.get('host')
    port = request.values.get('port')
    if utils.empty(port):
        port = '22'

    ssh_info = { 'user': user,
                 'host': host,
                 'port': port }

    return render_template('ssh_access.html', ssh_info=ssh_info)

@app.route('/iniframe',methods=['GET','POST'])
def iniframe():

    port = request.values.get('port')
    title = request.values.get('title')
    if utils.empty(port):
        port = '80'
    if utils.empty(title):
        title = ''

    return f'<html><head><title>{title}</title></head><body><iframe title="iFrame port {port}" width="100%" height="100%" src="http://{host}:{port}"></iframe></body></html>'


#Used in the configuration page to support the user browsing the file system
#for their SSH private/public keys and other files/dirs (e.g. offlining of sshfs content)
@app.route('/paths_ac',methods=['GET','POST'])
def paths_ac():

    term = request.values.get('term')
    cb = request.values.get('callback')
    container = request.values.get('container')
    ftype = request.values.get('ftype')
    if (utils.empty(ftype)):
        ftype = 'BOTH'

    if not utils.empty(container):
        if utils.empty(term):
            term = '/' #assume container is always Linux so this will be root

        try:
            docker_client = DockerLocal.getDockerClient()
            contObj = docker_client.containers.get(container)
            cmd=f'sh -c "/tmp/paths_ac.py --term {term}"'
            cmdRes = DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
            cmdResJson = cmdRes[1]
            pathsInfo = json.loads(cmdResJson)            
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Error executing paths_ac.py for term "{term}" in paths_ac',": Details: " + str(e),"pathsAcErr0")
            flash(fullMsg, "error")
            return render_template('error.html');
    else:
        if utils.empty(term):
            term = '/host_root/' #term = utils.root_path()

        if not term.startswith('/host_root'):
            term = '/host_root' + term

        try:
            pathsInfo = utils.pathContents(term,ftype)
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Error fetching paths using utils.pathContents for term {term} in paths_ac',": Details: " + str(e),"pathsAcErr1")
            flash(fullMsg, "error")
            return render_template('error.html');

    curPaths = pathsInfo['paths']
    foundParentPath = pathsInfo['parent_path'].removeprefix('/host_root')
    retVals = [{'id': cur['path'].removeprefix('/host_root'), 'label': cur['path'].removeprefix('/host_root'), 'value': cur['path'].removeprefix('/host_root'), 'isfile': cur['isfile']} for cur in curPaths]

    retVals.insert(0,{'id': foundParentPath, 'label': foundParentPath, 'value': foundParentPath})

    retValsJson = json.dumps(retVals)

    if not utils.empty(cb):
        retValsJson = cb + "(" + retValsJson + ")"

    return(retValsJson)

#Page where the user configures/sets configuration options, i.e. SSH keys, etc.
@app.route('/dlconfigure',methods=['GET','POST'])
def dlconfigure():

    try:
        if os.path.exists(config_file_path):
            config = utils.readConfig(config_file_path,rebase=False) #don't rebase to /host_root because want to show user as it is on host (actual root /)
        else:
            config = {}
        utils.guessConfig(config,user_homedir_in=user_homedir)
    except Exception as e:
        fullMsg = utils.genShowHideMessage(f'Error getting current config in dlconfigure',": Details: " + str(e),"dlconfigErr1")
        flash(fullMsg, "error")
        return render_template('error.html');


    #Set new values if the configure.html form was submitted:
    if not utils.empty(request.values.get('set_config')) and request.values.get('set_config') == 'set':
        config['config_sshPrivKeyFile'] = utils.valOrEmpty(request.values.get('config_sshPrivKeyFile'))
        config['config_sshPubKeyFile'] = utils.valOrEmpty(request.values.get('config_sshPubKeyFile'))
        config['config_awsCredsFile'] = utils.valOrEmpty(request.values.get('config_awsCredsFile'))
        config['config_envVarFile'] = utils.valOrEmpty(request.values.get('config_envVarFile'))
        config['config_startupScript'] = utils.valOrEmpty(request.values.get('config_startupScript'))
        orig_config_offlineUsageStorage = ''
        if 'config_offlineUsageStorage' in config:
            orig_config_offlineUsageStorage = config['config_offlineUsageStorage']
        new_config_offlineUsageStorage = utils.valOrEmpty(request.values.get('config_offlineUsageStorage'))
        config['config_offlineUsageStorage'] = new_config_offlineUsageStorage
        orig_config_repoCloneLoc = ''
        if 'config_repoCloneLoc' in config:
            orig_config_repoCloneLoc = config['config_repoCloneLoc']
        new_config_repoCloneLoc = utils.valOrEmpty(request.values.get('config_repoCloneLoc'))
        config['config_repoCloneLoc'] = new_config_repoCloneLoc

    try:
        utils.writeConfig(config_file_path,config)
    except Exception as e:
        fullMsg = utils.genShowHideMessage(f'Error saving updated config in dlconfigure',": Details: " + str(e),"dlconfigErr2")
        flash(fullMsg, "error")
        return render_template('error.html');

    config['useEcrFlag'] = 1
    if not useEcrFlag:
        config['useEcrFlag'] = 0

    allOfflineImageTags = list(offlineImageConfigInfo.keys())
    for curImageTag in allOfflineImageTags:
        if 'status' in offlineImageConfigInfo[curImageTag] and offlineImageConfigInfo[curImageTag]['status'] == 'Configuring':
            curOffliningImage = curImageTag
            config['curOffliningImage'] = curImageTag
            break

    return render_template('configure.html', config=config)

#Shows available images (both locally and at remote registries) in a table, with links to
#remove the images, pull them, start a container from them.
@app.route('/images')
def images():

    try:
        docker_client = DockerLocal.getDockerClient()
        images, defaultSortedImageNames = DockerLocal.getImages(docker_client, registryImagesInfo=cachedImageInfo,pullImageProgress=pullImageProgress,offlineImageConfigInfo=offlineImageConfigInfo)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error getting images from Docker',": Details: " + str(e),"getUserConfigErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    if cachedImageInfo is not None and 'ret_messages' in cachedImageInfo:
        retMessages = cachedImageInfo['ret_messages']
    else:
        retMessages = []

    for curMessage in retMessages:
        flash(curMessage, "info")

    viewConts, curRunningContainerCt = getLockerContainers()
    return render_template('images.html', images_info={ 'images_info_dict': images, 'image_names_sorted': defaultSortedImageNames, 'running_container_ct': curRunningContainerCt, 'max_rec_cont': MAX_RECOMMENDED_RUNNING_CONTAINERS })

#Start off an image pull from a registry and redirect to the page where the pull progress can be
#followed by the user (i.e. same page as for the check_pull_progress route).
@app.route('/pull-image')
def pull_image():

    try:
        config_values = utils.readUserConfigValues(config_file_path=config_file_path)
    except Exception as e:
        fullMsg = utils.genShowHideMessage(f'Error reading config in pull_image',": Details: " + str(e),"pullErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    if config.useEcrFlag:
        if not ('aws_access_key_id' in config_values and 'aws_secret_access_key' in config_values):
            flash("You need to configure AWS credentials (aws_secret_access_key and aws_access_key_id", "error")
            return render_template('error.html');

    imageToPull = request.args.get('image')

    try:
        startPullThread(imageToPull,config_values)
    except Exception as e:
        fullMsg = utils.genShowHideMessage(f'Error starting thread to execute image pull',": Details: " + str(e),"pullErr2")
        flash(fullMsg, "error")
        return render_template('error.html');


    return render_template('pulling.html', image=imageToPull)

#Return current pull progress for an image. This is called as an Ajax call from the pull progress
#page referenced above and shown there.
@app.route('/get-pull-progress')
def get_pull_progress():

    image = request.values.get('image')
    returnVal = "No available status, presumably pull has completed (check images)."
    if image in pullImageProgress:
        pullProgress = pullImageProgress[image]
        returnVal = "";
        for key in sorted(pullProgress.keys()):
            returnVal = returnVal + key + ": " + pullProgress[key] + "\n"
    return returnVal

#Show current pull progress for an image being pulled (repeatedly calls
#get_pull_progress route via Ajax calls to get the current progress).
@app.route('/check-pull-progress')
def check_pull_progress():

    image = request.values.get('image')
    return render_template('pulling.html', image=image)

#See here: https://stackoverflow.com/questions/9513072/more-than-one-static-path-in-local-flask-instance
@app.route('/fonts/<path:filename>')
def fonts(filename):
    return send_from_directory(app.config['FONTS_PATH'], filename)

#Display a form the user can fill out to commit a container to a new image.
@app.route('/commit-container-form', methods=['POST','GET'])
def commit_container_form():

    cont_id = request.values.get('container')

    try:
        docker_client = DockerLocal.getDockerClient()
        contObj = docker_client.containers.get(cont_id)
    except Exception as e:
        fullMsg = utils.genShowHideMessage(f'Error getting container object in commit_container_form',": Details: " + str(e),"commitContFormErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    base_image_tag = contObj.image.tags[0]

    return render_template('commit_container_form.html', commit_info={'container': cont_id, 'base_image_tag': base_image_tag})


#This route will commit a container to a new image,
#after which it redirects to the images page to show the table of all
#images (including the new one from the commit).
@app.route('/commit-container', methods=['POST','GET'])
def commit_container():

    container = request.values.get('container')
    commit_image_name = request.values.get('commit_image_name')
    commit_message = request.values.get('commit_message')
    anonymize = request.values.get('anonymize')

    try:
        docker_client = DockerLocal.getDockerClient()
        contObj = docker_client.containers.get(container)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error getting container object in commit_container',": Details: " + str(e),"commitContErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    curUser = runAsUser
    base_image_tag = contObj.image.tags[0]
    base_image_tag_matches = re.search("^(.+)\:(.+?)$",base_image_tag)
    if base_image_tag_matches is not None:
        base_image_tag_repo = base_image_tag_matches[1]
        base_image_tag_tag = base_image_tag_matches[2]
    else:
        base_image_tag_repo = None
        base_image_tag_tag = base_image_tag
    
    homeDominoTarBytes = BytesIO()
    if not utils.empty(anonymize) and anonymize == 'on':
        try:
            bits, stat = contObj.get_archive(containerUserHomedir)
            for chunk in bits:
                homeDominoTarBytes.write(chunk)
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Error backing up user {containerUserHomedir} directory to tar bytes',": Details: " + str(e),"commitContErr2")
            flash(fullMsg, "error")
            return render_template('error.html');

    if utils.empty(commit_image_name):
        #See here: https://stackoverflow.com/questions/415511/how-to-get-the-current-time-in-python
        commit_image_name = time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime())

    if utils.empty(anonymize) or anonymize != 'on':
        #Note that the image has not been anonymized, so only user can reuse it and only locally (no push to registry allowed)
        commit_image_name = commit_image_name + "_NOTANON"
    else:
        commit_image_name = commit_image_name + "_ANON"

    if utils.empty(commit_message):
        commit_message = f'Image commited from container having base image "{base_image_tag}" by user "{curUser}"'

    zeroExitSshfsFusermounts = set()
    try:
        #See here: https://askubuntu.com/questions/1138940/unmount-sshfs-from-mount-point
        for curSshfsMount in sshfsMounts:
            curSshfsMount_id = curSshfsMount[1]
            curSshfsMount_mount_point = curSshfsMount[4]
            cmd=f'fusermount -u {curSshfsMount_mount_point}'
            (exitCodeCurSshfsMountFusermount,outputCurSshfsMountFusermount) = DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=False)
            if exitCodeCurSshfsMountFusermount == 0:
                zeroExitSshfsFusermounts.add(curSshfsMount_id)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error unmounting network drives in commit_container',": Details: " + str(e),"commitContErr3")
        flash(fullMsg, "info")

    if not utils.empty(anonymize) and anonymize == 'on':
        try:
            #Before commiting, need to remove sensitive info (private key, etc.) by resetting to base image's containerUserHomedir
            cmd=f'mv {containerUserHomedir} /tmp/'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
            cmd=f'cp -r /containerUserHomedirORIG {containerUserHomedir}'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
            cmd=f'chown -R {containerUser}:{containerUser} {containerUserHomedir}'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
            cmd=f'rm -fr /tmp/{containerUser}'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Error restoring original {containerUserHomedir} before commit in commit_container',": Details: " + str(e),"commitContErr4")
            flash(fullMsg, "error")
            return render_template('error.html');

    try:
        contObj.commit(repository=base_image_tag_repo,tag=base_image_tag_tag + '_' + curUser + '_' + commit_image_name, message=commit_message, author=curUser)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error commiting container to new image in commit_container',": Details: " + str(e),"commitContErr5")
        flash(fullMsg, "error")
        return render_template('error.html');

    if not utils.empty(anonymize) and anonymize == 'on':
        try:
            #Restore user's original containerUserHomedir dir
            cmd=f'rm -fr {containerUserHomedir}'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
            homeDominoTarBytes.seek(0)
            contObj.put_archive('/home/',homeDominoTarBytes)
            cmd=f'chown -R {containerUser}:{containerUser} {containerUserHomedir}'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Error restoring user {containerUserHomedir} after commit in commit_container',": Details: " + str(e),"commitContErr6")
            flash(fullMsg, "error")
            return render_template('error.html');

    try:
        for curSshfsMount_id in zeroExitSshfsFusermounts:
            curSshfsMount = sshfsMountsDict[curSshfsMount_id]
            curSshfsMount_hostname = curSshfsMount[2]
            curSshfsMount_hostname_path = curSshfsMount[3]
            curSshfsMount_mount_point = curSshfsMount[4]
            curSshfsMount_hostname_user = curSshfsMount[5]
            cmd=f'smount -i {containerUserHomedir}/.ssh/id_privkey_{curUser} -m {curSshfsMount_mount_point} -r {curSshfsMount_hostname_user}@{curSshfsMount_hostname}:{curSshfsMount_hostname_path}'
            curSshfsMountMountRes = DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error remounting network drives after commit in commit_container',": Details: " + str(e),"commitContErr7")
        flash(fullMsg, "info")

    return redirect(url_for('images'))

#Display a form the user can fill out to start a container for an image.
@app.route('/start-container-form', methods=['POST'])
def start_container_form():

    image_id = request.values.get('image_id')
    image_tag = request.values.get('image_tag')
    full_image_tag = request.values.get('full_image_tag')
    ssh_pub_key = request.values.get('ssh_pub_key')
    ssh_priv_key = request.values.get('ssh_priv_key')

    try:
        config_values = utils.readUserConfigValues(config_file_path=config_file_path)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error reading user config values in start_container_form',": Details: " + str(e),"start_container_formErr0")
        flash(fullMsg, "error")
        return render_template('error.html')

    locally_available_sshfs_mounts = set()
    if 'config_offlineUsageStorage' in config_values and not utils.empty(config_values['config_offlineUsageStorage']):
        offlineUsageStorageLoc = config_values['config_offlineUsageStorage']
        for curSshfsMount in sshfsMounts:
            containerMountPoint = curSshfsMount[4]
            curSshfsMountFullPath = os.path.join(offlineUsageStorageLoc,containerMountPoint.lstrip('/'))
            if os.path.isdir(curSshfsMountFullPath):
                locally_available_sshfs_mounts.add(curSshfsMount[1])

    return render_template('start_container_form.html', start_info={'id': image_id, 'full_tag': full_image_tag, 'tag': image_tag, 'ssh_pub_key': ssh_pub_key, 'ssh_priv_key': ssh_priv_key, 'registry_name': config.registryName, 'sshfs_mounts': sshfsMounts, 'locally_available_sshfs_mounts': locally_available_sshfs_mounts})


@app.route('/offline-image-config-start')
def offline_image_config_start():

    try:
        docker_client = DockerLocal.getDockerClient()
        images, defaultSortedImageNames = DockerLocal.getImages(docker_client, registryImagesInfo=cachedImageInfo)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error getting images from Docker',": Details: " + str(e),"offlineImageConfigStartErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    lockerRunnableImages = []
    for curImageTag, curImageInfoDict in images.items():
        if 'locker_runnable' in curImageInfoDict and curImageInfoDict['locker_runnable'] and 'pulled' in curImageInfoDict and curImageInfoDict['pulled']:
            lockerRunnableImages.append(curImageInfoDict)

    if not len(lockerRunnableImages) > 0:
        errMsg = 'Error: Offline configuration is done using a container started from one of the Locker-runnable Docker images. Please first go to the images page and pull one of those, then return here to do offline configuration.'
        flash(errMsg, "error")
        return render_template('error.html');

    return render_template('offline_image_config_start.html', config={ 'images': lockerRunnableImages, 'sshfs_mounts': sshfsMounts })

#Display a form the user can fill out to make offline available network drive content
@app.route('/offline-image-config', methods=['POST','GET'])
def offline_image_config():

    imagetagid = request.values.get('imagetagid')
    imageid = request.values.get('imageid')
    imagetag = request.values.get('imagetag')
    network_drive_id = request.values.get('network_drive')

    network_drive_name = None
    network_drive_mount_point = None
    networkSshfsMounts = []

    if not utils.empty(network_drive_id) and network_drive_id in sshfsMountsDict:
        sshfsMountInfo = sshfsMountsDict[network_drive_id]
        network_drive_mount_point = sshfsMountInfo[4]
        network_drive_name = sshfsMountInfo[0] + " ( " + network_drive_mount_point + " )"
        networkSshfsMounts.append(sshfsMountInfo)
    else:
        errMsg = f'Error: Bad value for network_drive {network_drive_id}'
        flash(errMsg, "error")
        return render_template('error.html');

    if not utils.empty(imagetagid):
        matches = re.search("^(.+)___(.+?)$",imagetagid)
        imagetag = matches[1]
        imageid = matches[2]

    if not utils.checkOnVpnOrOrgOrCorporateNetwork(host=configCheckProxyServer):
        errMsg = f'Error: You must be connected to the corporate network (directly or over VPN) in order to do offline enabling.'
        flash(errMsg, "error")
        return render_template('error.html');

    if imagetag in offlineImageConfigInfo:
        errMsg = f'Error: a container has already been started to enable offline usage of image \'{imagetag}\', please check the progress on that'
        flash(errMsg, "error")
        return render_template('error.html');

    try:
        config_values = utils.readUserConfigValues(config_file_path=config_file_path)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error reading user config values in offline_image_config',": Details: " + str(e),"offlineImageConfigErr0")
        flash(fullMsg, "error")
        return render_template('error.html');

    if not 'config_offlineUsageStorage' in config_values or utils.empty(config_values['config_offlineUsageStorage']):
        fullMsg = "Error: you must set a value for offline storage location, please set a value for this in Configure."
        flash(fullMsg, "error")
        return render_template('error.html');

    try:
        contObj = start_containerFunc(imageid, 'rstudio', '', '', networkSshfsMounts, None, '', '', other_labels = { '__FOR_OFFLINE_IMAGE_ENABLE__': 'True' })
    except Exception as e:
        fullMsg = utils.genShowHideMessage(f'Error starting container in offline_image_config',": Details: " + str(e),"offlineImageConfigErr1")
        flash(fullMsg, "error")
        return render_template('error.html')

    if contObj.status != 'running':
        fullMsg = utils.genShowHideMessage(f'Error starting container in offline_image_config',": Details: " + str(e) + ", Container Status: " + contObj.status,"offlineImageConfigErr2")
        flash(fullMsg, "error")
        return render_template('error.html')

    offlineImageConfigInfo[imagetag] = { 'cont': contObj }

    cmd="sh -c 'printenv BUILD_PREFIX'"
    cmdRes = DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
    buildPrefix = cmdRes[1]
    offlineImageDisabledTxt = ''
    if utils.empty(buildPrefix):
        offlineImageDisabledTxt = ' disabled'

    return render_template('offline_image_config_form.html', offline_info={'container': contObj.short_id, 'imagetag': imagetag, 'ol_disabled_txt': offlineImageDisabledTxt, 'network_drive_id': network_drive_id, 'network_drive_name': network_drive_name, 'network_drive_mount_point': network_drive_mount_point})

#Show current offline image configuring progress for an image (repeatedly calls
#get-offline-image-config-status route via Ajax calls to get the current progress).
@app.route('/check-offline-image-config-status')
def check_offline_image_config_status():
    imagetag = request.values.get('imagetag')
    return render_template('check_offline_image_config_status.html', args={'imagetag': imagetag})

#Return current offline enabling config status for an image.
#This is called as an Ajax call from the check offline image
#config status page referenced above and shown there.
@app.route('/get-offline-image-config-status')
def get_offline_image_config_status():
    imagetag = request.values.get('imagetag')
    returnVal = "No available status, presumably offline enabling of network drive content is complete."
    if imagetag in offlineImageConfigInfo:
        returnVal = "";
        curOfflineConfigInfo = offlineImageConfigInfo[imagetag]

        if 'errors' in curOfflineConfigInfo and len(curOfflineConfigInfo['errors']) > 0:
            allErrors = curOfflineConfigInfo['errors']
            for curErrTxt in allErrors:
                curMsgType = '<span style="background-color:red;">ERROR</span> '
                returnVal = returnVal + curMsgType + ": " + curErrTxt + "\n"
            return returnVal
        if 'rsync_status' in curOfflineConfigInfo:
            for curOffliningLoc in sorted(curOfflineConfigInfo['rsync_status'].keys()):
                curOffliningLocType = '<span style="background-color:powderblue;">COPYING</span> '
                returnVal = returnVal + curOffliningLocType + curOffliningLoc + ": " + curOfflineConfigInfo['rsync_status'][curOffliningLoc] + "\n"
    return returnVal

@app.route('/cancel-offline-enable')
def cancel_offline_enable():

    imagetag = request.values.get('imagetag')
    threadcancel = request.values.get('threadcancel')

    if imagetag in offlineImageConfigInfo:
        curOfflineConfigInfo = offlineImageConfigInfo[imagetag]
        if not utils.empty(threadcancel) and threadcancel == 'True':
            terminateOfflineImageConfigThreadSignals[imagetag] = True
        else:
            try:
                contObj = curOfflineConfigInfo['cont']
                contObj.stop()
                contObj.remove()
                del offlineImageConfigInfo[imagetag]
            except Exception as e:
                fullMsg = utils.genShowHideMessage('Error stopping offline enabling container in cancel_offline_enable',": Details: " + str(e),"cancelOfflineEnableErr0")
                flash(fullMsg, "error")
                return render_template('error.html');
    else:
        fullMsg = f'Error in cancel_offline_enable, no container was created or is running for image \'{imagetag}\' to enable offline usage, so there is nothing to cancel.'
        flash(fullMsg, "error")
        return render_template('error.html');

    return redirect(url_for('images'))

def stopContAndOptionallyAppendErr(imagetag, errMsg=None):

    if imagetag in offlineImageConfigInfo:
        curOfflineConfigInfo = offlineImageConfigInfo[imagetag]
        contObj = curOfflineConfigInfo['cont']
    if not utils.empty(errMsg):
        curOfflineConfigInfo['errors'].append(errMsg)
    try:
        contObj.stop()
        contObj.remove()
    except Exception as e:
        curOfflineConfigInfo['errors'].append("Error stopping offline enabling container in stopContAndOptionallyAppendErr: " + str(e))

    del offlineImageConfigInfo[imagetag]
    if imagetag in terminateOfflineImageConfigThreadSignals:
        del terminateOfflineImageConfigThreadSignals[imagetag]


#A separate thread is run to make an network drive content usable
#offline (so the user can still use the app for other things while
#that is happening). This function executes the code to enable offline
#usage of network drive content, in a separate thread
def startOfflineEnableThread(imagetag, offlineUsageStorageLoc, cacheLocsToCopy, network_drive_id):
    def enable_offline(imagetag, offlineUsageStorageLoc, cacheLocsToCopy, network_drive_id):

        if imagetag in offlineImageConfigInfo:
            curOfflineConfigInfo = offlineImageConfigInfo[imagetag]
            contObj = curOfflineConfigInfo['cont']
        else:
            fullMsg = f'Error in enable_offline thread, no container was created or is running for image \'{imagetag}\''
            curOfflineConfigInfo['errors'].append(fullMsg)
            return

        curOfflineConfigInfo['errors'] = []

        #Confirm rsync is installed (and install if not):
        cmdRes = DockerLocal.execRunWrap(contObj,"sh -c 'command -v rsync'")
        if cmdRes[0] != 0:
            DockerLocal.execRunWrap(contObj,"apt-get update -y",raiseExceptionIfExitCodeNonZero=False)
            cmdRes = DockerLocal.execRunWrap(contObj,"apt-get -y install rsync",raiseExceptionIfExitCodeNonZero=False)
            if cmdRes[0] != 0:
                stopContAndOptionallyAppendErr(imagetag,errMsg="Error installing rsync in container, exit code '" + str(cmdRes[0]) + "', res = " + cmdRes[1])
                return

        if not utils.empty(network_drive_id) and network_drive_id in sshfsMountsDict:
            sshfsMountInfo = sshfsMountsDict[network_drive_id]
            network_drive_hostname = sshfsMountInfo[2]
            network_drive_path_at_hostname = sshfsMountInfo[3]
            network_drive_mount_point = sshfsMountInfo[4]
        else:
            fullMsg = f'Error in enable_offline thread, no info for network drive \'{network_drive_id}\''
            curOfflineConfigInfo['errors'].append(fullMsg)
            return

        drive, offlinePath = os.path.splitdrive(offlineUsageStorageLoc)
        offlinePath = offlinePath.replace(os.sep, posixpath.sep)
        print("offlinePath = " + offlinePath)

        rsyncCmds = {}
        curUser = runAsUser

        rsyncSetGroup = containerUser
        if os.getenv('RESET_USER_UGIDS') == 'True':
            set_hostUserGid = os.getenv('DOCKER_HOST_USER_GID')
            rsyncSetGroupCmdRes = DockerLocal.execRunWrap(contObj,f'getent group {set_hostUserGid} | cut -d: -f1')
            if cmdRes[0] == 0 and not utils.empty(cmdRes[1]):
                rsyncSetGroup = cmdRes[1]

        if cacheLocsToCopy is not None and len(cacheLocsToCopy) > 0:
            for cacheloc in cacheLocsToCopy:
                if utils.empty(cacheloc):
                    continue
                cachelocAtHost = cacheloc
                cachelocAtHost = re.sub("^" + network_drive_mount_point,network_drive_path_at_hostname,cachelocAtHost)
                cmdRes = DockerLocal.execRunWrap(contObj,f'mkdir -p {offlinePath}{cacheloc}',user=containerUser)
                if cmdRes[0] != 0:                    
                    stopContAndOptionallyAppendErr(imagetag,errMsg="Error doing mkdir -p for network drive cache location in container, exit code '" + str(cmdRes[0]) + "', res = " + cmdRes[1])
                    return
                toLocCache = str(Path(f'{offlinePath}{cacheloc}').parent)
                print('toLocCache = ' + toLocCache)
                rsyncCmdCache = f'rsync -e \'ssh -i {containerUserHomedir}/.ssh/id_privkey_{curUser} -o StrictHostKeyChecking=no\' --info=progress2 -haz --super --chown={containerUser}:{rsyncSetGroup} {curUser}@{network_drive_hostname}:{cachelocAtHost} {toLocCache}'

                print('rsyncCmdCache: ' + rsyncCmdCache)
                rsyncCmds[cacheloc] = rsyncCmdCache

        allOutStreamLocs = []
        allOutStreams = []

        for curRsyncCmdLoc in rsyncCmds:
            curRsyncCmd = rsyncCmds[curRsyncCmdLoc]
            print("curRsyncCmd = " + curRsyncCmd)
            cmd=f'sh -c "{curRsyncCmd}"'
            ec,outStream = DockerLocal.execRunWrap(contObj,cmd,stream=True,raiseExceptionIfExitCodeNonZero=True)
            allOutStreamLocs.append(curRsyncCmdLoc)
            allOutStreams.append(outStream)

        numOutStreams = len(allOutStreams)
        curStreamIdx = 0
        completedOutStreams = {}
        curOfflineConfigInfo['rsync_status'] = {}
        while True:
            if imagetag in terminateOfflineImageConfigThreadSignals and terminateOfflineImageConfigThreadSignals[imagetag]:
                print("CANCEL OFFLINE ENABLE: " + str(terminateOfflineImageConfigThreadSignals)) ### COMMENT OUT
                break
            if curStreamIdx not in completedOutStreams:
                try:
                    curOutStream = allOutStreams[curStreamIdx]
                    curOutStreamLoc = allOutStreamLocs[curStreamIdx]
                    curLinesAll = next(curOutStream).decode('ascii').strip()
                    curLines = curLinesAll.splitlines()
                    for curLine in curLines:
                        curLine = curLine.strip()
                        parts = curLine.split()
                        if len(parts) != 6:
                            continue
                        pattern = re.compile("\(xfr\#\d+,\s+(to|ir)\-chk\=\d+\/\d+\)$")
                        if pattern.search(curLine):
                            curOfflineConfigInfo['rsync_status'][curOutStreamLoc] = curLine
                            print(curOutStreamLoc + ": " + curLine) ### COMMENT OUT
                except Exception as e:
                    print("GOT EXCEPTION WHILE DOING RSYNC: " + str(e)) ### COMMENT OUT
                    curOfflineConfigInfo['rsync_status'][allOutStreamLocs[curStreamIdx]] = "COPYING COMPLETE"
                    completedOutStreams[curStreamIdx] = True

            numCompletedOutStreams = len(completedOutStreams)
            if (numCompletedOutStreams >= numOutStreams):
                break
            curStreamIdx = curStreamIdx + 1
            if curStreamIdx >= numOutStreams:
                curStreamIdx = 0

        stopContAndOptionallyAppendErr(imagetag)

        print(f'enable_offline thread for image \'{imagetag}\' ended')

    thread = threading.Thread(target=enable_offline, daemon=True, kwargs={ 'imagetag': imagetag, 'offlineUsageStorageLoc': offlineUsageStorageLoc,
                                                                           'cacheLocsToCopy': cacheLocsToCopy, 'network_drive_id': network_drive_id })
    thread.start()

#Make network drive content available offline
@app.route('/exec-offline-image', methods=['POST','GET'])
def exec_offline_image():

    cont_id = request.values.get('container')
    imagetag = request.values.get('imagetag')
    cacheloc1 = request.values.get('cacheloc1')
    cacheloc2 = request.values.get('cacheloc2')
    cacheloc3 = request.values.get('cacheloc3')
    network_drive_id = request.values.get('network_drive')

    try:
        config_values = utils.readUserConfigValues(config_file_path=config_file_path)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error reading user config values in exec_offline_image',": Details: " + str(e),"execOfflineImageErr0")
        flash(fullMsg, "error")
        return render_template('error.html')

    if not 'config_offlineUsageStorage' in config_values or utils.empty(config_values['config_offlineUsageStorage']):
        fullMsg = "Error in exec_offline_image: you must set a value for offline storage location, please set a value for this in Configure."
        flash(fullMsg, "error")
        return render_template('error.html')
    else:
        offlineUsageStorageLoc = config_values['config_offlineUsageStorage']

    if imagetag in offlineImageConfigInfo:
        contObj = offlineImageConfigInfo[imagetag]['cont']
    else:
        fullMsg = f'Error in exec_offline_image, no container was created or is running for image \'{imagetag}\''
        flash(fullMsg, "error")
        return render_template('error.html')

    cacheLocsToCopy = []
    if not utils.empty(cacheloc1):
        cacheLocsToCopy.append(cacheloc1)
    if not utils.empty(cacheloc2):
        cacheLocsToCopy.append(cacheloc2)
    if not utils.empty(cacheloc3):
        cacheLocsToCopy.append(cacheloc3)

    if len(cacheLocsToCopy) > 0:
        startOfflineEnableThread(imagetag, offlineUsageStorageLoc, cacheLocsToCopy, network_drive_id)
        print("Setting to 'Configuring' status for image: " + imagetag)
        offlineImageConfigInfo[imagetag]['status'] = 'Configuring'
        return render_template('check_offline_image_config_status.html', args={'imagetag': imagetag})
    else:
        contObj.stop()
        contObj.remove()
        del offlineImageConfigInfo[imagetag]
        mesg = "No offline configuring is running now."
        return render_template('message.html', args={'message': mesg})

#If the user began the offline config process but then didn't fill out the
#form and click 'Start', there will be leftover unused containers running,
#and this function will stop those. Call this before each handler to get
#rid of them
def stopNonConfiguringOfflineEnableConts():

    print('in stopNonConfiguringOfflineEnableConts')

    allOfflineImageTags = list(offlineImageConfigInfo.keys())

    for curImageTag in allOfflineImageTags:
        if 'status' in offlineImageConfigInfo[curImageTag] and offlineImageConfigInfo[curImageTag]['status'] == 'Configuring':
            continue
        else:
            curImageInfo = offlineImageConfigInfo[curImageTag]
            if 'cont' in curImageInfo:
                contObj = curImageInfo['cont']
                contObj.stop()
                contObj.remove()
            del offlineImageConfigInfo[curImageTag]
            print("Deleted for image: " + curImageTag)

# Write a function to dynamically generate supervisord scripts
# depending on the requested services.
def genSupervisordConf(services, supervisord_conf_file_path):
    """
    Generate a supervisord conf file for the services requested.
    """
    # Import "global" config variables
    try:
        config = Config("/config.yml")
    except Exception as e:
        raise Exception('Error getting config in genSupervisordConf: ' + str(e))
    
    # Define environment variable names and values
    WORKING_DIR_VAR=config.env_vars["LOCKER_WORKING_DIR"]
    PROJECT_OWNER_VAR=config.env_vars["LOCKER_PROJECT_OWNER"]
    STARTING_USERNAME_VAR=config.env_vars["LOCKER_STARTING_USERNAME"]

    # Base supervisord config with sshd
    base = f"""
    [supervisord]
    nodaemon=true
    environment=HOME="%(ENV_HOME)s",{WORKING_DIR_VAR}="%(ENV_{WORKING_DIR_VAR})s",{PROJECT_OWNER_VAR}="%(ENV_{PROJECT_OWNER_VAR})s",{STARTING_USERNAME_VAR}="%(ENV_{STARTING_USERNAME_VAR})s"
    logfile=/var/log/supervisor/supervisord.log

    [program:sshd]
    command=/usr/sbin/sshd -D
    """

    # Jupyter
    jupyter = f"""
    [program:jupyter]
    user=%(ENV_USER)s
    command=/bin/bash -c 'test -f $BUILD_PREFIX/setup.sh && source $BUILD_PREFIX/setup.sh; /var/opt/workspaces/custom/start_scripts/start_jupyter'
    stdout_logfile=/var/log/supervisor/%(program_name)s.log
    stderr_logfile=/var/log/supervisor/%(program_name)s.log
    startsecs=0
    autorestart=false
    """

    # JupyterLab
    jupyterlab = f"""
    [program:jupyterlab]
    user=%(ENV_USER)s
    command=/bin/bash -c 'test -f $BUILD_PREFIX/setup.sh && source $BUILD_PREFIX/setup.sh; /var/opt/workspaces/custom/start_scripts/start_jupyterlab'
    stdout_logfile=/var/log/supervisor/%(program_name)s.log
    stderr_logfile=/var/log/supervisor/%(program_name)s.log
    startsecs=0
    autorestart=false
    """

    # RStudio
    rstudio = f"""
    [program:rserver]
    user=%(ENV_USER)s
    command=/bin/bash -c 'test -f $BUILD_PREFIX/setup.sh && source $BUILD_PREFIX/setup.sh; /var/opt/workspaces/custom/start_scripts/start_rstudio 8888'
    stdout_logfile=/var/log/supervisor/%(program_name)s.log
    stderr_logfile=/var/log/supervisor/%(program_name)s.log
    startsecs=0
    autorestart=false
    """

    # VSCode
    vscode = f"""
    [program:vscode]
    user=%(ENV_USER)s
    command=/bin/bash -c 'test -f $BUILD_PREFIX/setup.sh && source $BUILD_PREFIX/setup.sh; /var/opt/workspaces/custom/start_scripts/start_vscode 8887'
    stdout_logfile=/var/log/supervisor/%(program_name)s.log
    stderr_logfile=/var/log/supervisor/%(program_name)s.log
    startsecs=0
    autorestart=false
    """

    # Add services to the base config
    if "jupyter" in services:
        base += jupyter
    if "jupyterlab" in services:
        base += jupyterlab
    if "rstudio" in services:
        base += rstudio
    if "vscode" or "_vscode" in services:
        base += vscode

    # Write the config to a file
    try:
        with open(supervisord_conf_file_path, "w") as file:
            base = textwrap.dedent(base)
            file.write(base)
    except Exception as e:
        raise Exception('Error writing supervisord conf file in genSupervisordConf: ' + str(e))


def start_containerFunc(image, main_app, container_name, vscode, networkSshfsMounts, localSshfsMounts, sibling_cont, enable_gpu, other_labels = None, envVarFile = "", startupScript = "", repo_uri = None, repo_release = None):
    try:
        config = utils.readConfig(config_file_path)
        config_values = utils.readUserConfigValues(config_file_path=config_file_path)
    except Exception as e:
        raise Exception('Error getting config in start_containerFunc: ' + str(e))

    # Import "global" config variables
    try:
        lockerConfig = Config("/config.yml")
    except Exception as e:
        raise Exception('Error getting lockerConfig in start_containerFunc: ' + str(e))

    sshPrivKeyFile = None
    sshPubKeyFile = None
    repoCloneLoc = None
    offlineUsageStorageLoc = None

    if 'config_sshPrivKeyFile' in config:
        sshPrivKeyFile = config['config_sshPrivKeyFile']
    if 'config_sshPubKeyFile' in config:
        sshPubKeyFile = config['config_sshPubKeyFile']

    if 'config_offlineUsageStorage' in config_values and not utils.empty(config_values['config_offlineUsageStorage']):
        offlineUsageStorageLoc = config_values['config_offlineUsageStorage']

    if not utils.empty(offlineUsageStorageLoc):
        drive, offlinePath = os.path.splitdrive(offlineUsageStorageLoc)
        offlinePath = offlinePath.replace(os.sep, posixpath.sep)
    else:
        if len(localSshfsMounts) > 0:
           errMsg = "Error in start_containerFunc: Please specify a local storage path (and populate it with offline content) in order to run with locally mounted content."
           raise Exception(errMsg)

    if 'config_repoCloneLoc' in config_values and not utils.empty(config_values['config_repoCloneLoc']):
        repoCloneLoc = config_values['config_repoCloneLoc']

    if not utils.empty(repoCloneLoc):
        drive, repoPath = os.path.splitdrive(repoCloneLoc)
        repoPath = repoPath.replace(os.sep, posixpath.sep)
        localRepoPath = str(Path(f'{repoPath}/repos'))
    else:
        if not utils.empty(repo_uri):
           errMsg = "Error in start_containerFunc: Please specify a repo clone location in order to clone repos."
           raise Exception(errMsg)
        localRepoPath = None

    localSshfsMounts_translated = []
    if localSshfsMounts is not None:
        for curLocalSshfsMount in localSshfsMounts:        
            curLocalSshfsMount_local_path = str(Path(f'{offlinePath}/{curLocalSshfsMount[4]}'))
            curLocalSshfsMount_container_mount_point = curLocalSshfsMount[4]
            localSshfsMounts_translated.append([curLocalSshfsMount_local_path,curLocalSshfsMount_container_mount_point])

    if utils.empty(main_app):
        main_app = 'rstudio'

    ports={"22":"",mainAppContainerPort:""}
    if main_app == 'vscode':
        ports={"22":"",vscodeContainerPort:""}
        vscode = None

    labels = {}
    if not other_labels is None:
        for curLabel in other_labels:
            labels[curLabel] = other_labels[curLabel]

    labels['MAIN_APP'] = main_app

    if not utils.empty(vscode) and vscode == 'on':
        vscode = '_vscode'
        ports[vscodeContainerPort] = ""
    else:
        vscode = ''

    # Generate supervisord conf file
    supervisord_conf_file_name = f'supervisord_{main_app}{vscode}.conf'
    supervisord_conf_file_path = os.path.join(app.config['FILES_PATH'],supervisord_conf_file_name)
    genSupervisordConf([main_app, vscode], supervisord_conf_file_path)

    try:
        docker_client = DockerLocal.getDockerClient()
    except Exception as e:
        raise Exception('Error connecting to Docker in start_containerFunc',": Details: " + str(e))

    curUser = runAsUser
    ep = ['/bin/bash']
    the_env = [
        "DOCKER_RUN=True",
        f"LOCKER_WORKING_DIR_VAR={lockerConfig.env_vars['LOCKER_WORKING_DIR']}",
        f"LOCKER_PROJECT_OWNER_VAR={lockerConfig.env_vars['LOCKER_PROJECT_OWNER']}",
        f"LOCKER_STARTING_USERNAME_VAR={lockerConfig.env_vars['LOCKER_STARTING_USERNAME']}",
        f"{lockerConfig.env_vars['LOCKER_WORKING_DIR']}={containerUserHomedir}",
        f"{lockerConfig.env_vars['LOCKER_PROJECT_OWNER']}={curUser}",
        f"{lockerConfig.env_vars['LOCKER_STARTING_USERNAME']}={curUser}",
        f"USER={containerUser}",
        f"HOME={containerUserHomedir}",
        f'DOCKER_HOST_SERVER={host}',
        f'DOCKER_HOST_USER={hostUser}'
    ]

    if not utils.empty(tzEnv):
        the_env.append('TZ=' + tzEnv)

    if os.path.isfile(envVarFile):
        with open(envVarFile) as file_in:
            for line in file_in:
                the_env.append(line.strip())

    if utils.empty(container_name):
        container_name = None


    if hostUsablePorts is not None:
        lockerUsedContPorts = getUsedLockerContainerPorts()
        for contPort in ports:
            availPort = getAvailablePort(lockerUsedContPorts)
            if availPort is None:
                raiseException("Error: No host ports remaining to start a new container.")
            if local_or_remote == 'l':
                ports[contPort] = ('127.0.0.1',availPort)
            else:
                ports[contPort] = availPort
            lockerUsedContPorts.add(availPort)        
    else:
        for contPort in ports:
            if local_or_remote == 'l':
                ports[contPort] = ('127.0.0.1',None)
            else:
                ports[contPort] = None

    try:
        set_hostUserUid = None
        set_hostUserGid = None
        if os.getenv('RESET_USER_UGIDS') == 'True':
            set_hostUserUid = os.getenv('DOCKER_HOST_USER_UID')
            set_hostUserGid = os.getenv('DOCKER_HOST_USER_GID')
        contObj = DockerLocal.runContainer(docker_client, image=image, ports=ports, entrypoint=ep,environment=the_env,labels=labels,name=container_name,
                                           enableSiblingCont = not utils.empty(sibling_cont) and sibling_cont == 'on',
                                           enableGPU = not utils.empty(enable_gpu) and enable_gpu == 'on', hostRoot = os.getenv('DOCKER_HOST_ROOT'),
                                           hostUserUid = set_hostUserUid, hostUserGid = set_hostUserGid)
        contObj.reload()
    except Exception as e:
        raise Exception('Error starting (and reloading attrs for) the new Docker container in start_containerFunc: ' + str(e))

    copyIntoContainerPaths= { supervisord_conf_file_path: f'/etc/supervisor/conf.d/{supervisord_conf_file_name}',
                              os.path.join(app.config['FILES_PATH'],'custom'): '/var/opt/workspaces/',
                              os.path.join(app.config['FILES_PATH'],'paths_ac.py'): '/tmp/paths_ac.py'}

    if os.path.isfile(envVarFile):
        copyIntoContainerPaths[envVarFile] = f'{containerUserHomedir}/.env'
    if os.path.isfile(startupScript):
        copyIntoContainerPaths[startupScript] = f'{containerUserHomedir}/.startupScript'
    try:
        for src,dest in copyIntoContainerPaths.items():
            DockerLocal.copyIntoContainer2(contObj=contObj,src=src,dst=dest)
            cmd=f'chown -R {containerUser}:{containerUser} {dest}'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
            cmd=f'chmod -R 0777 {dest}'
            DockerLocal.execRunWrap(contObj,cmd,raiseExceptionIfExitCodeNonZero=True)
    except Exception as e:
        raise Exception('Error copying files into the new Docker container in start_containerFunc: ' + str(e))

    contStartupScriptTxt = DockerLocal.containerStartupScript()

    unsetProxiesCmd = 'unset {HTTP,HTTPS,FTP,NO}_PROXY && unset {http,https,ftp,no}_proxy'
    contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = unsetProxiesCmd, asUser = None, notOnRestartFlag = False)        
    if proxyHandling == 'set' or (proxyHandling == 'check' and utils.checkOnVpnOrOrgOrCorporateNetwork(host=configCheckProxyServer)):
        print("config.proxyHandling == " + proxyHandling + ", setting proxies in container.")
        setProxiesScriptCmd = utils.setProxiesScript(proxiesHash=configProxies)
        DockerLocal.copyIntoContainer2(contObj=contObj,srcContent=setProxiesScriptCmd.encode(), dst=f'{containerUserHomedir}/.proxyEnv')
        chownProxyEnvCmd = f"/bin/sh -c \"chown {containerUser} {containerUserHomedir}/.proxyEnv\""
        contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = chownProxyEnvCmd, asUser = None, notOnRestartFlag = False)
        #See here: https://stackoverflow.com/questions/3557037/appending-a-line-to-a-file-only-if-it-does-not-already-exist
        lineToAdd = f'source {containerUserHomedir}/.proxyEnv'
        echoCmdTxt = f'echo "{lineToAdd}" >> {containerUserHomedir}/.bashrc'
        theCmd = f'/bin/sh -c \'grep -qxF "{lineToAdd}" {containerUserHomedir}/.bashrc || ({echoCmdTxt})\''
        contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = theCmd, asUser = None, notOnRestartFlag = True)
        contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = lineToAdd, asUser = None, notOnRestartFlag = False)
    elif proxyHandling == 'unset':
        print("config.proxyHandling == " + proxyHandling + ", no proxies will be set in container.")
        for curEnv in ['HTTP_PROXY','HTTPS_PROXY','FTP_PROXY','NO_PROXY','http_proxy','https_proxy','ftp_proxy','no_proxy']:
            echoCmdUnsetRProfileCmd = "/bin/sh -c \"echo 'Sys.unsetenv(\\\"" + curEnv + f"\\\")' >> {containerUserHomedir}/.Rprofile\""
            contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = echoCmdUnsetRProfileCmd, asUser = None, notOnRestartFlag = True)
    else:
        print("config.proxyHandling == " + proxyHandling + ", no proxies will be set in container.")
        for curEnv in ['HTTP_PROXY','HTTPS_PROXY','FTP_PROXY','NO_PROXY','http_proxy','https_proxy','ftp_proxy','no_proxy']:
            echoCmdUnsetRProfileCmd = "/bin/sh -c \"echo 'Sys.unsetenv(\\\"" + curEnv + f"\\\")' >> {containerUserHomedir}/.Rprofile\""
            contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = echoCmdUnsetRProfileCmd, asUser = None, notOnRestartFlag = True)

    try:
        contStartupScriptTxt = DockerLocal.containerStartup(contObj,sshPubKeyFile=sshPubKeyFile, sshPrivKeyFile=sshPrivKeyFile,
                                                            networkSshfsMounts=networkSshfsMounts,localSshfsMounts=localSshfsMounts_translated,
                                                            localRepoPath=localRepoPath, user=curUser, contStartupScriptTxt = contStartupScriptTxt)
        if not utils.empty(sibling_cont) and sibling_cont == 'on':
            DockerLocal.setupDockerCli(contObj,app.config['FILES_PATH'])
    except Exception as e:
        raise Exception('Error running container startup in start_container: ' + str(e))

    dockerHostEchoCmd = f"/bin/sh -c \"echo 'export DOCKER_HOST_SERVER={host}\nexport DOCKER_HOST_USER={hostUser}' >> {containerUserHomedir}/.bashrc\""
    contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = dockerHostEchoCmd, asUser = containerUser, notOnRestartFlag = True)

    if os.path.isfile(envVarFile):
        #See here: https://gist.github.com/mihow/9c7f559807069a03e302605691f85572
        echoCmd = f"/bin/sh -c \"echo 'set -o allexport; source {containerUserHomedir}/.env; set +o allexport' >> {containerUserHomedir}/.bashrc\""
        contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = echoCmd, asUser = containerUser, notOnRestartFlag = True)

    if os.path.isfile(startupScript):
        chownChmodStartupScriptCmd = f"/bin/sh -c \"chown {containerUser} {containerUserHomedir}/.startupScript; chmod u+x {containerUserHomedir}/.startupScript\""
        contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = chownChmodStartupScriptCmd, asUser = None, notOnRestartFlag = False)
        execStartupScriptCmd = f"/bin/sh -c \"{containerUserHomedir}/.startupScript\""
        contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = execStartupScriptCmd, asUser = containerUser, notOnRestartFlag = False)

    if local_or_remote == 'r':
        try:
            contStartupScriptTxt = DockerLocal.setupApacheProxy(contObj, app.config['FILES_PATH'], allowedUsers=list(set([curUser] + locker_admins)), contStartupScriptTxt=contStartupScriptTxt)
        except Exception as e:
            raise Exception('Error setting up Apache SiteMinder proxy in start_container: ' + str(e))

    if not utils.empty(repo_uri):
        contStartupScriptTxt = cloneRepoUriInContainer(repo_uri,repo_release,contStartupScriptTxt)

    #Start up selected main apps (RStudio, Jupyter, Jupyterlab, and/or VScode) with supervisord
    runSupervisord = f'/usr/bin/supervisord -c /etc/supervisor/conf.d/{supervisord_conf_file_name}'
    contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = runSupervisord, asUser = None, notOnRestartFlag = False)

    DockerLocal.copyIntoContainer2(contObj=contObj,srcContent=contStartupScriptTxt.encode(), dst=f'{containerUserHomedir}/.containerStartupScript')

    DockerLocal.execRunWrap(contObj, f'/bin/sh -c "chmod +x {containerUserHomedir}/.containerStartupScript"',raiseExceptionIfExitCodeNonZero=True)
    DockerLocal.execRunWrap(contObj, f'/bin/sh -c "{containerUserHomedir}/.containerStartupScript"',detach=True,environment=["SHELL=/bin/bash"],raiseExceptionIfExitCodeNonZero=True)

    return(contObj)

#Called when the user submits the form displayed by start_container_form, this route
#does the actual work to start the container (via utility function start_containerFunc above).
#After container is started, redirects back to the home page to show the table of all
#started containers (where the user can click links there to actually access the services
#like ssh, RStudio, etc. running in the containers).
@app.route('/start-container', methods=['POST'])
def start_container():

    image = request.values.get('image')
    main_app = request.values.get('main_app')
    container_name = request.values.get('container_name')
    repo_uri = request.values.get('repo_uri')
    repo_release = request.values.get('repo_release')
    vscode = request.values.get('vscode')
    sibling_cont = request.values.get('sibling_cont')
    enable_gpu = request.values.get('enable_gpu')
    envVarFile = request.values.get('envVarFile')
    startupScript = request.values.get('startupScript')

    networkSshfsMounts = []
    localSshfsMounts = []
    for curSshfsMount in sshfsMounts:
        curSshfsMountId = curSshfsMount[1]        
        network_mount_curSshfsMount = request.values.get(curSshfsMountId)
        local_mount_curSshfsMount = request.values.get('local_' + curSshfsMountId)
        #Locally mounting takes priority
        if not utils.empty(local_mount_curSshfsMount) and local_mount_curSshfsMount == 'on':
            localSshfsMounts.append(curSshfsMount)
        elif not utils.empty(network_mount_curSshfsMount) and network_mount_curSshfsMount == 'on':
            networkSshfsMounts.append(curSshfsMount)

    try:
        config = utils.readConfig(config_file_path)
        config_values = utils.readUserConfigValues(config_file_path=config_file_path)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error reading user config values in start_container',": Details: " + str(e),"start_container_Err0")
        flash(fullMsg, "error")
        return render_template('error.html')

    offlineUsageStorageLoc = None
    repoCloneLoc = None

    if utils.empty(envVarFile):
        if 'config_envVarFile' in config_values and not utils.empty(config_values['config_envVarFile']):
            envVarFile = config_values['config_envVarFile']
        else:
            envVarFile = ""
    if not utils.empty(envVarFile) and not envVarFile.startswith('/host_root'):
        envVarFile = '/host_root' + envVarFile

    if utils.empty(startupScript):
        if 'config_startupScript' in config_values and not utils.empty(config_values['config_startupScript']):
            startupScript = config_values['config_startupScript']
        else:
            startupScript = ""
    if not utils.empty(startupScript) and not startupScript.startswith('/host_root'):
        startupScript = '/host_root' + startupScript

    if 'config_offlineUsageStorage' in config_values and not utils.empty(config_values['config_offlineUsageStorage']):
        offlineUsageStorageLoc = config_values['config_offlineUsageStorage']

    if 'config_repoCloneLoc' in config_values and not utils.empty(config_values['config_repoCloneLoc']):
        repoCloneLoc = config_values['config_repoCloneLoc']

    if utils.empty(offlineUsageStorageLoc):
        if len(localSshfsMounts) > 0:
            errMsg = "Error in start_container: You must have configured an offline local storage location in order to use locally cached network drive content."
            flash(errMsg, "error")
            return render_template('error.html')

    if utils.empty(repoCloneLoc):
        if not utils.empty(repo_uri):
            errMsg = "Error in start_container: You must have configured a repo clone location in order to clone a repo."
            flash(errMsg, "error")
            return render_template('error.html')

    if not utils.empty(repo_uri):
        #If the user just copied the url of the Git repo from the browser url bar, just append .git to it so it will work for cloning
        if not repo_uri.endswith(".git") and not repo_uri.endswith("/"):
            repo_uri = repo_uri + ".git"

    try:
        contObj = start_containerFunc(image, main_app, container_name, vscode, networkSshfsMounts, localSshfsMounts, sibling_cont, enable_gpu, envVarFile = envVarFile, startupScript = startupScript, repo_uri = repo_uri, repo_release = repo_release, other_labels = { '__LOCKER_WORKSPACE_CONTAINER__': 'True' })
    except Exception as e:
        fullMsg = utils.genShowHideMessage(f'Error in start_container',": Details: " + str(e),"start_containerErr1")
        flash(fullMsg, "error")
        return render_template('error.html')

    return redirect(url_for('home'))

def cloneRepoUriInContainer(repo_uri,repo_release,contStartupScriptTxt):

    try:
        config = utils.readConfig(config_file_path)
        config_values = utils.readUserConfigValues(config_file_path=config_file_path)
    except Exception as e:
        raise Exception('Error getting config in cloneRepoUriInContainer: ' + str(e))

    repoCloneLocLoc = None
    localRepoPath = None

    if 'config_repoCloneLoc' in config_values and not utils.empty(config_values['config_repoCloneLoc']):
        repoCloneLocLoc = config_values['config_repoCloneLoc']

    if not utils.empty(repoCloneLocLoc):
        drive, offlinePath = os.path.splitdrive(repoCloneLocLoc)
        offlinePath = offlinePath.replace(os.sep, posixpath.sep)
        localRepoPath = str(Path(f'{offlinePath}/repos'))
    else:
        localRepoPath = None

    #match 2 uri formats:
    #git@biogit.pri.bms.com:smitha26/DockerLocal.git
    #https://biogit.pri.bms.com/smitha26/DockerLocal.git
    if not utils.empty(repo_uri) and not utils.empty(localRepoPath):
        matches = re.search("([^\/\:]+)\/(.+)\.git$",repo_uri)
        repo_owner = matches[1]
        just_repo_name = matches[2]
#        #Need to wait until the .containerStartupScript finishes doing things
        cmd=f'sh -c "cd /repos; test -e {just_repo_name} || git clone --recurse-submodules {repo_uri}"'
        contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = containerUser, notOnRestartFlag = True)
        if not utils.empty(repo_release):
            cmd=f'sh -c "cd /repos/{just_repo_name}; git checkout {repo_release}"'
            contStartupScriptTxt = DockerLocal.containerStartupScript(startupScriptTxt = contStartupScriptTxt, commandToAdd = cmd, asUser = containerUser, notOnRestartFlag = True)
    else:
        if utils.empty(localRepoPath):
            raise Exception("Error in cloneRepoUriInContainer: you must specify a path for offline local storage in config in order to clone repos into started containers.")
        if utils.empty(repo_uri):
            raise Exception("Error in cloneRepoUriInContainer: you did not specify a repo_uri.")

    return(contStartupScriptTxt)

#Stop or restart all containers
@app.route('/all-containers-action', methods=['POST','GET'])
def all_containers_action():

    action = request.args.get('action')
    if not action == 'stop' and not action == 'restart' and not action == 'terminate':
        fullMsg = utils.genShowHideMessage('Error in all_containers_action, action must be stop, restart, or terminate')
        flash(fullMsg, "error")
        return render_template('error.html');

    try:
        docker_client = DockerLocal.getDockerClient()
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error connecting to Docker',": Details: " + str(e),"allContActErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    try:
        containers = docker_client.containers.list(all=True)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error fetching container list from Docker',": Details: " + str(e),"allContActErr2")
        flash(fullMsg, "error")
        return render_template('error.html');

    for curContObj in containers:
        if '__FOR_OFFLINE_IMAGE_ENABLE__' in curContObj.labels and curContObj.labels['__FOR_OFFLINE_IMAGE_ENABLE__'] == 'True':
            continue
        if not '__LOCKER_WORKSPACE_CONTAINER__' in curContObj.labels or not curContObj.labels['__LOCKER_WORKSPACE_CONTAINER__'] == 'True':
            continue

        if (curContObj.status == 'running' and action == 'stop') or (curContObj.status == 'exited' and action == 'restart'):
            try:
                DockerLocal.execContainerAction(curContObj, action)
                if action == 'restart':
                    DockerLocal.execRunWrap(curContObj, f'/bin/sh -c "{containerUserHomedir}/.containerStartupScript -r"',detach=True,environment=["SHELL=/bin/bash"],raiseExceptionIfExitCodeNonZero=True)
            except Exception as e:
                fullMsg = utils.genShowHideMessage(f'Error performing {action} in all_containers_action',": Details: " + str(e),"allContActErr3a")
                flash(fullMsg, "error")
                return render_template('error.html');
        elif action == 'terminate':
            try:
                DockerLocal.execContainerAction(curContObj, 'stop')
                DockerLocal.execContainerAction(curContObj, 'remove')
            except Exception as e:
                fullMsg = utils.genShowHideMessage(f'Error performing {action} in all_containers_action',": Details: " + str(e),"allContActErr3b")
                flash(fullMsg, "error")
                return render_template('error.html');

    return redirect(url_for('home'))

#This route will perform specified actions (e.g. stop, pause, remove, etc.)
#on a container, after which it redirects to the home page to show the
#table of all containers.
@app.route('/container-actions', methods=['POST','GET'])
def container_actions():

    container = request.args.get('container')
    actions = request.args.get('actions')

    if utils.empty(actions):
        fullMsg = utils.genShowHideMessage('Error, no actions specified in container_actions',"contActionsErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    contObj = None
    try:
        docker_client = DockerLocal.getDockerClient()
        contObj = docker_client.containers.get(container)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error connecting to Docker and getting container in container_actions',": Details: " + str(e),"contActionsErr2")
        flash(fullMsg, "error")
        return render_template('error.html');

    actionsList = actions.split(",")

    for curAction in actionsList:
        try:
            DockerLocal.execContainerAction(contObj, curAction)
            if curAction == 'restart':
                DockerLocal.execRunWrap(contObj, f'/bin/sh -c "{containerUserHomedir}/.containerStartupScript -r"',detach=True,environment=["SHELL=/bin/bash"],raiseExceptionIfExitCodeNonZero=True)
        except Exception as e:
            fullMsg = utils.genShowHideMessage(f'Error performing action {curAction} in container_actions',": Details: " + str(e),"contActionsErr3")
            flash(fullMsg, "error")
            return render_template('error.html');

    return redirect(url_for('home'))

#This route will remove an image from the local Docker
#daemon, then redirect to the page showing the table of
#all images.
@app.route('/remove-image', methods=['POST','GET'])
def remove_image():

    image = request.args.get('image')

    try:
        docker_client = DockerLocal.getDockerClient()
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error connecting to Docker in remove_image',": Details: " + str(e),"remImageErr1")
        flash(fullMsg, "error")
        return render_template('error.html');

    try:
        docker_client.images.remove(image)
    except Exception as e:
        fullMsg = utils.genShowHideMessage('Error removing image from Docker in remove_image',": Details: " + str(e),"remImageErr2")
        flash(fullMsg, "error")
        return render_template('error.html');

    return redirect(url_for('images'))

@app.errorhandler(404)
def page_not_found(error):
    return render_template('page_not_found.html'), 404

#See here for how to store application wide values
#in app.config as kind of hack: https://www.reddit.com/r/flask/comments/1azce1/ask_flask_application_wide_variable/
#Here is info on getting epoch time:
#https://stackoverflow.com/questions/4548684/how-to-get-the-seconds-since-epoch-from-the-time-date-output-of-gmtime
#This route deals with the hearbeats that the app running in the browser will regularly send, and a separately
#running thread will check the last heartbeat and shutdown the app/server if no heartbeat in 3 min.
@app.route('/heartbeat', methods=['GET','POST'])
def heartbeat():
    if (request.args.get('action') == 'set'):
        app.config['last_hb'] = int(time.time())
#        print("set heartbeat: " + str(app.config['last_hb']))
        return str(app.config['last_hb'])
    elif (request.args.get('action') == 'get'):
        if (app.config['last_hb'] is None):
            app.config['last_hb'] = int(time.time())
#        print("get heartbeat: " + str(app.config['last_hb']))
        return str(app.config['last_hb'])

#See here for where I got this: https://stackoverflow.com/questions/15562446/how-to-stop-flask-application-without-using-ctrl-c
def shutdown_server():

    try:
        DockerLocal.stopContainersHavingLabel('__FOR_OFFLINE_IMAGE_ENABLE__', labelValue = 'True')
    except Exception as e:
        print("Error stopping offline configuring containers before shutdown: " + str(e))

    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')

    try:
        func()
    except Exception as e:
        print("Error shutting down server in shutdown_server: " + str(e))

#This route will cause the app/server to be shutdown.
@app.route('/shutdown')
def shutdown():
    print("About to shutdown...")
    removeContainerShutdownThread()
    return 'Application shutting down...'

def removeContainerShutdownThread():
    def remove_container_shutdown():
        time.sleep(10)
        DockerLocal.removeMyLockerContainer()
        shutdown_server() #This should not get called if the container was removed by preceding line, but if some error with that at least exit the Flask server and stop container

    thread = threading.Thread(target=remove_container_shutdown, daemon=True)
    thread.start()


#A separate thread is run to do an image pull (so the user can still
#use the app for other things while the pull is happening). This
#function executes the pull in a newly started Thread.
def startPullThread(imageToPull,config_values):
    def pull_loop(image):

        docker_client = DockerLocal.getDockerClient(lowLevel=True)

        if config.useEcrFlag and image.startswith(ecr_domain):
            ecr_client = ecr.getEcrClient(accessKey=config_values['aws_access_key_id'],secretKey=config_values['aws_secret_access_key'],awsRegion=aws_region)
            auth_config = ecr.ecrLogin(docker_client,ecr_client)
            imageToPull = image
        elif image.startswith(configRegistryName):
            auth_config = DockerRegistry.registryLogin(docker_client,registryUrl=configRegistryUrl)
            imageToPull = image
        else:
            auth_config = None
            imageToPull = image

        curImageProgress = {}
        pullImageProgress[image] = curImageProgress
        for line in docker_client.pull(imageToPull, stream=True, decode=True, auth_config = auth_config):
            if 'id' in line and 'status' in line and 'progress' in line:
                if line['status'] == 'Extracting':
                    line['status'] = line['status'] + " "
                curImageProgress[line['id']] = line['status'] + " " + line['progress']

        del pullImageProgress[image]

        print("Done pulling image: " + imageToPull)

    thread = threading.Thread(target=pull_loop, daemon=True, kwargs={ 'image': imageToPull })
    thread.start()

#See here for where I got this: https://networklore.com/start-task-with-flask/
#Separate thread is started to regularly (every 15 seconds) update registry images
def start_runner():
    def start_loop():
        #Update images available from registry every 15 seconds
        while True:
            try:
                DockerLocal.getRegistryImages(config_file_path,cachedImageInfo)
            except Exception as e:
                raise Exception('Error getting registry images data',": Details: " + str(e))

            time.sleep(15)

    print('Started thread to update registry images.')
    thread = threading.Thread(target=start_loop, daemon=True)
    thread.start()

#Attempt to shutdown any already running server (that user might have not stopped before quitting):
try:
    requests.get('http://localhost:5000/shutdown')
except:
    print("No server was already running.")

start_runner()

app.run(debug=False,host='0.0.0.0',port=5000) #listen from all hosts (which just allows host connections into this container running Locker)
