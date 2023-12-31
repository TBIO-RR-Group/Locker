#!/usr/bin/env python

import os
import getpass
import socket
import json
from pathlib import Path
import re
import validators
import ipaddress
import platform
import subprocess
from flask import Markup

def empty(str):
    """
    Return True if the str is None or composed of only whitespace, False otherwise
    """

    if str is None:
        return True
    if str.strip() == "":
        return True
    return False

def valOrEmpty(str):
    """
    Return str if it is not None/whitespace, and "" otherwise
    """

    if empty(str):
        return ""
    else:
        return str

def genShowHideMessage(alwaysShowTxt,initHideTxt,id):
    """
    Generate a markup string where alwaysShowTxt is always displayed, and initHideTxt is
    initially hidden but can be shown/hidden by clicking a +/- link. id sets dom ids for
    a created span and a element.
    """


    hiddenMsg = "<span style='display:none;' id='" + id + "'>" + initHideTxt + "</span><a style='cursor:pointer;' id='" + id + "_clickon' onclick='toggleShowHide(\"" + id + "\");'>&nbsp;+</a>";
    fullMsg = alwaysShowTxt + Markup(hiddenMsg)

    return(fullMsg)

def getUser():
    """
    Try to get the logged in user's username in various ways, and return the value gotten
    """

    try:
        user = getpass.getuser()
    except Error:
        user = os.getlogin()

    return user

#Got from here: https://stackoverflow.com/questions/12041525/a-system-independent-way-using-python-to-get-the-root-directory-drive-on-which-p
def root_path():
    """
    Return the root path of the machine (e.g. '/' on a Linux/Unix box)
    """

    return os.path.abspath(os.sep)

def pathContents(thePath,ftype):
    """
    Given an input path (e.g. /var/lib/) return the contents of that path
    as an array of hashes; also returns the parent path (returns these in a hash
    keyed by 'paths' and 'parent_path'). If the last part of the input value
    thePath is not an existing directory (e.g. STRVAL in /var/lib/STRVAL)
    it is used as an a pattern to match (e.g. only return dirs/files having
    STRVAL in them). ftype should be 'DIR', 'FILE' or 'DIR' --- if 'FILE' or
    'DIR' only files or dirs will be returned (otherwise all).
    """

    if empty(ftype):
        ftype = 'BOTH'
    if ftype != 'DIR' and ftype != 'FILE' and ftype != 'BOTH':
        raise Exception("Error in pathContents: ftype must be 'BOTH','DIR', or 'FILE'")

    origThePath = thePath
    matchTxt = None
    if not os.path.exists(thePath):
        pathInfo = os.path.split(thePath)
        thePath = pathInfo[0]
        matchTxt = pathInfo[1]
        if not os.path.exists(thePath):
            raise Exception(f'path or its prefix does not exist or is not accessible for {origThePath}')

    parentPathInfo = os.path.split(thePath)
    thePathParent = parentPathInfo[0]
    parentName = parentPathInfo[1]

    if not os.access(thePath, os.R_OK):
        return({'paths':[],'parent_path':thePathParent})

    if os.path.isfile(thePath):
        return({'paths': [{'path': thePath,'isfile': True}],'parent_path':thePathParent})

    contents = [{'path':os.path.join(thePath,cur),'isfile':os.path.isfile(os.path.join(thePath,cur))} for cur in os.listdir(thePath) if os.access(os.path.join(thePath,cur),os.R_OK)]
    if ftype == 'FILE':
        contents = [cur for cur in contents if cur['isfile']]
    elif ftype == 'DIR':
        contents = [cur for cur in contents if not cur['isfile']]
    if not empty(matchTxt):
        contents = [cur for cur in contents if matchTxt in os.path.split(cur['path'])[1]]

    contents = sorted(contents, key=lambda k: str.casefold(k['path'])) 

    return({'paths':contents, 'parent_path':thePathParent})

