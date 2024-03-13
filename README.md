# Locker - Flask app to run interactive Docker images

Locker is a Flask app to enable users to easily run specially created interactive Docker images on their local computer or remote server. Locker runs as a Docker container (it uses the "sibling docker containers" idea to start new containers for the special interactive Docker images). You first need to create the Locker Docker image by configuring values for your local setting and then building the image. You can then run Locker directly on a computer --- there are [Makefile](Makefile) targets to run it on Mac/Linux/Win and you can also execute other Makefile targets to generate Locker startup scripts that you can execute to start Locker. You can also setup and use Locker Services, which allows you to have EC2 instances with Locker running on them started for you by filling out web forms. There are Makefile targets for doing all the important actions with Locker and Locker Services, and see below for more details. Note that the code and artifacts for Locker are in the [locker](locker) subdirectory, and the code and artifacts for Locker services are in the [locker_services](locker_services) subdirectory. The below sections discuss setting up and using Locker and Locker Services; you can also see the [PDF documentation](Locker_Overview_Documentation.pdf) for more details (e.g. screenshots of Locker and Locker Services UI, etc.)

## Quickstart Locker

Follow these instructions to quickly get Locker up and running on your local computer. Note that these instructions are for running Locker directly on a computer, not using Locker Services to start EC2 instances with Locker running on them.

### Mac/linux

