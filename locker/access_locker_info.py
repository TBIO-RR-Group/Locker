import utils

host = utils.get_my_global_host_or_ip()
if host is None:
    host = 'localhost'

access_url = host
print(access_url)