def readUserConfigValues(config_file_path=None, config=None):
    """
    Given either config (object) or config_file_path (path to
    config json), read in the actual values from files pointed
    to by the user's config (e.g. read in the value of a user's
    private SSH key from the path to it in user's config).
    """

    if config_file_path is None and config is None:
        raise Exception('Error in utils.readUserConfigValues: both of config_file_path and config are None, one must have a value.')

    if config_file_path is not None:
        config = readConfig(config_file_path,rebase=False)

    config_values = {}
    if 'config_offlineUsageStorage' in config and not empty(config['config_offlineUsageStorage']):
        if os.path.exists('/host_root' + config['config_offlineUsageStorage']):
            config_values['config_offlineUsageStorage'] = '/host_root' + config['config_offlineUsageStorage']
        else:
            offlineUsageStoragePath = config['config_offlineUsageStorage']
            raise Exception(f'Error in utils.readUserConfigValues: a path "{offlineUsageStoragePath}" was specified for config_offlineUsageStorage, but it does not exist. Please update your configuration.')
    if 'config_repoCloneLoc' in config and not empty(config['config_repoCloneLoc']):
        if os.path.exists('/host_root' + config['config_repoCloneLoc']):
            config_values['config_repoCloneLoc'] = '/host_root' + config['config_repoCloneLoc']
        else:
            repoCloneLoc = config['config_repoCloneLoc']
            raise Exception(f'Error in utils.readUserConfigValues: a path "{repoCloneLoc}" was specified for config_repoCloneLoc, but it does not exist. Please update your configuration.')
    if 'config_sshPrivKeyFile' in config and not empty(config['config_sshPrivKeyFile']):
        if os.path.exists('/host_root' + config['config_sshPrivKeyFile']):
            config_values['config_sshPrivKey'] = slurpFile('/host_root' + config['config_sshPrivKeyFile'])
        else:
            sshPrivKeyPath = config['config_sshPrivKeyFile']
            raise Exception(f'Error in utils.readUserConfigValues: a path "{sshPrivKeyPath}" was specified for config_sshPrivKeyFile, but it does not exist. Please update your configuration.')
    if 'config_sshPubKeyFile' in config and not empty(config['config_sshPubKeyFile']):
        if os.path.exists('/host_root' + config['config_sshPubKeyFile']):
            config_values['config_sshPubKey'] = slurpFile('/host_root' + config['config_sshPubKeyFile'])
        else:
            sshPubKeyPath = config['config_sshPubKeyFile']
            raise Exception(f'Error in utils.readUserConfigValues: a path "{sshPubKeyPath}" was specified for config_sshPubKeyFile, but it does not exist. Please update your configuration.')
    if 'config_awsCredsFile' in config and not empty(config['config_awsCredsFile']):
        if os.path.exists('/host_root' + config['config_awsCredsFile']):
            awsCreds = slurpFile('/host_root' + config['config_awsCredsFile'])
            #This Python regex howto was useful to me here: https://docs.python.org/3/howto/regex.html
            accessKeyMatch = re.search(r"^aws_access_key_id = ([^\s]+)$", awsCreds,re.M)
            if accessKeyMatch:
                config_values['aws_access_key_id'] = accessKeyMatch.group(1)
            secretKeyMatch = re.search(r"^aws_secret_access_key = ([^\s]+)$", awsCreds,re.M)
            if secretKeyMatch:
                config_values['aws_secret_access_key'] = secretKeyMatch.group(1)
        else:
            awsCredsFilePath = config['config_awsCredsFile']
            raise Exception(f'Error in utils.readUserConfigValues: a path "{awsCredsFilePath}" was specified for config_awsCredsFile, but it does not exist. Please update your configuration.')
    if 'config_envVarFile' in config and not empty(config['config_envVarFile']):
        envVarFilePath = config['config_envVarFile']
        if not os.path.exists('/host_root' + envVarFilePath):
            raise Exception(f'Error in utils.readUserConfigValues: a path "{envVarFilePath}" was specified for config_envVarFile, but it does not exist. Please update your configuration.')
        else:
            config_values['config_envVarFile'] = '/host_root' + envVarFilePath
    if 'config_startupScript' in config and not empty(config['config_startupScript']):
        startupScriptPath = config['config_startupScript']
        if not os.path.exists('/host_root' + startupScriptPath):
            raise Exception(f'Error in utils.readUserConfigValues: a path "{startupScriptPath}" was specified for config_startupScript, but it does not exist. Please update your configuration.')
        else:
            config_values['config_startupScript'] = '/host_root' + startupScriptPath

    return(config_values)

def writeConfig(config_file_path,config,rebase=True):

    if rebase:
        config_copy = config.copy() #shallow copy, but sufficient for needs
        rebasePathKeys = ["config_sshPrivKeyFile", "config_sshPubKeyFile", "config_awsCredsFile", "config_offlineUsageStorage", "config_repoCloneLoc", "config_envVarFile", "config_startupScript" ]
        for cur in rebasePathKeys:
            if cur in config_copy:
                m = re.search('^/host_root(.+)',config_copy[cur])
                if m:
                    config_copy[cur] = m.group(1)
    else:
        config_copy = config

    with open(config_file_path,'w') as config_file:
        json.dump(config_copy, config_file)


def readConfig(config_file_path,rebase=True):

    with open(config_file_path) as config_file:
        config = json.load(config_file)

    if rebase:
        rebasePathKeys = ["config_sshPrivKeyFile", "config_sshPubKeyFile", "config_awsCredsFile", "config_offlineUsageStorage", "config_repoCloneLoc", "config_envVarFile", "config_startupScript" ]
        for cur in rebasePathKeys:
            if cur in config and not empty(config[cur]):
                if not config[cur].startswith('/host_root'):
                    config[cur] = '/host_root' + config[cur]

    return(config)

