#!/usr/bin/env python3

import json
import argparse
import os

def empty(str):
    """
    Return True if the str is None or composed of only whitespace, False otherwise
    """

    if str is None:
        return True
    if str.strip() == "":
        return True
    return False

#This is a copy of utils.pathContents (would be better to just use utils.py directly but
#trying to minimize/simplify this script's code which will be copied into and run Docker containers).
#In any case, this function should be kept consistent with the way utils.pathContents works.
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
            raise Exception('path or its prefix does not exist or is not accessible for ' + origThePath)

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


#Like route paths_ac in app.py, but for use inside a started Docker container as CLI
def paths_ac(term,ftype):

    if (empty(ftype)):
        ftype = 'BOTH'

    if empty(term):
        term = '/'

    pathsInfo = pathContents(term,ftype)
    print(json.dumps(pathsInfo))

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('--term', help="The path (and term at the end) to search", default="/", type=str)
parser.add_argument('--ftype', help="Type of sub-content to return (DIR, FILE, or BOTH)", default="BOTH", type=str)

args = parser.parse_args()
paths_ac(args.term.strip(),args.ftype.strip())
