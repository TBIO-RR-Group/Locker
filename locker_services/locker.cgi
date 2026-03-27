#!/usr/bin/env python

import os
import sys
import io
import time
import tempfile
import cgi
import cgitb; cgitb.enable() # Optional; for debugging only
from jinja2 import Template, Environment, FileSystemLoader
import utils
import boto3
import json
from collections import ChainMap
from Config import Config

# Load locker configuration
locker_config = Config("/config.yml")

arguments = cgi.FieldStorage()

#argumentsDict = {}
#try:
#   for key in arguments.keys():
#      val = arguments[key].value
#      try:
#         val = val.decode('utf-8')
#      except:
#         pass
#      try:
#         key = key.decode('utf-8')
#      except:
#         pass
#      argumentsDict[key] = val
#   utils.printTEXT(json.dumps(argumentsDict,indent=2))
#except Exception as e:
#   utils.printTEXT("Error: " + str(e))
##utils.printTEXT(str(arguments.keys()))
#sys.exit()

a = 'ec2_portal'
devtest = 'False'
stage = 'form'
password = None
server_username = None
locker_username = None
instance_hostname = None
hostname = None
install_location = None
locker_homedir = None
aws_region = None
instance_id = None
instance_ip = None
pull_latest_locker_image = False
ec2_instance_type = None
ec2_desc = None
admin_view = locker_config.ADMIN_VIEW_DEFAULT
version_view = "false"

#http_smuser = os.environ.get(locker_config.SERVER_USER_ENV_VAR_NAME)

SSOUserInfo = utils.getSSOUser()
if SSOUserInfo is not None:
   http_smuser = SSOUserInfo['User']
   os.environ[locker_config.SERVER_USER_ENV_VAR_NAME] = http_smuser
else:
   fullUrl = utils.getCGIScriptFullUrl()
   utils.SSORedirectUrl(fullUrl)
   sys.exit()

if 'a' in arguments:
   a = arguments['a'].value
if 'devtest' in arguments:
   devtest = arguments['devtest'].value
   if not utils.empty(devtest) and devtest == 'True':
      devtest = 'True'
   else:
      devtest = 'False'
if 'stage' in arguments:
   stage = arguments['stage'].value
if 'config_sshprivkey' in arguments:
   sshprivkey = arguments['config_sshprivkey'].value
   sshprivkey = utils.remove_nonprintable_characters(sshprivkey)
   if utils.empty(sshprivkey):
      sshprivkey = None
if 'password' in arguments:
   password = arguments['password'].value
if 'config_sshpubkey' in arguments:
   sshpubkey = arguments['config_sshpubkey'].value
   if utils.empty(sshpubkey):
      sshpubkey = None
if 'config_server_username' in arguments:
   server_username = arguments['config_server_username'].value
if 'config_locker_username' in arguments:
   locker_username = arguments['config_locker_username'].value
if 'config_hostip' in arguments:
   hostname = arguments['config_hostip'].value
if 'config_install_location' in arguments:
   install_location = arguments['config_install_location'].value
if 'config_pull_latest_locker_image' in arguments:
   pull_latest_locker_image = arguments['config_pull_latest_locker_image'].value
   if pull_latest_locker_image == 'on':
      pull_latest_locker_image = True
   else:
      pull_latest_locker_image = False
if 'config_locker_homedir' in arguments:
   locker_homedir = arguments['config_locker_homedir'].value
if 'config_aws_region' in arguments:
   aws_region = arguments['config_aws_region'].value
if 'config_ec2_instance_type' in arguments:
   ec2_instance_type = arguments['config_ec2_instance_type'].value
if 'config_ec2_desc' in arguments:
   ec2_desc = arguments['config_ec2_desc'].value
if 'config_root_disk_size' in arguments:
   root_disk_size = arguments['config_root_disk_size'].value
if 'config_sshprivkey_locker' in arguments:
   sshprivkey_locker = arguments['config_sshprivkey_locker'].value
   if utils.empty(sshprivkey_locker):
      sshprivkey_locker = None
if 'config_sshpubkey_locker' in arguments:
   sshpubkey_locker = arguments['config_sshpubkey_locker'].value
   if utils.empty(sshpubkey_locker):
      sshpubkey_locker = None
if 'instance_id' in arguments:
   instance_id = arguments['instance_id'].value
if 'instance_ip' in arguments:
   instance_ip = arguments['instance_ip'].value
if 'instance_hostname' in arguments:
   instance_hostname = arguments['instance_hostname'].value
edit_ec2_instance_type = None
edit_ec2_desc = None
edit_root_disk_size = None
if 'edit_ec2_instance_type' in arguments:
   edit_ec2_instance_type = arguments['edit_ec2_instance_type'].value
if 'edit_ec2_desc' in arguments:
   edit_ec2_desc = arguments['edit_ec2_desc'].value
if 'edit_root_disk_size' in arguments:
   edit_root_disk_size = arguments['edit_root_disk_size'].value
instance_type_justification = None
if 'instance_type_justification' in arguments:
   instance_type_justification = arguments['instance_type_justification'].value
   if utils.empty(instance_type_justification):
      instance_type_justification = None
instance_type_price = None
if 'instance_type_price' in arguments:
   try:
      instance_type_price = float(arguments['instance_type_price'].value)
   except (ValueError, TypeError):
      instance_type_price = None
install_docker_flag = False
if 'install_docker_cb' in arguments and arguments['install_docker_cb'].value == 'True':
   install_docker_flag = True
mount_network_homedir_flag = False
if 'mount_network_homedir_cb' in arguments and arguments['mount_network_homedir_cb'].value == 'True':
   mount_network_homedir_flag = True
if 'admin_view' in arguments:
   admin_view = arguments['admin_view'].value
if 'version_view' in arguments:
   version_view = arguments['version_view'].value

file_loader = FileSystemLoader('/locker_services/templates')
env = Environment(loader=file_loader)
env.trim_blocks = True
env.lstrip_blocks = True
env.rstrip_blocks = True

config = {}
template = None