For Mac and Linux, you can use the Makefile to build the Locker image and start Locker. First, ensure you have the [dependencies](#dependencies) installed. Then, follow the steps below in the terminal.

1. Clone this repository to your computer and move into the Locker directory:

    ```bash
    git clone https://github.com/TBIO-RR-Group/Locker.git
    cd Locker
    ```

2. Build the Locker Simple Image to use with Locker:

    ```bash
    docker build --platform linux/amd64 -t rr:LockerSimpleImage -f "./locker/LockerSimpleImage/Dockerfile" "./locker/LockerSimpleImage/."
    ```

3. Build and run Locker:

    ```bash
    make run-locker
    ```

Navigate to http://localhost:5000 to access Locker.


### Windows

For Windows, if you have [Windows Subsystem for Linux](https://docs.microsoft.com/en-us/windows/wsl/install-win10) (WSL) installed, you can use the Makefile to build the Locker image and start Locker by following the [Mac/linux](#maclinux) instructions. To run directly on Windows without WSL, ensure you have the [dependencies](#dependencies) installed and follow the steps below in Powershell.

1. Clone this repository to your computer and move into the Locker directory:

    ```powershell
    git clone https://github.com/TBIO-RR-Group/Locker.git
    cd Locker
    ```

2. Build the Locker Simple Image to use with Locker:

    ```powershell
    docker build --platform linux/amd64 -t rr:LockerSimpleImage -f "./locker/LockerSimpleImage/Dockerfile" "./locker/LockerSimpleImage/."
    ```

3. Build and run Locker:

    ```powershell
    .\build_and_run_win.bat
    ```

Navigate to http://localhost:5000 to access Locker.

## Creating Special Interactive Docker Images for use with Locker

Docker images must be specially created to work with Locker, in particular you need to install the interactive apps that Locker works with: RStudio, Jupyter, Jupyterlab, and VSCode (sshd is also required for ssh access to started containers; note that Locker uses [Supervisord](http://supervisord.org/) to run and manage multiple processes inside started containers). We provide a [simple, "bare bones" example Dockerfile](locker/LockerSimpleImage) that you can use as a starting point --- you could easily enhance this with additional installs (R and Python packages, apt installs, etc.) Alternatively, within our company we created a special process and system to aid us in creating these Docker images and we have also released that at [DockerImageBuilder repo](https://github.com/TBIO-RR-Group/DockerImageBuilder).

## Working with a Single Sign-on (SSO) service

Locker can be run in 2 modes: 'local' or 'remote'. 'local' is meant for an individual to run Locker on their local computer (e.g. Mac or Windows laptop) and does not allow access to Locker over the internet (Locker can only be accessed by localhost-based urls, e.g. http://localhost:5000, in this case); it is assumed only the user has physical access to the computer running Locker in 'local' mode and that they will directly access Locker from a web browser running on that computer. 'remote' does allow access to Locker over the internet, but in this case access is controlled using an SSO service (only the user who started the remotely running Locker will be able to access it over the internet, based on them having a valid SSO token that Locker will check and validate). Internally at our company where we developed Locker we use [SiteMinder](https://www.broadcom.com/products/identity/siteminder) for this purpose, however we have also created and separately released an [SSO solution based on JSON web tokens](https://github.com/TBIO-RR-Group/ldap_jwt_sso) that can be used with Locker.

## Setting up a Docker Registry

Locker requires that the special interactive Docker images created for use with Locker be stored at and made accessible from a Docker registry. You could use any registry for this purpose, as long as it doesn't require authentication/Docker login, for example the [Docker Distribution Registry](https://distribution.github.io/distribution/). Alternatively, [AWS ECR](https://aws.amazon.com/ecr/) is a popular registry service, although it does require authentication to use it --- we have created and separately released a [proxy server to ECR](https://github.com/TBIO-RR-Group/apache_ecr_proxy) that doesn't require end user authentication to AWS (the proxy does that on behalf of users in order to provide access to ECR images).

Note: if you only intend to use Locker on a single machine (e.g. Mac or Windows Laptop) for yourself and don't want to set up a Docker registry or SSO service, you can simply build and keep the images to be used with Locker directly on the machine where you will run Locker (Locker will make those accessible to you to start containers from, it will just be the case that there won't be any registry images to pull) and run Locker in 'local' mode on that machine.

## Creating the Docker Image for Locker and Locker Services

Before you can run Locker or Locker services you need to create the Docker image that can run them. There are 2 configuration files you will need to edit to set your own values: `.env` and `config.yml`. `.env` is a file defining a small number of environment variables and is necessary for using the Makefile. `config.yml` is a [YAML](https://en.wikipedia.org/wiki/YAML) format file that contains the majority of the necessary configuration values for Locker and Locker services, and there are detailed comments inside it explaining what the values mean and how they should be set. To create the Docker image follow the steps below.

1. Clone this repository to your server:

    ```bash
    git clone https://github.com/TBIO-RR-Group/Locker.git
    ```

2. Update the values in config.yml with your own values. Then create a `.env` file in the same directory as the `Makefile`. Then copy the following environmental variables and replace them with your own values.

    Example `.env` file:
    ```bash
    # Docker image variables
    NAME=<IMAGE NAME HERE>
    VERSION=<IMAGE VERSION HERE>
    REGISTRY=<REGISTRY HERE>
    ECR_REGISTRY=<ECR REGISTRY HERE>

    # Apache configurations
    SERVER_ADMIN=<SERVER ADMIN HERE>
    PORT=<PORT HERE>

    # AWS Settings
    AWS_ACCESS_KEY_ID=<AWS ACCESS KEY ID HERE>
    AWS_SECRET_ACCESS_KEY=<AWS SECRET ACCESS KEY HERE>
    AWS_ADMIN_KEY=<FULL PATH TO AWS ADMIN KEY HERE>
    AWS_DEFAULT_REGION=<AWS DEFAULT REGION HERE>

    # SSL Certs
    CERT_FILE=<FULL PATH TO CERT FILE HERE>
    KEY_FILE=<FULL PATH TO KEY FILE HERE>
    ```

4. Run `make build` to build the docker image.

## Running Locker Services

Locker Services is a platform for launching and managing AWS EC2 instances with Locker preconfigured and running. Ensure that you have a server with the list of [dependencies](#dependencies) installed. To run Locker Services on your server, after building the Docker image:

 Run `make run-locker-services` to start a container running Locker Services.
 
 ## Running Locker directly on a Computer
 
 If you just want to directly run Locker on a computer without going through Locker Services you can run `make run-locker` on Mac and Linux computers (and Windows Subsystem for Linux). Alternatively, you can generate a start script that could be used to start Locker (you could then just distribute this start script to other users so they wouldn't have to clone the repo and build the image themselves): on Mac and Linux (and Windows Subsystem for Linux) run `make locker-startscript` --- this will write the generated start script to `/tmp/start_script`. Windows Note: if you don't want to use Windows Subsystem for Linux on Windows to build the Locker image and start and run Locker, there is a Windows Batch script `build_and_run_win.bat` you can run in e.g. Powershell that will build the Locker image and start Locker for you. Note also: if you don't have access to the `make` program in order to start Locker directly or generate start scripts, you can also just manually execute the script [gen_start_script](locker/gen_start_script) that is used to create the start scripts, and please see the comments at the top of gen_start_script for how to do that.

## Development

Follow the [setup instructions](#setting-up-locker-services) and then run `make dev`. This will bind-mount the `.vscode`, `locker`, and `locker_services` folders to their locations inside the container. Any changes made to files in these directories will persist outside of the container and changes will be reflected in "real-time".

## Dependencies

### Locker
- Docker
- GNU Make (Mac/Linux/WSL)
- Git

### Locker Serivces
To run Locker Services, you must have the following dependencies installed:

- Linux server
- AWS Credentials with proper permissions
- An AMI that will be used for the EC2 instances started by Locker Services
- Docker
- GNU Make

## Using Locker Services

#### Content
- [Locker Setup Instructions](#locker-setup-instructions)
- [Day-to-day Use Instructions](#day-to-day-use-instructions)
- [Additional Resources](#additional-resources)

### Locker Setup Instructions
1. Navigate to the **Locker Services** main page (that you just setup as above), which will show a portal view of all your started EC2 instances.
2. Create a new server
    1. On the top menu bar, click **Locker on New Server**
    2. Configure the settings accordingly
        - Choose **Instance Type** (e.g. m5.xlarge)
        - Paste entire contents of your `id_rsa.pub` to **SSH Public Key** and `id_rsa` to **SSH Private Key** fields
    3. Click **Start Locker on New Server**
        - This can take a while, so be patient. You can use other windows/tabs, but don't navigate away from this page until the process is complete.
        - You'll get an onscreen message and email confirming whether the startup succeeded or failed
3. Open the **Locker Portal** for your new server
    1. Click **Locker Server Portal** on the top menu bar of the **Locker Services** portal
    2. Find your new server in the list, and click the **Locker** link under the **Open Connection** column
4. Configure your new server 
    1. Click **Configure** on the top menu bar
    2. In the **Git Repos Clone Location:** option, select the following path: `/usr`
    3. Click **Save Configuration**
5. Pull your locker image(s)
    1. Click **Images** on the top menu bar
    2. Find your image, and pull it by clicking **Pull**
        - E.g., `rr:img-2023-11-SelfContained`
        - Self contained images are larger and take longer to pull, but they start up faster and enable faster package downloads during development
        - This can take a long time, just be patient!
6. Create a new container
    1. Once your image has pulled, click on the **Images** tab on the top menu bar
    2. Find the image you want to develop in
    3. Click the **Start** button in the **Start Container** column, and configure the options accordingly
        - Select IDE (RStudio, Jupyter, Jupyterlab, VScode)
        - Paste in `ssh` URL of your biogit repo
        - Paste in startup script if any (e.g. modified from `init_locker.sh` script). This startup script is stored in `/host_root/home/ec2-user/.locker/` by default.
    4. Click **Start** to create your new container
        - It might take a few seconds before your container can be opened
7. Open the IDE
    1. Click the **Containers** tab on the top menu
    2. Find your new container in the list, and click on the app, e.g., `rstudio` link

### Day-to-Day Use Instructions
1. Navigate to your server's **Container** page
    - Access the portal starting at **Locker Server Portal** on the top menu bar of the **Locker Services** portal -> Find your EC2 instance server and click the **Locker** link under **Open Connection** -> **Containers Tab**
2. Click **Start** on the container you want to use
3. Open the IDE after the container has started
    - e.g., click the `rstudio` link on the container row
4. Click **Stop** on the container line when you're done developing for the day

As another note, click **Stop** on the main server in the **Locker Services** to avoid accruing server costs, e.g., on weekends (you can later easily restart it); also, you can terminate servers when no longer needed.
