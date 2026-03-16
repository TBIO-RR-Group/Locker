import time
import calendar
from flask import request, redirect, g
import requests
import os
import re
import json
import tempfile
import logging
from Config import Config
import utils

# Load locker configuration
config = Config("/config.yml")

# Configure logging
logger = logging.getLogger(__name__)

def get_browser_headers():
    """Get browser-like headers required for ForgeRock validation requests"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Sec-Ch-Ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1'
    }

#Returning None means 'pass', i.e. allow the user access to the
#requested resource. Otherwise returns a "access denied" message that
#can get displayed to the user. This version uses ForgeRock/Ping
#authentication exclusively.
def smAuth(request, requiredUsers, validatedCookies):

    logger.info('Processing ForgeRock/Ping authentication')
    
    redirect_url = config.redirect_url
    validate_url = config.validate_url

    #See here for getting parts of url in Flask: https://stackoverflow.com/questions/15974730/how-do-i-get-the-different-parts-of-a-flask-requests-url
    #See here for quote: https://stackoverflow.com/questions/1695183/how-to-percent-encode-url-parameters-in-python
    location = redirect_url + f'?{config.REDIRECT_TARGET_ARGNAME}=' + requests.utils.quote(request.url)

    if not config.SSO_SESSION_COOKIE_NAME in request.cookies:
        logger.info(f'No {config.SSO_SESSION_COOKIE_NAME} cookie found, redirecting to ForgeRock SSO')
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
            logger.info(f'Removing expired cookie: {curSmSession[:20]}...')
            delCookies[curSmSession] = True

    for curSmSession, assocVal in delCookies.items():
        del validatedCookies[curSmSession]

    smSession = request.cookies[config.SSO_SESSION_COOKIE_NAME]

    if smSession in validatedCookies:
        logger.info('Cookie found in cache')
        validatedCookieVals = validatedCookies[smSession]
        if validatedCookieVals[2] in requiredUsers:
            logger.info(f'User {validatedCookieVals[2]} authorized')
            g.authenticated_user = validatedCookieVals[2]
            return None
        else:
            logger.info(f'User {validatedCookieVals[2]} not authorized')
            return "Access Denied"

    logger.info('Validating ForgeRock cookie with validation service')
    
    # ForgeRock requires browser-like headers for successful validation
    validation_cookies = {config.SSO_SESSION_COOKIE_NAME: smSession}
    validation_headers = get_browser_headers()
    logger.info('Using browser-like headers for ForgeRock validation')
    
    try:
        validateResp = requests.get(
            validate_url,
            cookies=validation_cookies,
            headers=validation_headers,
            allow_redirects=True,
            timeout=10
        )
        
        logger.info(f'Validation response status: {validateResp.status_code}')
        respLines = validateResp.text.splitlines()
        
    except Exception as e:
        logger.error(f'ForgeRock validation request failed: {str(e)}')
        return redirect(location)

    if len(respLines) == 0 or respLines[0] != 'Success':
        logger.info('ForgeRock validation failed, redirecting to SSO')
        return redirect(location)

    respValsHash = {}
    for curLine in respLines:
        matches = re.search('^([^\=]+)=(.+)$', curLine)
        if matches:
            respValsHash[matches.group(1)] = matches.group(2)

    if not respValsHash['User'] in requiredUsers:
        logger.info(f'User {respValsHash["User"]} not in required users list')
        return "Access Denied"

    validatedCookies[smSession] = [int(respValsHash["TTL"]),calendar.timegm(time.gmtime()),respValsHash["User"]]
    numCookies = len(validatedCookies.keys())
    logger.info(f'ForgeRock authentication successful for user {respValsHash["User"]}, cached sessions: {numCookies}')

    g.authenticated_user = respValsHash["User"]
    return None