#ami_id='ami-0915bcb5fa77e4892' #the AMI (Amazon Linux 2) that will be used to start EC2s
#ami_id = 'ami-058da02a01b8d3be6' #Amazon Linux 2 AMI with NVIDIA TESLA GPU Driver (need to subscripe to use this).
#ami_id = 'ami-03f6cae090226269f' #Amazon Linux 2 AMI with NVIDIA GPU Drivers installed (created by Eric Sison, see 7/29/22 email)
#ami_id = 'ami-010ec3b6aeebfc21a' #Amazon Linux 2 AMI with NVIDIA GPU Drivers installed, can be used on p2/p3/g5, should also work on g4. Also usable on non-GPU instances. Created by Eric Sison 8/3/22
#From Eric Sison: AMI ID's change frequently due to patching or bug fixes, search by AMI Name to find the latest AMI id; AMI Name: Amazon Linux 2 AG GPU latest
ami_name = locker_config.AMI_NAME
ami_id = utils.getAMIIDFromName(ami_name, aws_region='us-east-1')

def validate_justification_if_needed(price, justification, config_btn=''):
   """If instance type price exceeds threshold, require justification."""
   threshold = getattr(locker_config, 'LARGE_INSTANCE_COST_THRESHOLD', 2.0)
   if price is not None and price > threshold and (justification is None or justification.strip() == ''):
      cgi_exit(
         f"<b>Error</b>: Instance type costs ${price}/hr (threshold: ${threshold}/hr). "
         f"A justification is required. Please go back and provide one.",
         config_btn=config_btn
      )

def send_justification_email(smuser, instance_id, instance_type_str, justification, context='New'):
   """Send email about large instance justification to the submitting user and admins."""
   try:
      html = (
         f"<b>Large Instance Justification ({context})</b><br><br>"
         f"<b>User:</b> {smuser}<br>"
         f"<b>Instance ID:</b> {instance_id}<br>"
         f"<b>Instance Type:</b> {instance_type_str}<br>"
         f"<b>Justification:</b><br>{justification.strip()}"
      )
      utils.sendMailSMUser(locker_config.ADMIN_EMAIL_FROM,
                           f'Large Instance Justification ({context}) - {instance_id}', html)
   except:
      pass

def new_ec2_locker_func():

   config = {}
   template = None

   global server_username
   global hostname
   global install_docker_flag
   global locker_homedir
   global sshprivkey_locker
   global sshpubkey_locker

   if stage == 'exec':
      (config,template) = new_ec2_func(exec_exit=False)
      startedEc2Msg = config['startedMsg']
      ec2_instanceid = config['instanceid']
      ec2_ip = config['ip']
      ec2_remoteHostname = config['remoteHostname']
      server_username = config['instanceuser']
      hostname = config['remoteHostname']
      install_docker_flag = True
      (config,template) = start_docker_func()
      
      # Copy SSL certificate files to EC2 instance
      copy_ssl_certs_res = utils.copy_ssl_certificates_to_ec2(server_username, hostname)
      if not copy_ssl_certs_res['success']:
         cgi_exit("<b>Error</b>: Failed copying SSL certificates to EC2 instance: " + copy_ssl_certs_res['error_msg'], config_btn="new_ec2_locker_btn")
      
      locker_homedir = ""
      sshprivkey_locker = sshprivkey
      sshpubkey_locker = sshpubkey
      (config,template) = start_locker_image_func(exec_exit=False)
      locker_remote_hostname = config['remote_hostname']
      lockerCgi = utils.getCGIScript()
      startedMsg = (
         "<b>Your Locker server is ready!</b>"
         "<br><br>"
         "<b>Server:</b> {} ({})"
         "<br>"
         "<b>SSH:</b> {}@{}"
         "<br><br>"
         "<a href='https://{}' target='_blank'>Open Locker</a>"
         " | "
         "<a href='{}?a=ec2_portal'>Server Portal</a>"
         " | "
         "<a href='{}?a=terminate_ec2_instance&instance_id={}&instance_ip={}'>Terminate Server</a>"
      ).format(ec2_remoteHostname, ec2_instanceid, locker_config.AMI_USER, ec2_ip,
               locker_remote_hostname, lockerCgi, lockerCgi, ec2_instanceid, ec2_ip)
      startedFullMsg = startedMsg + "<br><br>An email with these details has been sent to you."
      try:
         utils.sendMailSMUser(locker_config.ADMIN_EMAIL_FROM,'New EC2 started and Locker started on it',startedMsg)
      except:
         pass

      cgi_exit(startedFullMsg,config_btn='new_ec2_locker_btn')
   else:
      awsRegionsHash = utils.readJsonFile('aws_regions.json')
      ec2InstanceTypesArr,instTypeNameToDesc,instTypePrices = utils.getInstanceTypes(ami_id=ami_id)
      config = { 'aws_regions': awsRegionsHash, 'ec2_instance_types': ec2InstanceTypesArr, 'username': utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME), 'devtest': devtest,
                 'mount_network_homedir': locker_config.MOUNT_NETWORK_HOMEDIR_FLAG, 'container_user': locker_config.CONTAINER_USER,
                 'instance_type_prices': instTypePrices, 'large_instance_cost_threshold': getattr(locker_config, 'LARGE_INSTANCE_COST_THRESHOLD', 2.0) }
      template = env.get_template('new_ec2_locker.html')

   return(config, template)

