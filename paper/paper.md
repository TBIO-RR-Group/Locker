---
title: 'Locker: A User-Friendly Tool to Run and Manage Interactive Docker Containers Supporting Reproducible Research'
tags:
  - Python
  - Docker
  - reproducible research
  - containers
  - data science
  - RStudio
  - Jupyter
authors:
  - name: Andrew Smith
    orcid: 0009-0009-6515-1671
    corresponding: true
    affiliation: 1
  - name: Eric Davis
    orcid: 0000-0003-4051-3217
    affiliation: 2
  - name: Adnan Derti
    orcid: 0000-0002-8453-2244
    affiliation: 2
  - name: Scott D. Chasalow
    orcid: 0000-0003-1513-0249
    affiliation: 1
affiliations:
  - name: Informatics & Predictive Sciences, Translational Bioinformatics, Bristol Myers Squibb, Lawrence Township, NJ, USA
    index: 1
  - name: Vindhya Data Science, Morrisville, NC, USA
    index: 2
date: 3 December 2024
bibliography: paper.bib
---

# Summary

Reproducible computational analysis requires careful tracking and retention of all relevant artifacts, including code, input data, results, run logs, and files that define the computational environment. A Docker image is an excellent method of encapsulating an environment that can be both run as a container to perform analyses and easily archived for future use and reproduction of the analyses if necessary. However, many users would benefit from a simple, intuitive way to develop code and run analyses using Docker images, with a mechanism that includes strong safeguards against accidental loss of work. We have created and publicly released "Locker" to meet this need. Locker provides a web-based graphical user interface (GUI) for users to easily start, use, and stop containers with common data science IDEs such as RStudio and Jupyter. Locker can be used on a local computer or on a remote instance. To facilitate Locker's use on remote machines, we have included "Locker Services", an intuitive, web-based portal that can create and manage Amazon Elastic Compute Cloud (EC2) instances pre-configured for running Locker. Locker and Locker Services provide a flexible, easy-to-use interface for performing reproducible computational analyses locally or in the cloud.

# Statement of need

At Bristol Myers Squibb ("BMS") we have developed a comprehensive process and suite of supporting software to facilitate reproducibility of computational analyses [@sandve2013]. BMS bioinformatics scientists develop script-based analyses, principally using R and Python, following a formal but flexible process to ensure the analyses can be fully reproduced in the future. Such reproduction may be required by regulatory authority audits, by journal publishers, or simply for ensuring complete internal documentation of how analysis results were produced. This involves carefully tracking, versioning, and archiving all important artifacts of the computational analysis, such as specific releases of Git code repositories (repos), input data and output files, run log files, and full details of the computational environment used to execute the analysis.

Versioning and archiving the full computational environment are crucial for reproducibility, and we do this using Docker images. We develop custom Docker images for our analysts containing many user-requested packages (R and Python modules, operating system packages, etc.), tools useful for interactive code development and data analysis such as RStudio, Jupyter, JupyterLab, and VS Code, and the Secure Shell Daemon (sshd) for secure terminal access. We periodically create updated versions of these images, and we archive all images for future on-demand reproduction of computational analyses. However, our analysts needed an easy way to use these Docker images for code development, preferably via an intuitive user interface (UI) that avoids a need for complicated Docker command-line executions. We built Locker to fill this need. It is designed to be reliable and lean, to guard against unintentional loss of work due to interruptions in the network or user error, and to be convenient, helping users manage multiple projects and multiple compute resources. We are releasing Locker open source in hopes that others will find it useful for managing data science projects in a reproducible research environment. Potential alternatives to Locker include Portainer (portainer.io) and Domino (domino.ai). However, Locker is simpler and leaner than such alternatives and is free for personal or commercial use (Apache License 2.0).

# Implementation

"Locker" consists of two main applications: Locker and Locker Services. Locker is a web-based GUI for managing Docker images and interactive containers. Locker Services is a web-based GUI for creating and managing EC2 instances, preconfigured to run Locker. These two applications are defined in a single Dockerfile, which can be built and run with GNU Make. Shell scripts and Windows batch files are included for starting Locker on platforms without GNU Make and enable Locker to run on all major operating systems such as Linux, MacOS, and Windows. The public GitHub repository contains detailed instructions for running Locker or setting up a new Locker Services application.

## Locker

Locker is a Flask web application that the user accesses from a web browser. Using the Docker SDK for Python [@dockerpy2014], it executes, on behalf of the user, Docker operations on the host machine where Locker is running. With Locker the user can pull Locker-compatible images from an associated Docker registry and start interactive application containers that run either RStudio, Jupyter, or JupyterLab, and optionally VS Code. SSH access also is provided. Using web links from a grid page view listing all containers, the user can easily manage containers (Stop, Restart, or Terminate) and access applications running in the containers. Figure 1 shows a screenshot of the Containers tab of the Locker UI.

