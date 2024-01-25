#!/usr/bin/env python

import os
import sys
import getpass
import urllib.parse
import requests
import socket
import json
from pathlib import Path
import re
import platform
#from time import ctime
import time
import calendar
import subprocess
from flask import Markup
import io
import tempfile
import cgi
import cgitb; cgitb.enable() # Optional; for debugging only
from paramiko import SSHClient
import paramiko
from scp import SCPClient
import boto3
from pkg_resources import resource_filename
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import ldap
import sqlite3
from sqlite3 import Error
import http.cookies as Cookie
from Config import Config

config = Config("/config.yml")

def empty(str):
    """
    Return True if the str is None or composed of only whitespace, False otherwise
    """

    if str is None:
        return True
    if str.strip() == "":
        return True
    return False

#Return True if the port is open and can be bound to, otherwise False
#gotten and modified from here: https://gist.github.com/betrcode/0248f0fda894013382d7
def isPortOpen(port,ip="127.0.0.1"):
    """
    Return True if port is an open port on the current machine,
    (i.e. can be bound to) and False otherwise
    """

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((ip, int(port)))
        s.shutdown(2)
        return False
    except:
        return True

def slurpFile(file):
    """
    Read an entire text file in and return it as a string.
    """

    try:
        with open(file) as x: f = x.read()
        return f
    except Exception as e:
        raise Exception("Error in utils.slurpFile: " + str(e))

def printHTML(outputHTML):
    print("Content-Type: text/html")
    print()
    print(outputHTML)

def printTEXT(outputTEXT):
    print("Content-Type: text/plain")
    print()
    print(outputTEXT)

def getEnvVar(varName):
    varVal = os.environ.get(varName)
    if varVal is None:
       return('')
    else:
    	return(varVal)

def execRemoteSudoCmd(sudo_cmd, hostname, server_username, sshprivkey=None, password=None):

    remoteRes = { "success": False, "error_msg": "You must provide correct args to utils.execRemoteSudoCmd, sudo_cmd, hostname, server_username and one of sshPrivKey or password." }
    #Prefer password if it is given, as that allows the sudo command to be run (using sudo_run_commands_remote) if the user doesn't have password-less sudo on the remove host
    if not empty(password):
        remoteRes = sudo_run_commands_remote(sudo_cmd, hostname, server_username, password)
    elif not empty(sshprivkey):
        remoteRes = execRemoteCmd(f'sudo bash -c "{sudo_cmd}"',server_username,hostname,sshprivkey=sshprivkey,password=password,get_pty=True)

    return(remoteRes)

def sudo_run_commands_remote(command, server_address, server_username, server_pass):

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=server_address,
                    username=server_username,
                    password=server_pass)

        #See here for where I got idea for this: https://stackoverflow.com/questions/46285449/python-paramiko-executing-sudo
        #See also here: https://stackoverflow.com/questions/6270677/how-to-run-sudo-with-paramiko-python
        stdin, stdout, stderr = ssh.exec_command("sudo -S bash -c \"" + command + "\"")
        stdin.write(server_pass + '\n')
        stdin.flush()
        stdout_lines = stdout.read().decode("utf-8")
        stderr_lines = stderr.read().decode("utf-8")
        #https://stackoverflow.com/questions/3562403/how-can-you-get-the-ssh-return-code-using-paramiko
        exit_code = stdout.channel.recv_exit_status()
        return({ "success": True, "stdout_lines": stdout_lines, "stderr_lines": stderr_lines, "exit_code": exit_code })
    except Exception as e:
        return({ "success": False, "error_msg": "Error executing remote sudo command in utils.sudo_run_commands_remote: " + str(e) })


def sshConnect(username,hostname,password=None,sshprivkey=None,port=22):

    pkey = None

    if sshprivkey is not None:

        # Try each key type
        for cls in [paramiko.RSAKey, paramiko.DSSKey, paramiko.ECDSAKey, paramiko.Ed25519Key]:
            pkey_file = io.StringIO(initial_value=sshprivkey) # needs be inside loop
            try:
                pkey = cls.from_private_key(pkey_file)
            except paramiko.ssh_exception.SSHException:
                pass
            else:
                break
        
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=hostname, port=port, username=username, pkey=pkey, password=password, banner_timeout=200)

    return(ssh)