def start_docker_func():

   config = {}
   template = None

   if stage == 'exec':
      if utils.empty(server_username) or utils.empty(hostname) or (utils.empty(password) and utils.empty(sshprivkey)):
         cgi_exit("<b>Error</b>: You must provide a hostname or IP address, username, and password or SSH private key.",config_btn='start_docker_btn')
      resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
      if not resSet['success']:
         cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_docker_btn')
      else:
         resSet = resSet['resSet']
      msg = "Docker is installed and available."
      if not 'DOCKER_INSTALLED' in resSet and not 'DOCKERD_INSTALLED' in resSet and not 'DOCKER_INFO_SUCCESS' in resSet:
         msg = "Docker has not been installed. You can try to install it by re-doing this form with the 'Install and Start Docker' checkbox checked."
      if ('DOCKER_INSTALLED' in resSet or 'DOCKERD_INSTALLED' in resSet) and not 'DOCKER_INFO_SUCCESS' in resSet:
          msg = "Docker seems to be partially or fully installed already, but is not running or not accessible to the user.<br>The current installation should be fixed instead of a new install.<br>See above bullets for details of the issues."

      if install_docker_flag:
         if 'DOCKER_INFO_SUCCESS' in resSet:
            msg = "Docker is already installed and available."
         elif not 'DOCKER_INSTALLED' in resSet and not 'DOCKERD_INSTALLED' in resSet and not 'DOCKER_INFO_SUCCESS' in resSet:
            try:
               utils.installDockerOnServer(server_username,hostname,sshprivkey=sshprivkey,password=password)
            except Exception as e:
               cgi_exit("<b>Error</b>: error installing docker on server: " + str(e),config_btn='start_docker_btn')
            #Recheck Docker status to make sure it is running and available
            resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
            if not resSet['success']:
               cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_docker_btn')
            else:
               resSet = resSet['resSet']
            if 'DOCKER_INFO_SUCCESS' in resSet:
               msg = "Docker was successfully installed and is available."
            else:
               msg = "There was an error installing Docker. See above bullets for details of the issues."
         elif 'DOCKER_INSTALLED' in resSet and 'DOCKERD_INSTALLED' in resSet and not 'DOCKER_INFO_SUCCESS' in resSet and not 'USER_IN_DOCKER_GROUP' in resSet:
            #Try to add the user to the docker group and see if that fixes
            remoteRes = utils.execRemoteSudoCmd('usermod -aG docker {}'.format(server_username), hostname, server_username, sshprivkey=sshprivkey, password=password)
            if not remoteRes['success']:
               cgi_exit("<b>Error</b>: Failed adding user to the docker group at remote server: " + remoteRes['error_msg'],config_btn="start_docker_btn")
            testLines = remoteRes['stdout_lines']
            #Check docker status again and see if okay now
            resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
            if not resSet['success']:
               cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_docker_btn')
            else:
               resSet = resSet['resSet']
            if 'DOCKER_INSTALLED' in resSet and 'DOCKERD_INSTALLED' in resSet and 'USER_IN_DOCKER_GROUP' in resSet:
               if 'DOCKER_INFO_SUCCESS' in resSet:
                  msg = "Docker had been installed, but access failed due to the user not being in the 'docker' group; the user was added to the 'docker' group and now docker is running and available"
               else:
                  #Try to start/restart docker and see if that fixes things
                  remoteRes = utils.execRemoteSudoCmd('service docker restart', hostname, server_username, sshprivkey=sshprivkey, password=password)
                  if not remoteRes['success']:
                     cgi_exit("<b>Error</b>: Failed starting/restarting Docker at remote server: " + remoteRes['error_msg'],config_btn="start_docker_btn")
                  resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
                  if not resSet['success']:
                     cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_docker_btn')
                  else:
                     resSet = resSet['resSet']
                  if 'DOCKER_INSTALLED' in resSet and 'DOCKERD_INSTALLED' in resSet and 'USER_IN_DOCKER_GROUP' in resSet and 'DOCKER_INFO_SUCCESS' in resSet:
                     msg = "Docker had been installed but was not accessible. The user was added to the 'docker' group and docker was started/restarted and docker is now running and available."
                  else:
                     msg = "Docker had been installed but was not accessible. The user was added to the 'docker' group and docker was started/restarted, however unfortuntately that did not fix the issues and Docker is still inaccessible."


      config = { 'username': server_username, 'hostname': hostname, 'docker_status': resSet, 'msg': msg }
      template = env.get_template('docker_status.html')
   else:
      template = env.get_template('start_docker.html')
      config['username'] = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)

   return(config, template)

