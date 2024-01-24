import time
import calendar
from flask import request, redirect
import requests
import os
import re
import json
import tempfile
from Config import Config
import utils

# Load locker configuration
config = Config("/config.yml")

#Returning None means 'pass', i.e. allow the user access to the
#requested resource. Otherwise returns a "access denied" message that
#can get displayed to the user. This version goes directly against
#the SiteMinder validation services and not indirectly through
#an intermediate service (so use this if you are directly on the
#BMS network).
def smAuth(request, requiredUsers, validatedCookies):

    #app.logger.info('Inside SiteMinder.smAuth')
    
    redirect_url = config.redirect_url
    validate_url = config.validate_url

    #See here for getting parts of url in Flask: https://stackoverflow.com/questions/15974730/how-do-i-get-the-different-parts-of-a-flask-requests-url
    #See here for quote: https://stackoverflow.com/questions/1695183/how-to-percent-encode-url-parameters-in-python
    location = redirect_url + f'?{config.REDIRECT_TARGET_ARGNAME}=' + requests.utils.quote(request.url)

    if not config.SSO_SESSION_COOKIE_NAME in request.cookies:
        #app.logger.info('SiteMinder.smAuth: redirecting to ' + location)
        return redirect(location)

    #Remove expired cookies from the validatedCookies dict
    currentEpochSecs = calendar.timegm(time.gmtime())
    delCookies = {}
    for curSmSession, assocVals in validatedCookies.items():
        initTtlSecs = assocVals[0]
        initEpochSecs = assocVals[1]
        secsDiff = currentEpochSecs - initEpochSecs
        remainingTtlSecs = initTtlSecs - secsDiff
        if remainingTtlSecs <= 0:
            #app.logger.info('SiteMinder.smAuth: adding timed out cookie to delCookies: ' + curSmSession)
            delCookies[curSmSession] = True

    for curSmSession, assocVal in delCookies.items():
        #app.logger.info('SiteMinder.smAuth: removing timed out cookie: ' + curSmSession)
        del validatedCookies[curSmSession]

    smSession = request.cookies[config.SSO_SESSION_COOKIE_NAME]

    if smSession in validatedCookies:
        #app.logger.info('SiteMinder.smAuth: smSession was in validatedCookies.')
        validatedCookieVals = validatedCookies[smSession]
        if validatedCookieVals[2] in requiredUsers:
            #app.logger.info('SiteMinder.smAuth: user is valid.')
            return None
        else:
            #app.logger.info('SiteMinder.smAuth: user is NOT valid, access denied.')
            return "Access Denied"

    #app.logger.info('SiteMinder.smAuth: cookie had not been previously validated, validating and checking user.')
    validateResp = requests.get(validate_url,cookies={ config.SSO_SESSION_COOKIE_NAME: smSession })
    respLines = validateResp.text.splitlines()

    if respLines[0] != 'Success':
        #app.logger.info('SiteMinder.smAuth: unsuccessful validation, redirecting to: ' + location)
        return redirect(location)

    respValsHash = {}
    for curLine in respLines:
        matches = re.search('^([^\=]+)=(.+)$', curLine)
        if matches:
            respValsHash[matches.group(1)] = matches.group(2)

    if not respValsHash['User'] in requiredUsers:
        #app.logger.info('SiteMinder.smAuth: for just validated cookie user is NOT valid, access denied.')
        return "Access Denied"

    validatedCookies[smSession] = [int(respValsHash["TTL"]),calendar.timegm(time.gmtime()),respValsHash["User"]];
    numCookies = len(validatedCookies.keys())
    #app.logger.info('SiteMinder.smAuth: cookie validated, user can pass, added cookie to validatedCookies, numCookies = ' + str(numCookies))

    return None