def execRemoteCmd(command,username,hostname,stdinTxt=None,password=None,sshprivkey=None,port=22,get_pty=False):

    try:
        ssh = sshConnect(username,hostname, password=password, sshprivkey=sshprivkey,port=port)
    except Exception as e:
        return({ "success": False, "error_msg": "Error doing sshConnect in utils.execRemoteCmd: " + str(e) })

    
    try:
        stdin, stdout, stderr = ssh.exec_command(command, get_pty=get_pty)
    except Exception as e:
        return({ "success": False, "error_msg": "Error doing ssh.exec_command in utils.execRemoteCmd: " + str(e) })

    #See here: https://stackoverflow.com/questions/48554497/how-do-i-write-to-stdin-returned-from-exec-command-in-paramiko
    try:
        if stdinTxt is not None:
            stdin.channel.send(stdinTxt)
            stdin.channel.shutdown_write()
    except Exception as e:
        return({ "success": False, "error_msg": "Error writing stdin for remote command in utils.execRemoteCmd: " + str(e) })

    try:
        stdout_lines = stdout.readlines()
        stderr_lines = stderr.readlines()
    except Exception as e:
        return({ "success": False, "error_msg": "Error reading result stdout and stderr lines in utils.execRemoteCmd: " + str(e) })

    #https://stackoverflow.com/questions/3562403/how-can-you-get-the-ssh-return-code-using-paramiko
    exit_code = stdout.channel.recv_exit_status()

    return({ "success": True, "stdout_lines": stdout_lines, "stderr_lines": stderr_lines, "exit_code": exit_code })

#If forUser is None then just get all groups on the remote system, otherwise get the groups forUser is in
def getGroupNames(username,hostname,password=None,sshprivkey=None,sshport=22, forUser=None):

    groups = set()
    if forUser is None:
        remoteRes = execRemoteCmd('bash',username,hostname,sshprivkey=sshprivkey,password=password,stdinTxt='getent group | cut -d: -f1',port=sshport)
        if not remoteRes['success']:
            return(remoteRes);
        stdout_lines = remoteRes['stdout_lines']
        for curLine in stdout_lines:
            groups.add(curLine.strip())
    else:
        remoteRes = execRemoteCmd('bash',username,hostname,sshprivkey=sshprivkey,password=password,stdinTxt=f'id -nG {forUser}',port=sshport)
        if not remoteRes['success']:
            return(remoteRes);
        stdout_lines = remoteRes['stdout_lines']
        for curLine in stdout_lines:
            curGroups = curLine.split()
            for curGroup in curGroups:
                groups.add(curGroup)

    return({'success': True, 'groups': groups})

def checkDockerStatus(username,hostname,password=None,sshprivkey=None,sshport=22):

    try:
        #See here: https://raymii.org/s/snippets/Bash_Bits_Check_if_command_is_available.html
        #And here: https://stackoverflow.com/questions/43721513/how-to-check-if-the-docker-engine-and-a-docker-container-are-running
        #And here: https://stackoverflow.com/questions/10112614/how-do-i-create-a-multiline-python-string-with-inline-variables
        #And here: https://stackoverflow.com/questions/18431285/check-if-a-user-is-in-a-group
        bashScriptTxt = '''\
command -v docker >& /dev/null && echo "DOCKER_INSTALLED"
command -v dockerd >& /dev/null && echo "DOCKERD_INSTALLED"
command -v screen >& /dev/null && echo "SCREEN_INSTALLED"
command -v tmux >& /dev/null && echo "TMUX_INSTALLED"
command -v nohup >& /dev/null && echo "NOHUP_INSTALLED"
docker info >& /dev/null && echo "DOCKER_INFO_SUCCESS"
DG=""
if [ -e /var/run/docker.sock ]; then
    DG=$(stat -c "%G" /var/run/docker.sock)
fi
echo "DOCKER_GROUP=$DG"
if [ ! -z "$DG" ]; then
     id -Gn {} | grep -c "\\b$DG\\b" >& /dev/null && echo "USER_IN_DOCKER_GROUP"
fi
'''.format(username)

        resSet = {}
        remoteRes = execRemoteCmd('bash',username,hostname,sshprivkey=sshprivkey,password=password,stdinTxt=bashScriptTxt,port=sshport)
        if not remoteRes['success']:
            return(remoteRes);
        stdout_lines = remoteRes['stdout_lines']
        for curLine in stdout_lines:
            k = curLine.strip()
            v = True
            dgMatch = re.search(r"^DOCKER_GROUP=(.*)$", k,re.M)
            if dgMatch:
                k = 'DOCKER_GROUP'
                v = dgMatch.group(1)
            resSet[k] = v
        return({'success': True, 'resSet': resSet})
    except Exception as e:
        return({'success': False, 'error_msg': str(e)})

#        return({ "success": False, "error_msg": "Error reading result stdout and stderr lines in utils.execRemoteCmd: " + str(e) })
#    return({ "success": True, "stdout_lines": stdout_lines, "stderr_lines": stderr_lines, "exit_code": exit_code })