def start_locker_image_func(exec_exit=True):

   config = {}
   template = None

   lockerPort = '5000'

   if stage == 'exec':
      if utils.empty(server_username) or utils.empty(locker_username) or utils.empty(hostname) or utils.empty(sshprivkey_locker) or utils.empty(sshpubkey_locker) or (utils.empty(password) and utils.empty(sshprivkey)):
         cgi_exit("<b>Error</b>: You must provide a hostname (or IP address), server username, password (or SSH private key), Locker username, and a Locker private/public keypair.",config_btn='start_locker_image_btn')
      remoteRes = utils.execRemoteCmd('hostname -f',server_username,hostname,sshprivkey=sshprivkey,password=password)
      if not remoteRes['success']:
         cgi_exit("<b>Error</b>: Failed executing hostname -f at remote server: " + remoteRes['error_msg'],config_btn="start_locker_image_btn")
      resLines = remoteRes['stdout_lines']
      remote_hostname = resLines[0].strip()
      lockerPort = utils.checkIfLockerRunningAlready(server_username,hostname,password=password,sshprivkey=sshprivkey)
      resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
      if not resSet['success']:
         cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_locker_image_btn')
      else:
         resSet = resSet['resSet']

      #If docker/dockerd is already installed but just misconfigured (not running or user not in Docker group), try to fix; but won't try to fully install Docker here
      if 'DOCKER_INSTALLED' in resSet and 'DOCKERD_INSTALLED' in resSet:
         if not 'DOCKER_INFO_SUCCESS' in resSet:
            #Try to start/restart docker and see if that fixes things
            remoteRes = utils.execRemoteSudoCmd('service docker restart', hostname, server_username, sshprivkey=sshprivkey, password=password)
            if not remoteRes['success']:
               cgi_exit("<b>Error</b>: Failed starting/restarting Docker at remote server: " + remoteRes['error_msg'],config_btn="start_locker_image_btn")
            resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
            if not resSet['success']:
               cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_locker_image_btn')
            else:
               resSet = resSet['resSet']

         if not 'USER_IN_DOCKER_GROUP' in resSet:
            #Try to add the user to the group of /var/run/docker.sockand see if that fixes
            remoteDockerGroup = resSet['DOCKER_GROUP']
            if utils.empty(remoteDockerGroup):
               cgi_exit("<b>Error</b>: Cannot determine group of remote docker /var/run/docker.sock file",config_btn='start_locker_image_btn')
            if remoteDockerGroup != 'root':
               remoteRes = utils.execRemoteSudoCmd(f'usermod -aG {remoteDockerGroup} {server_username}', hostname, server_username, sshprivkey=sshprivkey, password=password)
               if not remoteRes['success']:
                  cgi_exit(f"<b>Error</b>: Failed adding user to the docker /var/run/docker.sock group {remoteDockerGroup} at remote server: " + remoteRes['error_msg'],config_btn="start_locker_image_btn")
            resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
            if not resSet['success']:
               cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_locker_image_btn')
            else:
               resSet = resSet['resSet']
            #If user still not in the group of /var/run/docker.sock, change its group to some newly created group and add user to that group:
            if not 'USER_IN_DOCKER_GROUP' in resSet:
               remoteGroups = utils.getGroupNames(server_username,hostname,sshprivkey=sshprivkey,password=password)
               #remoteGroupsForUser = utils.getGroupNames(server_username,hostname,sshprivkey=sshprivkey,password=password,forUser='smitha26')
               setDockerGroup = 'dockergroup'
               ct = 0
               while setDockerGroup in groups:
                  setDockerGroup = 'dockergroup' + str(ct)
                  ct = ct + 1
               remoteRes = utils.execRemoteSudoCmd(f'groupadd {setDockerGroup}; usermod -aG {setDockerGroup} {server_username}; chgrp {setDockerGroup} /var/run/docker.sock', hostname, server_username, sshprivkey=sshprivkey, password=password)
            if not remoteRes['success']:
               cgi_exit("<b>Error</b>: Failed resetting and adding user to the docker /var/run/docker.sock group at remote server: " + remoteRes['error_msg'],config_btn="start_locker_image_btn")

         resSet = utils.checkDockerStatus(server_username,hostname,sshprivkey=sshprivkey,password=password)
         if not resSet['success']:
            cgi_exit("<b>Error</b>: " + resSet['error_msg'],config_btn='start_locker_image_btn')
         else:
            resSet = resSet['resSet']

      if not ('DOCKER_INSTALLED' in resSet and 'DOCKERD_INSTALLED' in resSet and 'DOCKER_INFO_SUCCESS' in resSet):
         cgi_exit("<b>Error</b>: Docker is not installed, not running, or not accessible on the server.<br>Please make sure that Docker is running and available before starting Locker.<br>You can <a href='locker.cgi?a=start_docker'>check Docker status</a> for more details.",config_btn='start_locker_image_btn')
      startLocker_image_res = utils.startLocker_image(locker_username, server_username,hostname,password=password,sshprivkey=sshprivkey, sshprivkey_locker=sshprivkey_locker, sshpubkey_locker=sshpubkey_locker, locker_homedir=locker_homedir, pullLatestLockerImage=pull_latest_locker_image, devtest_flag=True if devtest=='True' else False)

      if not startLocker_image_res['success']:
         json_formatted_res_str = json.dumps(startLocker_image_res, indent=2)
         cgi_exit("<b>Error</b>: failed starting Locker on remote server:<br><pre>" + json_formatted_res_str + "</pre>",config_btn='start_locker_image_btn')

      startedLockerMsg = (
         "<b>Locker is ready!</b>"
         "<br><br>"
         "Access your Locker at {}"
         "<br><br>"
         "<a href='https://{}' target='_blank'>Open Locker</a>"
         " | "
         "<a href='{}?a=ec2_portal'>Server Portal</a>"
      ).format(remote_hostname, remote_hostname, utils.getCGIScript())
      startedLockerFullMsg = startedLockerMsg + "<br><br>An email with these details has been sent to you."

      if exec_exit:
         try:
            utils.sendMailSMUser(locker_config.ADMIN_EMAIL_FROM,'Locker started on server',startedLockerMsg)
         except Exception as e:
            pass
         cgi_exit(startedLockerFullMsg,config_btn='start_locker_image_btn')
      else:
         config = { 'startedLockerMsg': startedLockerMsg, 'startedLockerFullMsg': startedLockerFullMsg, 'remote_hostname': remote_hostname }
         return(config,None)
   else:
      template = env.get_template('start_locker_image.html')
      config['username'] = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)
      config['devtest'] = devtest
      config['container_user'] = locker_config.CONTAINER_USER
      config['ami_user'] = locker_config.AMI_USER

   return(config, template)

def new_ec2_func(exec_exit=True):

   config = {}
   template = None
   smuser = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)

   if stage == 'exec':

      # Check server limit
      if smuser not in locker_config.ADMIN_USERNAME:
         existing_instances = utils.getLockerInstances(creator=smuser)
         non_terminated = [i for i in existing_instances if i['State']['Name'] != 'terminated']
         max_servers = locker_config.MAX_SERVERS_PER_USER
         if len(non_terminated) >= max_servers:
            cgi_exit(
               f"<b>Error</b>: You already have {len(non_terminated)} server(s) (limit is {max_servers}). "
               f"Please <a href='locker.cgi?a=ec2_portal'>terminate existing servers</a> before creating a new one.",
               config_btn='new_ec2_btn'
            )

      validate_justification_if_needed(instance_type_price, instance_type_justification, config_btn='new_ec2_btn')

      try:

         #See here: https://stackoverflow.com/questions/23929235/multi-line-string-with-extra-space-preserved-indentation
         bashScriptTxt = '''\
cat >> ~/.ssh/authorized_keys <<- EOM
{}
EOM
'''.format(sshpubkey.rstrip())
         if locker_config.MOUNT_NETWORK_HOMEDIR_FLAG and mount_network_homedir_flag:
            hostPath = locker_config.NETWORK_HOMEDIR_HOSTPATH.replace("__USER__",smuser)
            mountPath = locker_config.NETWORK_HOMEDIR_MOUNTPATH.replace("__USER__",smuser)
