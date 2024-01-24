import yaml

class Config:
    def __init__(self, filename):
        with open(filename, 'r') as file:
            conf = yaml.safe_load(file)
            ## Unnest sections of config file
            self.__dict__ = {
                **conf["credential_settings"],
                **conf["locker_services"],
                **conf["locker"]
            }

        ## TODO: Change code to handle dict and remove these
        self.EXTRA_TAGS = self.unpack(self.EXTRA_TAGS)
        self.sshfsMounts = self.unpack(self.sshfsMounts)
        self.sshfsHostMounts = self.unpack(self.sshfsHostMounts)

        ## Parse regexes
        self.lockerRunnableImageRegexes = \
            self.parseRegexes(self.lockerRunnableImageRegexes)
    
    ## Unpack dictionaries as lists of lists
    def unpack(self, prop):
        return [[v for v in p.values()] for p in prop]
    
    ## Variable substitution for regexes
    def parseRegexes(self, prop):
        return [p.format(**self.__dict__) for p in prop]


if __name__ == "__main__":
    ## Example
    locker_config = Config('/config.yml')
    print(locker_config.ADMIN_USERNAME)