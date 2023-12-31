#!/usr/bin/env python
import os
print("Content-type: text/html\r\n\r\n")
print("<h2>Environment</h2><br>")
for param in os.environ.keys():
   if "AWS" not in param:
      print("<b>%20s</b>: %s <br>" % (param, os.environ[param]))