Locker works directly with the open-source Docker Registry or Amazon Elastic Container Registry (ECR). A separate, related tool we have released allows you to proxy ECR without requiring end-user authentication to Amazon Web Services (AWS) [@smith2023a]. To execute Docker actions, the Locker container is started using the "sibling Docker containers" technique, i.e., bind mounting in /var/run/docker.sock [@colangelo2019]. A user can choose to start Locker in "local" or "remote" mode. "Local" mode provides no authentication and access control, and only localhost access is provided. This is appropriate for running on a computer to which only the owner has access, such as a personal workstation. "Remote" mode provides access over a network but authenticates users via an associated single sign-on (SSO) solution so that only the user who started a container can access it. SSO solutions such as CA SiteMinder can be used. We also have released a separate simple SSO tool based on JSON web tokens that can be used with Locker [@smith2023b]. This SSO tool does require authenticating users against a Lightweight Directory Access Protocol (LDAP) server. Application containers started by Locker can optionally use the "sibling Docker containers" technique. This approach allows a user to start a new Docker container from within an existing container and thus use functionality available only as a separate Docker image.

Locker supports network drive mounting (e.g., mounting user network home directories or other network file systems) inside application containers. Network drive addresses and mount points in containers can be configured in the Locker configuration file, but users can choose to enable or disable network drive mounting when starting a container. Inside Locker application containers, users assume a generic identity (e.g., the "ubuntu" user or other user account created inside the image). Thus, network drives are mounted using Filesystem in Userspace (FUSE)-based Secure Shell Filesystem (SSHFS) and user access to such drives is controlled via SSH keys. This allows users to access their organizational files as their true organizational identities (e.g., their corporate LDAP usernames). A Python utility, 'smount', is also included in our release and can be used to perform easy and robust mounting using SSHFS, with a corresponding unmount when a container is shut down.

As an additional convenience, Locker bind mounts the host root directory ('/' on Mac or Linux, 'C:' on Windows) into application containers at mount point "/host_root". Users also can specify a host location (bind mounted into the application container at "/repos") where cloned repos may be stored. Read and write access to such host or network drives from within an application container serves two critical purposes. First, it provides convenient access to a user's host or network drive content. Second, the user should use these as safe, persistent locations for storing code (repo clones) and output files; anything stored directly in a container (e.g., in /tmp) is ephemeral and will be gone once the container is terminated.

Locker also supports use cases where containers operate fully offline, by providing easy support for caching network drive content into directories on the host machine. These host directories can then be bind mounted into application containers (in lieu of network mounting) at container startup. Thus, a user first could prepare to work offline while on network by pulling a Docker image and caching necessary files (repo clones and required subdirectories of their network drives). They then could work offline using this cached content.

Docker images need to be created specifically for use with Locker. Among other things, the main applications - RStudio, Jupyter, JupyterLab, and VS Code - plus openssh (for sshd) must be installed. We provide a simple minimal Dockerfile, based on the rocker/rstudio image, that can be used to create Locker-compatible images. Users wishing to use Locker for themselves can use the included Dockerfile as-is or as a base for new images. Locker also optionally supports the use of images where some of the content is installed on a network drive, such as Amazon Elastic File System (EFS), that is mounted at container startup. This architecture can result in slower execution in the container due to the need to fetch over a possibly slow network but is useful for cases where very large self-contained images might not fit easily on the disk of a host machine. We also released separately a build process and supporting scripts for easily creating larger-scale Locker-compatible images [@bruccoleri2023]. This process directly supports both self-contained images and images with network-installed content.

## Locker Services

Locker Services is a Python CGI application that runs under Apache2 with Transport Layer Security (TLS), so certificates are required. It also works with an associated SSO solution like CA SiteMinder or the simple SSO tool referenced above. It is a web UI for starting Locker on existing remote servers (e.g., a persistent cloud workstation) and for starting new EC2 servers running Locker in the AWS cloud. Locker Services also provides a portal for managing all such EC2 servers. Via this portal a user can Stop, Restart, or Terminate servers, and access them via SSH or a web link to Locker. Regular users can manage only servers they have started. Locker Services administrators, however, can manage all servers started by a Locker Services instance. Locker Services also provides links for download of the Locker start scripts (which are configurable and dynamically generated upon startup of Locker Services). Figure 2 shows a screenshot of the Locker Services Locker Server Portal tab.

Both Locker and Locker Services can be customized using a Yaml configuration file (config.yml) to set values for things such as Docker registry domain and Locker image name. Details of all the configurable settings are given as comments in template configuration files included in the Locker release. A user could then build their own custom Locker image using their modified configuration files. Full installation and configuration details and user documentation for Locker and Locker Services are available at the Locker GitHub repository.

# Figures

![The containers view of Locker, showing 2 containers, 1 stopped and 1 running.\label{fig:locker}](figure_1a.pdf)

![The Locker Server Portal view of Locker Services, showing EC2 servers started by a user, some stopped and some running.\label{fig:locker-services}](figure_1b.pdf)

# Acknowledgements

We acknowledge contributions from all members of the Bristol Myers Squibb Translational Bioinformatics team who provided feedback and testing during the development of Locker.

# References