def guessConfig(config,user_homedir_in=None):
    """
    Try to guess the values for user's config values (e.g. try to find
    user's public/private SSH keys inside .ssh dir in their home dir, etc.)
    Update config object with guessed values.
    """

    if user_homedir_in is not None:
        if not user_homedir_in.startswith('/host_root'):
            user_homedir = '/host_root' + user_homedir_in
        else:
            user_homedir = user_homedir_in
        privkey_path = os.path.join(user_homedir,'.ssh','id_rsa')
        pubkey_path = os.path.join(user_homedir,'.ssh','id_rsa.pub')
        awscreds_path = os.path.join(user_homedir, '.aws','credentials')
        if os.path.exists(privkey_path) and (not 'config_sshPrivKeyFile' in config or empty(config['config_sshPrivKeyFile'])):
            config['config_sshPrivKeyFile'] = privkey_path.removeprefix('/host_root')
        if os.path.exists(pubkey_path) and (not 'config_sshPubKeyFile' in config or empty(config['config_sshPubKeyFile'])):
            config['config_sshPubKeyFile'] = pubkey_path.removeprefix('/host_root')

        if os.path.exists(awscreds_path) and (not 'config_awsCredsFile' in config or empty(config['config_awsCredsFile'])):
            config['config_awsCredsFile'] = awscreds_path.removeprefix('/host_root')

    return

#Returns the IP address of the machine you are currently running on.
#Gotten from here: https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
def get_my_ip():
    """
    Return the IP address of the machine running on.
    """

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def get_my_hostname():
    """
    Return the fqdn hostname of the machine running on.
    """

    try:
        #See here: https://stackoverflow.com/questions/51890210/python-fqdn-like-hostname-fqdn
        hostname = socket.getaddrinfo(socket.gethostname(), 0, flags=socket.AI_CANONNAME)[0][3]
    except:
        hostname = None
    if empty(hostname):
        hostname = socket.getfqdn(socket.gethostname())
    return hostname

def get_my_global_host_or_ip():
    """
    Gets the hostname (if FQDN) or IP (if global),
    otherwise just returns None
    (assume locahost only in this case)
    """

    host = get_my_hostname()
    if not validators.domain(host):
        host = get_my_ip()
        if not validators.ipv4(host):
            host = None
        else:
            test_ip = ipaddress.IPv4Address(host)
            if not test_ip.is_global:
                host = None

    return host

def slurpFile(file):
    """
    Read an entire text file in and return it as a string.
    """

    try:
        result = subprocess.run(['cat', file],stdout=subprocess.PIPE)
        return result.stdout.decode('utf-8')
    except Exception as e:
        raise Exception("Error in utils.slurpFile: " + str(e))

#    try:
#        with open(file) as x: f = x.read()
#        return f
#    except Exception as e:
#        raise Exception("Error in utils.slurpFile: " + str(e))

def unsetProxies():
    """
    Unset environment variables for proxy servers (HTTP_PROXY, etc.)
    """

    for curEnv in ['HTTP_PROXY','HTTPS_PROXY','FTP_PROXY','NO_PROXY','http_proxy','https_proxy','ftp_proxy','no_proxy']:
        if curEnv in os.environ:
            del os.environ[curEnv]

def setProxies(proxiesHash=None):
    """
    Set environment variables for proxy servers (HTTP_PROXY, etc.)
    """

    if proxiesHash is not None:
        for envVar, envVarVal in proxiesHash.items():
            os.environ[envVar] = envVarVal

#Will return text containing lines like 'export http_proxy=..." that you could execute with e.g. bash
def setProxiesScript(proxiesHash=None):
    """
    Set environment variables for proxy servers (HTTP_PROXY, etc.) as bash script export commands
    """

    bashScriptTxt = ""
    if proxiesHash is not None:
        for envVar, envVarVal in proxiesHash.items():
            bashScriptTxt = bashScriptTxt + f'export {envVar}={envVarVal}' + "\n"

    return(bashScriptTxt)

#host = corporate proxy server domain
def checkOnVpnOrOrgOrCorporateNetwork(host=None):
    """
    Return True if currently connected to the corporate network
    or VPN, False otherwise. Checks by doing a ping operation to
    host.
    """

#    retcode = os.system(f'ping -c 1 {host} > /dev/null 2>&1')

    if empty(host):
        raise Exception("Error in utils.checkOnVpnOrOrgOrCorporateNetwork: input host value is empty")

    retcode = ping(host)
    if not retcode:  
        return False #VPN not connected or not on corporate network
    else:
        return True #connected to VPN or on corporate network

#Got here: https://stackoverflow.com/questions/2953462/pinging-servers-in-python
def ping(host):
    """
    Returns True if host (str) responds to a ping request.
    Remember that a host may not respond to a ping (ICMP) request even if the host name is valid.
    """

    # Option for the number of packets as a function of
    param = '-n' if platform.system().lower()=='windows' else '-c'

    # Building the command. Ex: "ping -c 1 google.com"
    command = ['ping', param, '1', host]

    FNULL = open(os.devnull, 'w')

    return subprocess.call(command, stdout=FNULL, stderr=subprocess.STDOUT) == 0