def startLocker_image(locker_username, server_username,hostname,password=None,sshprivkey=None, sshprivkey_locker=None, sshpubkey_locker=None, locker_homedir=None, sshport=22, pullLatestLockerImage=False, devtest_flag=False):

    startLockerScriptLocation = config.START_SCRIPT_LOCATION
    startLockerScriptName = os.path.basename(startLockerScriptLocation)
    if devtest_flag:
        startLockerScriptLocation = config.START_SCRIPT_LOCATION_DEVTEST
        startLockerScriptName = os.path.basename(startLockerScriptLocation)

    if empty(locker_homedir):
        locker_homedir= "~/"

    if not locker_homedir.endswith("/"):
        locker_homedir = locker_homedir + "/"

    remote_locker_dir = '{hd}.locker/'.format(hd=locker_homedir)
    remote_locker_sshdir = '{hd}.locker/.ssh/'.format(hd=locker_homedir)

    #First create the remote .locker dir
    bashScriptTxt = '''\
mkdir -p {rlsd}
'''.format(rlsd=remote_locker_sshdir)
    remoteRes = execRemoteCmd('bash',server_username,hostname,sshprivkey=sshprivkey,password=password,stdinTxt=bashScriptTxt,port=sshport)
    if not remoteRes['success']:
        return(remoteRes)
    if  'exit_code' in remoteRes and int(remoteRes['exit_code']) != 0:
        remoteRes['success'] = False
        return(remoteRes)

    ssh = sshConnect(server_username,hostname, password=password, sshprivkey=sshprivkey,port=sshport)
    scp = SCPClient(ssh.get_transport())

    scp.put(startLockerScriptLocation, remote_locker_dir, recursive=False)
    with tempfile.NamedTemporaryFile() as sshprivkey_locker_file:
        sshprivkey_locker_file.write(sshprivkey_locker.encode())
        sshprivkey_locker_file.flush()
        scp.put(sshprivkey_locker_file.name, remote_locker_sshdir + 'id_privkey', recursive=False)
    with tempfile.NamedTemporaryFile() as sshpubkey_locker_file:
        sshpubkey_locker_file.write(sshpubkey_locker.encode())
        sshpubkey_locker_file.flush()
        scp.put(sshpubkey_locker_file.name, remote_locker_sshdir + 'id_privkey.pub', recursive=False)
    scp.close()

    pullLatestLockerImageTxt = ""
    if pullLatestLockerImage:
        pullLatestLockerImageTxt = " -p"
    bashScriptTxt = '''\
{rld}{slsn} -u {lu} -d {lhd} -s r{plli}
'''.format(rld=remote_locker_dir,slsn=startLockerScriptName,lu=locker_username,lhd=locker_homedir,plli=pullLatestLockerImageTxt)
    remoteRes = execRemoteCmd('bash',server_username,hostname,sshprivkey=sshprivkey,password=password,stdinTxt=bashScriptTxt,port=sshport)
    if not remoteRes['success']:
        return(remoteRes)
    if  'exit_code' in remoteRes and int(remoteRes['exit_code']) != 0:
        remoteRes['success'] = False
        return(remoteRes)

    return({"success": True})

#returns the remote hostname if Locker is running, otherwise None
def checkIfLockerRunningAlready(username,hostname,password=None,sshprivkey=None,sshport=22):

    open_locker_port = 5000

    while True:
        if isPortOpen(open_locker_port,ip=hostname):
            break
        else:
            open_locker_port = open_locker_port + 1

    return(open_locker_port)

#Turn the /etc/os-release file into a Dict and return it
def getOSInfo(username,hostname,password=None,sshprivkey=None,sshport=22):

    osInfo = {}
    remoteRes = execRemoteCmd('cat /etc/os-release',username,hostname,sshprivkey=sshprivkey,password=password,port=sshport)
    resLines = remoteRes['stdout_lines']

    #See here: https://stackoverflow.com/questions/29030135/module-to-parse-a-simple-syntax-in-python
    for curline in resLines:
        curline = curline.strip()
        if empty(curline):
            continue
        k,v = curline.split("=")
        # .strip('"') will remove if there or else do nothing
        osInfo[k] = v.strip('"')

    return(osInfo)

def installDockerOnServer(username,hostname,sshprivkey=None,password=None, sshport=22):

    osInfo = getOSInfo(username,hostname,sshprivkey=sshprivkey,password=password,sshport=sshport)

    ssh = sshConnect(username,hostname, password=password, sshprivkey=sshprivkey,port=sshport)
    scp = SCPClient(ssh.get_transport())

    install_script = 'install_docker.sh' #Just try to use the script at get.docker.com by default
    if 'ID' in osInfo and osInfo['ID'] == 'amzn' and 'VERSION' in osInfo and osInfo['VERSION'] == '2':
        #install for Amazon Linux 2
        install_script = 'install_docker_amazon_linux2.sh'

    scp.put(install_script, '/tmp/', recursive=False)
    scp.close()

    remoteRes = execRemoteCmd('/tmp/{} {}'.format(install_script,username),username,hostname,sshprivkey=sshprivkey,password=password,port=sshport,get_pty=True)
    if not remoteRes['success']:
        raise Exception("Error running docker install script: " + remoteRes['error_msg'])

def readJsonFile(filePath):

    with open(filePath) as f:
        data = json.load(f)

    return(data)

