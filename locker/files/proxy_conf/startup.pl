use lib qw(/perl_mods);
#Note: see here for how to dynamically get the actual user Apache is running under (www-data on Ubuntu):
#https://serverfault.com/questions/125865/finding-out-what-user-apache-is-running-as
#Basically, use apachectl -S
system("touch /tmp/.cache_fastmmap_sharefile; chown www-data:www-data /tmp/.cache_fastmmap_sharefile");
1;