#            bashScriptTxt2 = '''\
#cat > ~/.ssh/id_rsa_{} <<- EOM
#{}
#EOM
#
#chmod 0600 ~/.ssh/id_rsa_{}
#sudo umount -l /home
#sudo mkdir -p {}
#sudo chown ec2-user:ec2-user {}
#sudo sshfs {}@{}:{} {} -o allow_other -o IdentityFile=~/.ssh/id_rsa_{}
#'''.format(smuser,sshprivkey.rstrip(),smuser,mountPath,mountPath,smuser,locker_config.NETWORK_HOMEDIR_HOST,hostPath,mountPath,smuser)

            bashScriptTxt2 = '''\
cat > ~/.ssh/id_privkey_{} <<- EOM
{}
EOM

chmod 0600 ~/.ssh/id_privkey_{}
sudo mkdir -p {}
sudo chown {}:{} {}
sudo bash -c 'echo "{}@{}:{} {} fuse.sshfs x-systemd.automount,_netdev,StrictHostKeyChecking=no,IdentityFile={}/.ssh/id_privkey_{},allow_other,reconnect 0 0" >> /etc/fstab'
sudo mount -a
'''.format(smuser,sshprivkey.rstrip(),smuser,mountPath,locker_config.AMI_USER, locker_config.AMI_USER, mountPath,smuser,locker_config.NETWORK_HOMEDIR_HOST,hostPath,mountPath,locker_config.AMI_USER_HOMEDIR, smuser)

         sshprivkey_docker_env_admin_key = utils.slurpFile(locker_config.KEYLOC)
         resp,remoteHostname = utils.startEc2(aws_region=aws_region,root_disk_size=root_disk_size,ec2_instance_type=ec2_instance_type,ami_id=ami_id, creator=smuser,desc=ec2_desc, sshprivkey=sshprivkey_docker_env_admin_key)
         ip = resp['Instances'][0]['PrivateIpAddress']
         username = locker_config.AMI_USER
         instanceid = resp['Instances'][0]['InstanceId']

         if instance_type_justification is not None:
            try:
               utils.updateEc2Tags(instanceid, [{'Key': 'InstanceTypeJustification', 'Value': instance_type_justification.strip()}])
            except:
               pass
            send_justification_email(smuser, instanceid, ec2_instance_type, instance_type_justification, context='New')

         remoteRes = utils.execRemoteCmd('bash',username,ip,sshprivkey=sshprivkey_docker_env_admin_key,stdinTxt=bashScriptTxt)
         lockerCgi = utils.getCGIScript()
         if not remoteRes['success']:
            cgi_exit("<b>Error</b>: Failed adding pub key to authorized_keys at remote server: " + remoteRes['error_msg'],config_btn="new_ec2_btn")
         if mount_network_homedir_flag:
            remoteRes = utils.execRemoteCmd('bash',username,ip,sshprivkey=sshprivkey_docker_env_admin_key,stdinTxt=bashScriptTxt2)
            if not remoteRes['success']:
               cgi_exit("<b>Error</b>: Failed adding user's priv key at remote server: " + remoteRes['error_msg'],config_btn="new_ec2_btn")
         startedMsg = (
            "<b>EC2 instance launched!</b>"
            "<br><br>"
            "<b>Server:</b> {} ({})"
            "<br>"
            "<b>SSH:</b> {}@{}"
            "<br><br>"
            "<a href='{}?a=ec2_portal'>Server Portal</a>"
            " | "
            "<a href='{}?a=terminate_ec2_instance&instance_id={}&instance_ip={}'>Terminate Server</a>"
         ).format(remoteHostname, instanceid, locker_config.AMI_USER, ip, lockerCgi, lockerCgi, instanceid, ip)
         startedFullMsg = startedMsg + "<br><br>An email with these details has been sent to you."

         if exec_exit:
            try:
               utils.sendMailSMUser(locker_config.ADMIN_EMAIL_FROM,'New EC2 started for Locker',startedMsg)
            except:
               pass
            cgi_exit(startedFullMsg,config_btn='new_ec2_btn')
         else:
            config = { 'startedMsg': startedMsg, 'startedFullMsg': startedFullMsg, 'instanceid': instanceid, 'ip': ip, 'remoteHostname': remoteHostname, 'instanceuser': locker_config.AMI_USER }
            return(config,None)
      except Exception as e:
         utils.printTEXT("Error starting ec2: " + str(e))
         sys.exit()
   else:
      awsRegionsHash = utils.readJsonFile('aws_regions.json')
#      ec2InstanceTypesArr = utils.readJsonFile('ec2_instance_types.json')
      ec2InstanceTypesArr,instTypeNameToDesc,instTypePrices = utils.getInstanceTypes(ami_id=ami_id)
      config = { 'aws_regions': awsRegionsHash, 'ec2_instance_types': ec2InstanceTypesArr, 'username': smuser, 'mount_network_homedir': locker_config.MOUNT_NETWORK_HOMEDIR_FLAG,
                 'instance_type_prices': instTypePrices, 'large_instance_cost_threshold': getattr(locker_config, 'LARGE_INSTANCE_COST_THRESHOLD', 2.0) }
      template = env.get_template('new_ec2.html')

   return(config, template)

def AWSTagsToHash(instances):

   for instance in instances:
      if 'Tags' in instance:
         instTags = instance['Tags']
         tagsHash = {curTag['Key']:curTag['Value'] for curTag in instTags}
         instance['TagsHash'] = tagsHash