#For info about filtering to instance types consistent with an AMI, see these links:
#https://stackoverflow.com/questions/48270057/list-all-possible-instance-types-for-a-specific-ami
#https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.describe_images
#https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-images.html
#https://awscli.amazonaws.com/v2/documentation/api/latest/reference/ec2/describe-instance-types.html
#https://aws.amazon.com/blogs/compute/it-just-got-easier-to-discover-and-compare-ec2-instance-types/
def ec2_instance_types(ami_id=None):
    '''Yield all available EC2 instance types'''
    ec2 = boto3.client('ec2')
    describe_args = {}

    if ami_id is not None:
        try:
            describeImagesArgs = {}
            describeImagesArgs['ImageIds'] = [ami_id]
            imageInfo = ec2.describe_images(**describeImagesArgs)
        except Exception as e:
            printTEXT("Error doing describe_images: " + str(e))
            sys.exit()

        virtTypes = []
        architectures = []
        try:
            virtType = imageInfo['Images'][0]['VirtualizationType']
            virtTypes.append(virtType)
            architecture = imageInfo['Images'][0]['Architecture']
            architectures.append(architecture)
        except:
            pass
        describe_args['Filters']=[
            {
                'Name': 'processor-info.supported-architecture',
                'Values': architectures
            },
            {
                'Name': 'supported-virtualization-type',
                'Values': virtTypes
            }
        ]
    while True:
        describe_result = ec2.describe_instance_types(**describe_args)
        yield from [i for i in describe_result['InstanceTypes']]
        if 'NextToken' not in describe_result:
            break
        describe_args['NextToken'] = describe_result['NextToken']

def ec2_instance_type_offerings(availability_zone=None):

    ec2 = boto3.client('ec2')
    describe_args = {}

    describe_args['Filters'] = [{'Name': 'location', 'Values':[availability_zone]}]
    describe_args['LocationType'] = 'availability-zone'

    while True:
        describe_result = ec2.describe_instance_type_offerings(**describe_args)
        yield from [i for i in describe_result['InstanceTypeOfferings']]
        if 'NextToken' not in describe_result:
            break
        describe_args['NextToken'] = describe_result['NextToken']


def getInstanceTypeOfferings(availability_zone=None):

    ret_instance_types = {}

    if availability_zone is None:
        return(ret_instance_types)

    for curInstTypeRec in ec2_instance_type_offerings(availability_zone):
        ret_instance_types[curInstTypeRec['InstanceType']] = True

    return(ret_instance_types)

def getSubnetAvailabilityZone(subnetId=None):

    ec2 = boto3.resource('ec2')
    subnet = ec2.Subnet(subnetId)

    az = subnet.availability_zone

    return(az)