def ec2_portal_func(exec_exit=True):

   config = {}
   template = None
   smuser = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)

   try:
      # admin_view is default 'true'
      if smuser in locker_config.ADMIN_USERNAME and admin_view == 'true':
         inst = utils.getLockerInstances()
      else:
         inst = utils.getLockerInstances(creator=smuser)
      ec2InstanceTypesArr,instTypeNameToDesc,_ = utils.getInstanceTypes(ami_id=ami_id)
      AWSTagsToHash(inst)
      if version_view == 'true':
         for currInst in inst:
            currInst['LockerVersion'] = 'unknown'
            currInst['LockerImageId'] = 'unknown'
            currInst['UpdateAvailable'] = 'false'
            if currInst['State']['Name'] == 'running' and 'PrivateIpAddress' in currInst:
               locker_info = utils.get_locker_info_from_ec2(currInst['PrivateIpAddress'])
               currInst['LockerVersion'] = locker_info.get('locker_version','unknown')
               currInst['LockerImageId'] = locker_info.get('image_id','unknown')
               currInst['UpdateAvailable'] = locker_info.get('update_available','false')
      #See here for how to avoid errors printing datetime in json: https://stackoverflow.com/questions/11875770/how-to-overcome-datetime-datetime-not-json-serializable
      #utils.printTEXT(json.dumps(inst,indent=2,default=str))
      #sys.exit()
      config = {
         "inst": inst,
         "inst_type_name_to_desc": instTypeNameToDesc,
         "username": smuser,
         'config_btn': 'ec2_portal_btn',
         'ami_user': locker_config.AMI_USER, 
         'ip_to_hostname': locker_config.IP_TO_HOSTNAME_JS, 
         'admins': locker_config.ADMIN_USERNAME, # to show admin box
         'admin_view': admin_view, # to set checked/unchecked state
         'version_view': version_view
      }
      template = env.get_template('ec2_portal.html')
   except Exception as e:
      utils.printTEXT("Error in ec2_portal_func: " + str(e))
      sys.exit()

   return(config, template)

def terminate_ec2_instance_func():

   config = {}
   template = None
   retCode = None
   msg = None

   if stage == 'exec':
      if not utils.empty(aws_region):
         retCode, msg = utils.SMUserEc2Action(instanceId=instance_id,aws_region=aws_region,action='terminate')
      else:
         retCode, msg = utils.SMUserEc2Action(instanceId=instance_id,action='terminate')
      if retCode == 1:
         cgi_exit(f"Successfully terminated instance {instance_id} having ip address {instance_ip}")
      else:
         cgi_exit(f"Error terminating instance {instance_id} having ip address {instance_ip} : " + msg)
   else:
      template = env.get_template('res_mesg.html')
      config['msg'] = f'<p>Please click <a onclick="if (confirm(\'Are you sure you want to terminate the instance?\')) {{showSpinner(); window.location=\'locker.cgi?a=terminate_ec2_instance&stage=exec&instance_id={instance_id}&instance_ip={instance_ip}\';}}" href="#">here</a> to terminate instance {instance_id} having ip address {instance_ip}.</p>'

   return(config, template)

def stop_ec2_instance_func():

   config = {}
   template = None
   retCode = None
   msg = None
   stopContErrMsg = ""

   if stage == 'exec':
      sshprivkey_docker_env_admin_key = utils.slurpFile(locker_config.KEYLOC)
      username = locker_config.AMI_USER
      stopAllRunningDockerContCmd = "if [ ! -z $(docker ps -q) ]; then docker stop $(docker ps -q); fi"
      remoteRes = utils.execRemoteCmd(stopAllRunningDockerContCmd,username,instance_ip,sshprivkey=sshprivkey_docker_env_admin_key)
      if not remoteRes['success'] or not remoteRes['exit_code'] == 0:
         stopContErrMsg = "\n\nError first stopping running docker containers on remote host in stop_ec2_instance_func"

      if not utils.empty(aws_region):
         retCode, msg = utils.SMUserEc2Action(instanceId=instance_id,aws_region=aws_region,action='stop')
      else:
         retCode, msg = utils.SMUserEc2Action(instanceId=instance_id,action='stop')
      if retCode == 1:
         cgi_exit(f"Successfully stopped instance {instance_id} having ip address {instance_ip}" + stopContErrMsg)
      else:
         cgi_exit(f"Error stopping instance {instance_id} having ip address {instance_ip} : " + msg + stopContErrMsg)
   else:
      template = env.get_template('res_mesg.html')
      config['msg'] = f'<p>Please click <a onclick="if (confirm(\'Are you sure you want to stop the instance?\')) {{showSpinner(); window.location=\'locker.cgi?a=stop_ec2_instance&stage=exec&instance_id={instance_id}&instance_ip={instance_ip}\';}}" href="#">here</a> to stop instance {instance_id} having ip address {instance_ip}.</p>'

   return(config, template)

def start_ec2_instance_func():

   config = {}
   template = None
   retCode = None
   msg = None
   startContErrMsg = ""

   if stage == 'exec':
      if not utils.empty(aws_region):
         retCode, msg = utils.SMUserEc2Action(instanceId=instance_id,aws_region=aws_region,action='start')
      else:
         retCode, msg = utils.SMUserEc2Action(instanceId=instance_id,action='start')

      if retCode != 1:
         cgi_exit(f"Error starting instance {instance_id} having ip address {instance_ip} : " + msg)

      #Wait for the EC2 to be running by continually executing a command until it succeeds:
      sshprivkey_docker_env_admin_key = utils.slurpFile(locker_config.KEYLOC)
      username = locker_config.AMI_USER
      while (True):
         remoteRes = utils.execRemoteCmd('hostname -f',username,instance_ip,sshprivkey=sshprivkey_docker_env_admin_key)
         if not remoteRes['success'] or not remoteRes['exit_code'] == 0:
            time.sleep(1.0)
            continue
         else:
            break

      startLockerContCmd = 'if [ ! -z $(docker ps -a -q -f "name=^locker_\w+_\d+$" | head -1) ]; then docker start $(docker ps -a -q -f "name=^locker_\w+_\d+$" | head -1); fi'
      remoteRes = utils.execRemoteCmd(startLockerContCmd,username,instance_ip,sshprivkey=sshprivkey_docker_env_admin_key)
      if not remoteRes['success'] or not remoteRes['exit_code'] == 0:
         cgi_exit(f"Successfully started instance {instance_id} having ip address {instance_ip}, but error starting Locker docker containers on remote host: " + remoteRes['error_msg'])
      else:
         cgi_exit(f"Successfully started instance {instance_id} having ip address {instance_ip}")
   else:
      template = env.get_template('res_mesg.html')
      config['msg'] = f'<p>Please click <a onclick="if (confirm(\'Are you sure you want to start the instance?\')) {{showSpinner(); window.location=\'locker.cgi?a=start_ec2_instance&stage=exec&instance_id={instance_id}&instance_ip={instance_ip}\';}}" href="#">here</a> to start instance {instance_id} having ip address {instance_ip}.</p>'

   return(config, template)

def update_locker_func():
   """
   Connects to an EC2 instance, pulls the latest Locker image,
   and restarts the Locker container.
   """
   config = {}
   template = None
   smuser = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)

   if stage == 'exec':
      if utils.empty(instance_ip) or utils.empty(instance_hostname):
         cgi_exit("<b>Error</b>: You must provide an IP address and hostname.",config_btn='update_locker_btn')
      sshprivkey_docker_env_admin_key = utils.slurpFile(locker_config.KEYLOC)
      locker_info = utils.get_locker_info_from_ec2(instance_ip)
      if locker_info.get('update_available','false') != 'true':
         cgi_exit(f"No update available for Locker on instance {instance_id} having ip address {instance_ip}.",config_btn='update_locker_btn')
      update_res = utils.update_locker_on_ec2(
         locker_username = smuser,
         server_username = locker_config.AMI_USER,
         current_container_id = locker_info.get('container_id',''),
         hostname = instance_ip,
         sshprivkey = sshprivkey_docker_env_admin_key
      )
      if not update_res['success']:
         json_formatted_res_str = json.dumps(update_res, indent=2)
         cgi_exit("<b>Error</b>: failed updating Locker on remote server:<br><pre>" + json_formatted_res_str + "</pre>",config_btn='update_locker_btn')
      startedLockerMsg = f"<b>Success</b>: Locker was updated on the remote server, access it <a href='https://{instance_hostname}'>here</a>."
      cgi_exit(startedLockerMsg,config_btn='update_locker_btn')

   template = env.get_template('res_mesg.html')
   config['msg'] = f"<p>Please click <a onclick=\"if (confirm('Are you sure you want to update Locker on the instance?')) {{showSpinner(); window.location='locker.cgi?a=update_locker&stage=exec&instance_hostname={instance_hostname}&instance_ip={instance_ip}';}}\" href=\"#\">here</a> to update Locker on {instance_hostname} server with ip address {instance_ip}.</p>"
   return(config, template)

def edit_ec2_instance_func():

   config = {}
   template = None
   smuser = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)

   if utils.empty(instance_id):
      cgi_exit("<b>Error</b>: No instance_id provided.", config_btn='ec2_portal_btn')

   details = utils.getEc2InstanceDetails(instance_id)
   if not details['success']:
      cgi_exit("<b>Error</b>: " + details['error_msg'], config_btn='ec2_portal_btn')

   # Authorization check
   creator_tag = details['tags'].get('Creator', '')
   creators = [x.strip() for x in creator_tag.split(",")]
   if smuser not in creators and smuser not in locker_config.ADMIN_USERNAME:
      cgi_exit("<b>Error</b>: You are not authorized to edit this instance because you are not its creator (or an admin).", config_btn='ec2_portal_btn')

   if stage == 'exec':
      changes_made = []
      current_desc = details['tags'].get('Description', '')
      current_instance_type = details['instance_type']
      current_root_disk_size = details['root_volume_size']

      # Update description if changed
      if edit_ec2_desc is not None and edit_ec2_desc != current_desc:
         res = utils.updateEc2Tags(instance_id, [{'Key': 'Description', 'Value': edit_ec2_desc}])
         if not res['success']:
            cgi_exit("<b>Error</b> updating description: " + res['error_msg'], config_btn='ec2_portal_btn')
         changes_made.append("Description updated")

      # Update instance type if changed
      if edit_ec2_instance_type is not None and not edit_ec2_instance_type.startswith(current_instance_type + ' ') and edit_ec2_instance_type != current_instance_type:
         validate_justification_if_needed(instance_type_price, instance_type_justification, config_btn='ec2_portal_btn')
         if details['state'] == 'running':
            cgi_exit("<b>Error</b>: Instance must be stopped before changing instance type. Please <a href='locker.cgi?a=stop_ec2_instance&instance_id={}&instance_ip='>stop the instance</a> first.".format(instance_id), config_btn='ec2_portal_btn')
         # Extract the instance type name (e.g. "m5.xlarge" from "m5.xlarge (4 cores - 16 GB RAM, $0.2/Hrs)")
         new_type_name = edit_ec2_instance_type.split(' ')[0] if ' ' in edit_ec2_instance_type else edit_ec2_instance_type
         res = utils.modifyEc2InstanceType(instance_id, new_type_name)
         if not res['success']:
            cgi_exit("<b>Error</b> changing instance type: " + res['error_msg'], config_btn='ec2_portal_btn')
         # Update the InstanceTypeDescription tag
         utils.updateEc2Tags(instance_id, [{'Key': 'InstanceTypeDescription', 'Value': edit_ec2_instance_type}])
         if instance_type_justification is not None:
            utils.updateEc2Tags(instance_id, [{'Key': 'InstanceTypeJustification', 'Value': instance_type_justification.strip()}])
            send_justification_email(smuser, instance_id, edit_ec2_instance_type, instance_type_justification, context='Edit')
         changes_made.append("Instance type changed to " + new_type_name)

      # Update storage if changed
      if edit_root_disk_size is not None and current_root_disk_size is not None:
         new_size = int(edit_root_disk_size)
         if new_size < current_root_disk_size:
            cgi_exit("<b>Error</b>: Root disk size can only be increased, not decreased. Current size is {} GB.".format(current_root_disk_size), config_btn='ec2_portal_btn')
         if new_size > current_root_disk_size:
            res = utils.modifyEc2VolumeSize(details['root_volume_id'], new_size)
            if not res['success']:
               error_msg = res['error_msg']
               if 'IncorrectModificationState' in error_msg or 'OPTIMIZING' in error_msg:
                  friendly = (
                     "<b>Error modifying volume size</b>"
                     "<br><br>"
                     "This volume was recently resized and is still being optimized by AWS. "
                     "AWS enforces a cooldown period (typically 6 hours) after each volume "
                     "modification, during which no further size changes can be made."
                     "<br><br>"
                     "Please wait and try again later."
                     "<br><br>"
                     "<a style='cursor:pointer;' onclick='toggleShowHide(\"vol_error_details\");'>"
                     "Show full error details <span id='vol_error_details_clickon'>&nbsp;+</span></a>"
                     "<span style='display:none;' id='vol_error_details'>"
                     "<br><br>" + error_msg +
                     "</span>"
                  )
                  cgi_exit(friendly, config_btn='ec2_portal_btn')
               cgi_exit("<b>Error</b> modifying volume size: " + error_msg, config_btn='ec2_portal_btn')
            changes_made.append("Root disk size changed to {} GB".format(new_size))

      if changes_made:
         msg = "<b>Success</b>: " + "; ".join(changes_made) + ".<br><a href='locker.cgi?a=ec2_portal'>Back to Server Portal</a>"
      else:
         msg = "No changes were made.<br><a href='locker.cgi?a=ec2_portal'>Back to Server Portal</a>"
      cgi_exit(msg, config_btn='ec2_portal_btn')
   else:
      ec2InstanceTypesArr,instTypeNameToDesc,instTypePrices = utils.getInstanceTypes(ami_id=ami_id)
      config = {
         'instance_id': instance_id,
         'instance_ip': details['tags'].get('Hostname', ''),
         'instance_state': details['state'],
         'current_instance_type': details['instance_type'],
         'current_desc': details['tags'].get('Description', ''),
         'current_root_disk_size': details['root_volume_size'] or 100,
         'ec2_instance_types': ec2InstanceTypesArr,
         'username': smuser,
         'instance_type_prices': instTypePrices,
         'large_instance_cost_threshold': getattr(locker_config, 'LARGE_INSTANCE_COST_THRESHOLD', 2.0)
      }
      template = env.get_template('edit_ec2.html')

   return(config, template)