#Got originally here and modified: https://pet2cattle.com/2022/05/python-ondemand-instance-price
def current_ec2_pricing(instance_type = None, region='us-east-1', os='Linux', preinstalled_software='NA', tenancy='Dedicated', byol=False):

  ec2_client = boto3.client(service_name='ec2', region_name=region)

  endpoint_file = resource_filename('botocore', 'data/endpoints.json')

  with open(endpoint_file, 'r') as f:
      endpoint_data = json.load(f)

  region_name = endpoint_data['partitions'][0]['regions'][boto3.session.Session().region_name]['description'].replace('Europe', 'EU')

  filters = [
        {'Type': 'TERM_MATCH', 'Field': 'termType', 'Value': 'OnDemand'},
        {'Type': 'TERM_MATCH', 'Field': 'capacitystatus', 'Value': 'AllocatedHost' if tenancy == 'Host' else 'Used'},
        {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region_name},
        {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': tenancy},
        {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': os},
        {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': preinstalled_software},
        {'Type': 'TERM_MATCH', 'Field': 'licenseModel', 'Value': 'Bring your own license' if byol else 'No License required'},
    ]

  if not empty(instance_type):
      filters.append({'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type})

  pricing_client = boto3.client('pricing', region_name='us-east-1')
  instPricingInfo = {}
  nextToken = None
  while True:
      if nextToken is not None:
          response = pricing_client.get_products(ServiceCode='AmazonEC2', Filters=filters, NextToken=nextToken)
      else:
          response = pricing_client.get_products(ServiceCode='AmazonEC2', Filters=filters)

      for price in response['PriceList']:
          price = json.loads(price)
          instType = price['product']['attributes']['instanceType']

          for on_demand in price['terms']['OnDemand'].values():
              for price_dimensions in on_demand['priceDimensions'].values():
                  roundTo = 2
                  ppu = round(float(price_dimensions['pricePerUnit']['USD']),roundTo)
                  while ppu <= 0.0:
                      roundTo = roundTo + 1
                      ppu = round(float(price_dimensions['pricePerUnit']['USD']),roundTo)
                  instPricingInfo[instType] = { 
                      'region': region, 
                      'os': os, 
                      'preinstalled_software': preinstalled_software, 
                      'tenancy': tenancy, 
                      'byol': byol, 
                      'price': str(ppu),
                      'unit': price_dimensions['unit'],
                      'effective': on_demand['effectiveDate']
                  }
      if 'NextToken' in response:
          nextToken = response['NextToken']
      else:
          nextToken = None
      if empty(nextToken):
          break

  return(instPricingInfo)

def readObjFromJsonCacheFile(cacheFileLoc, timeoutSecs=86400):

    if timeoutSecs < 0:
        return(None)

    try:
        if Path(cacheFileLoc).is_file():
            ti_c = int(os.path.getctime(cacheFileLoc))
            epoch_time = int(time.time())
            if (epoch_time - ti_c) < timeoutSecs:
                with open(cacheFileLoc, encoding='utf-8', errors='ignore') as json_data:
                    cachedObj = json.load(json_data, strict=False)
                    return(cachedObj)
    except Exception as e:
        return(None)

    return(None)

def writeObjToJsonCacheFile(obj,cacheFileLoc):

    if config.JSON_CACHE_TIMEOUT_SECS < 0:
        return

    objJsonTxt = json.dumps(obj)

    cacheFile = open(cacheFileLoc,"w",encoding='utf-8')
    cacheFile.write(objJsonTxt)
    cacheFile.close()

def getInstanceTypes(ami_id=None):

    instanceTypesCacheFileLoc = f'{config.JSON_CACHE_DIR}/.__AWSinstanceTypesInfo.json'
    cacheReadObj = readObjFromJsonCacheFile(instanceTypesCacheFileLoc,timeoutSecs=config.JSON_CACHE_TIMEOUT_SECS)
    if cacheReadObj is not None:
        ret_instance_types = cacheReadObj[0]
        inst_type_name_to_desc = cacheReadObj[1]
        return (ret_instance_types,inst_type_name_to_desc)

    checkCommonInstTypesList = [ 'm4.xlarge', 'm4.2xlarge', 'm4.4xlarge', 'r5a.4xlarge', 'i3.8xlarge', 'm5n.24xlarge' ]
    checkCommonInstTypesSet = set(checkCommonInstTypesList)
    common_instance_types_found = {}
    common_instance_types = []
    other_instance_types = []
    ret_instance_types = []
    inst_type_name_to_desc = {}

    (SubnetId,SecurityGroupId,KeyName) = getNewEc2Params()

    instTypePrices = current_ec2_pricing()
    instTypePricesShared = current_ec2_pricing(tenancy='Shared')
    for curInstType in instTypePricesShared.keys():
        if curInstType not in instTypePrices:
            instTypePrices[curInstType] = instTypePricesShared[curInstType]

    availability_zone = getSubnetAvailabilityZone(SubnetId)
    azInstTypesHash = getInstanceTypeOfferings(availability_zone)

    if ami_id is not None:
        for curInstTypeRec in ec2_instance_types(ami_id):
            instTypeName = curInstTypeRec["InstanceType"]
            if not instTypeName in azInstTypesHash or not azInstTypesHash[instTypeName]:
                continue
            instTypePrice = "NA"
            instTypePriceUnit = "NA"
            if instTypeName in instTypePrices:
                instTypePricingInfo = instTypePrices[instTypeName]
                if instTypePricingInfo is not None and 'price' in instTypePricingInfo:
                    instTypePrice = instTypePricingInfo['price']
                if instTypePricingInfo is not None and 'unit' in instTypePricingInfo:
                    instTypePriceUnit = instTypePricingInfo['unit']
            defVirtCpus = curInstTypeRec["VCpuInfo"]["DefaultVCpus"]
            memory = int(curInstTypeRec["MemoryInfo"]["SizeInMiB"])
            if memory >= 1024:
                memory = int(memory / 1024)
                memoryStr = str(memory) + " GB"
            else:
                memoryStr = str(memory) + " MB"
            instStr = f'{instTypeName} ({defVirtCpus} cores - {memoryStr} RAM, ${instTypePrice}/{instTypePriceUnit})'
            if instTypeName in checkCommonInstTypesSet:
                common_instance_types_found[instTypeName] = instStr
            else:
                other_instance_types.append(instStr)
            inst_type_name_to_desc[instTypeName] = instStr

    other_instance_types = sorted(other_instance_types)
    for curInstType in checkCommonInstTypesList:
        if curInstType in common_instance_types_found:
            common_instance_types.append(common_instance_types_found[curInstType])
    ret_instance_types = ["---Commonly-Used-Types---"] + common_instance_types + ["---Other-Types---"] + other_instance_types

    cacheWriteObj = [ret_instance_types,inst_type_name_to_desc]
    writeObjToJsonCacheFile(cacheWriteObj,instanceTypesCacheFileLoc)

    return(ret_instance_types,inst_type_name_to_desc)

def getLockerInstances(creator=None):

    ec2 = boto3.client('ec2')
    describe_args = {}

    describe_args = [
        {
            'Name':'tag:Application', 
            'Values': ['Locker']
        }
    ]

    if creator is not None:
        describe_args.append({ 'Name':'tag:Creator','Values': [creator] })

    allLockerInstances = []

    while True:
        describe_result = ec2.describe_instances(Filters=describe_args)
        curReservations = describe_result['Reservations']
        for curRes in curReservations:
            curInst = curRes["Instances"]
            allLockerInstances = allLockerInstances + curInst
        if 'NextToken' not in describe_result:
            break
        describe_args['NextToken'] = describe_result['NextToken']

    return(allLockerInstances)

#Will start, stop, or terminate a running EC2, but only if it's 'Creator' tag is equal to the SiteMinder user accessing
#the web page
def SMUserEc2Action(instanceId=None, aws_region='us-east-1', action=None):

    http_smuser = os.environ.get(config.SERVER_USER_ENV_VAR_NAME)
    if http_smuser is None:
        return(0,f"Error: env var {config.SERVER_USER_ENV_VAR_NAME} is undefined, you must be a known user to execute this function.")

    if instanceId is None or action is None:
        return(0,"Error: you must provide values for 'instanceId' and 'action'.")

    try:
        ec2 = boto3.resource('ec2')
        instance = ec2.Instance(instanceId)
        if instance.state['Name'] == 'terminated':
            if action == 'terminate':
                return(1,f'The instance with id {instanceId} is in state terminated, therefore nothing to do.')
            else:
                return(0,f'The instance with id {instanceId} is in state terminated, therefore cannot perform action {action}.')
        for tags in instance.tags:
            tagKey = tags["Key"]
            tagVal = tags["Value"]
            if tagKey == 'Creator':
                # Could be multiple creators, so split the
                # comma-separated string into a list
                tagVal = [x.strip() for x in tagVal.split(",")]
                if http_smuser in tagVal or http_smuser in config.ADMIN_USERNAME:
                    if action == 'terminate':
                        instance.terminate()
                        return(1,f'Success: Instance with id {instanceId} was terminated.')
                    elif action == 'stop':
                        instance.stop()
                        return(1,f'Success: Instance with id {instanceId} was stopped.')
                    elif action == 'start':
                        instance.start()
                        return(1,f'Success: Instance with id {instanceId} was started.')
                    else:
                        return(0,f'Error: unknown action {action} to perform on EC2 with id {instanceId}.')
                    break
                else:
                    return(0,"Error: You cannot " + action + " the instance because you are not it's creator (or an admin).")
                    break
    except Exception as e:
        return(0,"Error in SMUserEc2Action: " + str(e))

    return(0,"Unknown Error in SMUserEc2Action, return should not be from here.")

def getNewEc2Params():
    return(config.SUBNET_ID,config.SECURITY_GROUP_ID,config.KEYNAME)

def getAMIIDFromName(ami_name, aws_region='us-east-1'):

    ami_id = None

    try:

#        ACCESS_KEY = ""
#        SECRET_KEY = ""
#        client = boto3.client('ec2', region_name=aws_region,aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY)
        #If don't explicitly pass in access key and secret key, will try to find in /usr/share/httpd/.aws/credentials
        client = boto3.client('ec2', region_name=aws_region)

        response = client.describe_images(
            Filters=[{ 'Name': 'name', 'Values': [ami_name] }]
        )
        ami_id = response['Images'][0]['ImageId']
    except Exception as e:
        printTEXT("Error: " + str(e))
        sys.exit()

    return(ami_id)

def startEc2(aws_region='us-east-1',root_disk_size=100,ec2_instance_type='t2.micro',ami_id='ami-0915bcb5fa77e4892',creator=None, desc=None, sshprivkey=None):

    (SubnetId,SecurityGroupId,KeyName) = getNewEc2Params()

    ec2_instance_type_desc = ec2_instance_type
    splitVals = ec2_instance_type.split(" ",1)
    ec2_instance_type = splitVals[0]

    owner = config.ADMIN_USERNAME
    if creator is None:
        creator = owner

    # Turn owner & creater into comma-separated
    # lists for AWS.
    # Note these are split back into python lists
    # in downstream functions for parsing.
    stringify = lambda x: ",".join(x if isinstance(x, list) else [x])
    owner = stringify(owner)
    creator = stringify(creator)

    today = time.ctime()

    if desc is None:
        desc = ""

    try:
        root_disk_size = int(root_disk_size)

#        ACCESS_KEY = ""
#        SECRET_KEY = ""
#        client = boto3.client('ec2', region_name=aws_region,aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY)
        #If don't explicitly pass in access key and secret key, will try to find in /usr/share/httpd/.aws/credentials
        client = boto3.client('ec2', region_name=aws_region)

        tagsArr = [
            {
                'Key': 'Name',
                'Value': 'Locker Server for user {} created {}'.format(creator,today)
            },
            {
                'Key': 'Description',
                'Value': desc
            },
            {
                'Key': 'InstanceTypeDescription',
                'Value': ec2_instance_type_desc
            },
            {
                'Key': 'Owner',
                'Value': owner
            },
            {
                'Key': 'Creator',
                'Value': creator
            }
        ]

        for curExtraTag in config.EXTRA_TAGS:
            tagKey = curExtraTag[0]
            tagValue = curExtraTag[1]
            newTag = { 'Key': tagKey, 'Value': tagValue }
            tagsArr.append(newTag)

        response = client.run_instances(
            BlockDeviceMappings=[
                {
                    'DeviceName': '/dev/xvda',
                    'Ebs': {
                        
                        'DeleteOnTermination': True,
                        'VolumeSize': root_disk_size,
                        'VolumeType': 'gp3'
                    },
                },
            ],
            ImageId=ami_id,

            SubnetId=SubnetId,
            KeyName=KeyName,
            InstanceType=ec2_instance_type,
            MaxCount=1,
            MinCount=1,
            Monitoring={
                'Enabled': False
            },
            SecurityGroupIds=[
                SecurityGroupId
            ],
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': tagsArr
                }
            ]
        )

        session = boto3.Session()

        instanceid = response['Instances'][0]['InstanceId']

        ec2 = session.resource('ec2')
        instance = ec2.Instance(instanceid)
        instance.wait_until_running()

        new_ec2_username = config.AMI_USER
        new_ec2_ip = response['Instances'][0]['PrivateIpAddress']
        while (True):
            remoteRes = execRemoteCmd('hostname -f',new_ec2_username,new_ec2_ip,sshprivkey=sshprivkey)
            if not remoteRes['success'] or not remoteRes['exit_code'] == 0:
                time.sleep(1.0)
                continue
            else:
                break

        remoteHostname = remoteRes['stdout_lines'][0].strip()
        ec2.create_tags(Resources=[instanceid], Tags=[{'Key':'Hostname', 'Value':remoteHostname}])

    except Exception as e:
        printTEXT("Error: " + str(e))
        sys.exit()

    return(response,remoteHostname)

def sendMailSMUser(fromEmail,subj,msgHtml):

    http_smuser = os.environ.get(config.SERVER_USER_ENV_VAR_NAME)
    toList = config.ADMIN_EMAIL_ALERTS

    if http_smuser is not None:
        http_smuser_email = queryLdapForUid(http_smuser)
        if http_smuser_email is not None:
            toList = [http_smuser_email] + toList

    sendMail(fromEmail,toList,subj,msgHtml)
    return

#See here: https://stackoverflow.com/questions/882712/sending-html-email-using-python
#And here: https://stackoverflow.com/questions/6270782/how-to-send-an-email-with-python
def sendMail(fromEmail,toList,subj,msgHtml):
    """
    Send an HTML email.
    """

    mailhost=config.MAILHOST
    # Create message container - the correct MIME type is multipart/alternative.
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subj
    msg['From'] = fromEmail
    msg['To'] = ",".join(toList)
    # Record the MIME type
    html_part = MIMEText(msgHtml, 'html')

    # Attach parts into message container.
    # According to RFC 2046, the last part of a multipart message, in this case
    # the HTML message, is best and preferred.
    msg.attach(html_part)
    # Send the message via local SMTP server.
    mail = smtplib.SMTP(mailhost)

    mail.ehlo()
    mail.starttls()

    mail.sendmail(fromEmail, ",".join(toList), msg.as_string())
    mail.quit()

def sendMailWithTextAttachment(fromEmail,toList,subj,msgText,msgAttachTxt,attachFileName="attach.txt"):
    """
    Send an HTML email.
    """

    mailhost=config.MAILHOST
    # Create message container - the correct MIME type is multipart/alternative.
    msg = MIMEMultipart("alternative",None,[MIMEText(msgText,'html')])
    msg['Subject'] = subj
    msg['From'] = fromEmail
    msg['To'] = ",".join(toList)

    part = MIMEBase('text', "plain")
    part.set_payload(msgAttachTxt)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="' + attachFileName + '"')
    msg.attach(part)

    # Send the message via local SMTP server.
    mail = smtplib.SMTP(mailhost)

    mail.ehlo()
    mail.starttls()

    mail.sendmail(fromEmail, ",".join(toList), msg.as_string())
    mail.quit()

def ldapConnect():
    """
    Connect to an Ldap server.
    """

    ldap_url = config.LDAP_URL

    con = ldap.initialize(ldap_url)
    con.simple_bind_s()
    return con

def queryLdapForUid(uid,con=None):
    """
    Execute an Ldap query to get email address for a given uid
    """

    if con is None:
        con = ldapConnect()

    base_dn = config.LDAP_BASE_SEARCH
    filter_str = f"(|({config.LDAP_FILTER_UID_NAME}={uid}*))"
#    attrs = ['cn', 'uid', 'mail', 'bmsentaccountstatus']
    attrs = [config.LDAP_MAIL_ATTR]

    try:
        results = con.search_ext_s(base_dn, ldap.SCOPE_SUBTREE, filter_str, attrs)
    except ldap.LDAPError as error:
        raise Exception("Error querying LDAP: " + str(error))

    ldapRes = [[result[1]['mail'][0].decode('utf-8')]
               for result in results]

    if len(ldapRes) > 0:
        http_smuser_email = ldapRes[0][0]
        return(http_smuser_email)

    return None

def SSORedirectUrl(url):

    location = config.redirect_url + '?url=' + urllib.parse.quote(url)
    print("Status: 303 See other")
    print("Location: " + location)
    print()

def getCGIScriptFullUrl():
    fullUrl = os.environ.get('REQUEST_SCHEME') + "://" + os.environ.get('SERVER_NAME') + ":" + os.environ.get('SERVER_PORT') + os.environ.get('REQUEST_URI')
    return(fullUrl)

#same as above function but doesn't include query string
def getCGIScript():
    domain = os.environ.get('REQUEST_SCHEME') + "://" + os.environ.get('SERVER_NAME') + ":" + os.environ.get('SERVER_PORT') + os.environ.get('SCRIPT_NAME')
    return(domain)


#Got various sqlite3 functions from here: https://www.sqlitetutorial.net/sqlite-python/
def create_connection(db_file):
    """ create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Error as e:
        print(e)

    return conn

def create_table(conn, create_table_sql):
    """ create a table from the create_table_sql statement
    :param conn: Connection object
    :param create_table_sql: a CREATE TABLE statement
    :return:
    """
    try:
        c = conn.cursor()
        c.execute(create_table_sql)
    except Error as e:
        print(e)

def insert_validated_cookie(conn, session, cookie_vals):

    ttl = cookie_vals['TTL']
    epochsecs = cookie_vals['epochsecs']
    full_cookie_vals = json.dumps(cookie_vals)

    sql = ''' INSERT INTO VALIDATED_COOKIES(SESSION_TOKEN,TTL,EPOCHSECS,ALL_COOKIE_INFO_JSON)
              VALUES(?,?,?,?) '''
    cur = conn.cursor()
    cur.execute(sql, (session, ttl, epochsecs, full_cookie_vals,))
    conn.commit()

def remove_expired_cookies(conn):

    #Remove expired cookies from VALIDATED_COOKIES
    cur = conn.cursor()
    cur.execute("SELECT SESSION_TOKEN,TTL,EPOCHSECS FROM VALIDATED_COOKIES")
    res_rows = cur.fetchall()

    currentEpochSecs = calendar.timegm(time.gmtime())
    delCookies = {}
    for cur_row in res_rows:
        curSession = cur_row[0]
        initTtlSecs = int(cur_row[1])
        initEpochSecs = int(cur_row[2])
        secsDiff = currentEpochSecs - initEpochSecs
        remainingTtlSecs = initTtlSecs - secsDiff
        if remainingTtlSecs <= 0:
            delCookies[curSession] = True

    for curSession, assocVal in delCookies.items():
        cur.execute("DELETE FROM VALIDATED_COOKIES WHERE SESSION_TOKEN = ?", (curSession,))
    conn.commit()

def get_session(conn,session):

    cur = conn.cursor()
    cur.execute("SELECT (ALL_COOKIE_INFO_JSON) FROM VALIDATED_COOKIES WHERE SESSION_TOKEN = ?",(session,))
    res_rows = cur.fetchall()

    if len(res_rows) <= 0:
        return(None)
    else:
        sessionInfoJsonTxt = res_rows[0][0]
        cookieInfo = json.loads(sessionInfoJsonTxt)
        return(cookieInfo)

def getSSOUser():

    validatedCookies = {}

    cookies = Cookie.SimpleCookie()
    cookie_string = os.environ.get('HTTP_COOKIE')
    if empty(cookie_string):
        cookie_string = ""
    cookies.load(cookie_string)

    if not config.SSO_SESSION_COOKIE_NAME in cookies:
        return(None)

    validatedCookiesConn = create_connection("/tmp/.__ssosession.db")
    sqlTableTxt = "CREATE TABLE IF NOT EXISTS VALIDATED_COOKIES (SESSION_TOKEN text PRIMARY KEY, TTL int, EPOCHSECS int, ALL_COOKIE_INFO_JSON text)"
    create_table(validatedCookiesConn, sqlTableTxt)

    remove_expired_cookies(validatedCookiesConn)

    ssoSession = str(cookies[config.SSO_SESSION_COOKIE_NAME].value)

    validatedCookieVals = get_session(validatedCookiesConn,ssoSession)
    if validatedCookieVals is not None:
        return(validatedCookieVals)

    validateResp = requests.get(config.validate_url,cookies={ config.SSO_SESSION_COOKIE_NAME: ssoSession })
    respLines = validateResp.text.splitlines()

    if respLines[0] != 'Success':
        return(None)

    respValsHash = {}
    for curLine in respLines:
        matches = re.search('^([^\=]+)=(.+)$', curLine)
        if matches:
            respValsHash[matches.group(1)] = matches.group(2)

    respValsHash['epochsecs'] = calendar.timegm(time.gmtime())    
    insert_validated_cookie(validatedCookiesConn, ssoSession, respValsHash)

    return(respValsHash)

def remove_nonprintable_characters(s):
    # Remove ansi characters
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    cleaned_str = ansi_escape.sub('', s)

    # Remove windows-style line endings (CRLF)
    return cleaned_str.replace('\r\n', '\n')