def cgi_exit(errormsg,config_btn=''):
   template = env.get_template('res_mesg.html')
   config['msg'] = errormsg
   config['config_btn'] = config_btn
   # Check server limit for tab display (non-admin users only)
   smuser_limit_check = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)
   if smuser_limit_check not in locker_config.ADMIN_USERNAME:
      existing_instances = utils.getLockerInstances(creator=smuser_limit_check)
      non_terminated = [i for i in existing_instances if i['State']['Name'] != 'terminated']
      max_servers = locker_config.MAX_SERVERS_PER_USER
      if len(non_terminated) >= max_servers:
         config['at_server_limit'] = True
         config['server_limit_msg'] = (
            f"You have {len(non_terminated)} server(s) (limit is {max_servers}). "
            f"Please <a href='locker.cgi?a=ec2_portal'>terminate existing servers</a> before creating a new one."
         )
   output = template.render(config=config)
   utils.printHTML(output)
   sys.exit()

#try:
#   test_res = utils.getInstanceTypeOfferings()
#except Exception as e:
#   cgi_exit("Error: " + str(e))
#cgi_exit(str(test_res));

if a == 'new_ec2_locker':
   (config,template) = new_ec2_locker_func()
elif a == 'start_locker_image':
   (config,template) = start_locker_image_func()
elif a == 'start_docker':
   (config,template) = start_docker_func()
elif a == 'new_ec2':
   (config,template) = new_ec2_func()
elif a == 'ec2_portal':
   (config,template) = ec2_portal_func()
elif a == 'terminate_ec2_instance':
   (config,template) = terminate_ec2_instance_func()
elif a == 'stop_ec2_instance':
   (config,template) = stop_ec2_instance_func()
elif a == 'start_ec2_instance':
   (config,template) = start_ec2_instance_func()
elif a == 'update_locker':
   (config,template) = update_locker_func()
elif a == 'edit_ec2_instance':
   (config,template) = edit_ec2_instance_func()


if config is not None and template is not None:
   # Check server limit for tab display (non-admin users only)
   smuser_limit_check = utils.getEnvVar(locker_config.SERVER_USER_ENV_VAR_NAME)
   if smuser_limit_check not in locker_config.ADMIN_USERNAME:
      existing_instances = utils.getLockerInstances(creator=smuser_limit_check)
      non_terminated = [i for i in existing_instances if i['State']['Name'] != 'terminated']
      max_servers = locker_config.MAX_SERVERS_PER_USER
      if len(non_terminated) >= max_servers:
         config['at_server_limit'] = True
         config['server_limit_msg'] = (
            f"You have {len(non_terminated)} server(s) (limit is {max_servers}). "
            f"Please <a href='locker.cgi?a=ec2_portal'>terminate existing servers</a> before creating a new one."
         )

if template is not None:
   output = template.render(config=config)
   utils.printHTML(output)

###SCRAPS###


#print("hello, world")
#arguments = cgi.FieldStorage()
#for i in arguments.keys():
# print(i + '=' + arguments[i].value)
#
#template = Template('Hello {{ name }}')
#print(template.render(name='Andrew Smith(HPW)'))
#
#persons = [
#    {'name': 'Andrej', 'age': 34}, 
#    {'name': 'Mark', 'age': 17}, 
#    {'name': 'Thomas', 'age': 44}, 
#    {'name': 'Lucy', 'age': 14}, 
#    {'name': 'Robert', 'age': 23}, 
#    {'name': 'Dragomir', 'age': 54}, 
#]
#
#template = env.get_template('showpersons.txt')
#output = template.render(persons=persons)
#    pkey = None
#    if sshprivkey is not None:
#        try:
#            pkey_file = io.StringIO(initial_value=sshprivkey)
#            pkey = paramiko.RSAKey.from_private_key(pkey_file)
#        except Exception as e:
#            printTEXT("Error: " + str(e))
#            sys.exit()
#    ssh = paramiko.SSHClient()
#    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
#    ssh.connect(hostname = hostname, port = port, username = username, pkey = pkey, password = password)
#    VpcId='vpc-7647ae11',
