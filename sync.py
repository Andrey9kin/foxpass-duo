# Foxpass to Duo user sync script
#
# Copyright (c) 2017-present, Foxpass, Inc.
# All rights reserved.
#
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


import argparse
import logging
import requests
import sys
import time
import urllib.parse
import os

import duo_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='Sync between Foxpass and Duo.')
parser.add_argument('--once', action='store_true', help='Run once and exit (or non-empty FOXPASS_DUO_SYNC_ONCE env. var.)')
parser.add_argument('--do', action='store_true', help='Run sync otherwise will only print what it would do without actually doing it (or non-empty FOXPASS_DUO_DO_SYNC env. var.)')
parser.add_argument('--interval', default=5, type=int, help='Minutes to wait between runs')
parser.add_argument('--foxpass-hostname', default='https://api.foxpass.com',
                    help='Foxpass API URL, e.g. https://api.foxpass.com (or FOXPASS_HOSTNAME env. var.)')
parser.add_argument('--foxpass-api-key', help='Foxpass API key (or FOXPASS_API_KEY env. var.)')
parser.add_argument('--foxpass-group', help='Foxpass group name to sync (or FOXPASS_GROUP env. var.)')
parser.add_argument('--duo-hostname', help='Duo URL, e.g. duo-XXXX.duosecurity.com (or DUO_HOSTNAME env. var.)')
parser.add_argument('--duo-ikey', help='Duo API ikey (or DUO_IKEY env. var.)')
parser.add_argument('--duo-skey', help='Duo API skey (or DUO_SKEY env. var.)')
ARGS = parser.parse_args()

try:
    FOXPASS_HOSTNAME = ARGS.foxpass_hostname or os.environ['FOXPASS_HOSTNAME']
    FOXPASS_API_KEY = ARGS.foxpass_api_key or os.environ['FOXPASS_API_KEY']
    FOXPASS_GROUP = ARGS.foxpass_group or os.environ.get('FOXPASS_GROUP', None)

    FOXPASS_DUO_SYNC_ONCE = ARGS.once or True if 'FOXPASS_DUO_SYNC_ONCE' in os.environ else False
    FOXPASS_DUO_DO_SYNC = ARGS.do or True if 'FOXPASS_DUO_DO_SYNC' in os.environ else False

    DUO_HOSTNAME = ARGS.duo_hostname or os.environ['DUO_HOSTNAME']
    DUO_IKEY = ARGS.duo_ikey or os.environ['DUO_IKEY']
    DUO_SKEY = ARGS.duo_skey or os.environ['DUO_SKEY']
except KeyError as e:
    logger.error('No value in args. or env. for {}'.format(str(e)))
    sys.exit(1)

FOXPASS_REQUEST_HEADERS={'Accept': 'application/json',
                         'Authorization': 'Token {}'.format(FOXPASS_API_KEY)}

admin_api = duo_client.Admin(
    ikey=DUO_IKEY,
    skey=DUO_SKEY,
    host=DUO_HOSTNAME
)

def get_foxpass_users_in_group(group):
    group_url = urllib.parse.urljoin(FOXPASS_HOSTNAME, '/v1/groups/{}/members/'.format(group))

    r = requests.get(group_url, headers=FOXPASS_REQUEST_HEADERS)
    r.raise_for_status()

    json_data = r.json()

    if 'data' in json_data:
        return [user['username'] for user in json_data['data']]

    return None

def get_all_foxpass_users():
    url = urllib.parse.urljoin(FOXPASS_HOSTNAME, '/v1/users/')

    r = requests.get(url, headers=FOXPASS_REQUEST_HEADERS)
    r.raise_for_status()
    json_data = r.json()

    if 'data' in json_data:
        return json_data['data']

    return None

def sync():
    duo_users = admin_api.get_users()
    duo_email_set = dict()
    for user in duo_users:
        if user['email'] and user['email'] not in list(duo_email_set.keys()):
            duo_email_set[user['email']] = user

    foxpass_users = get_all_foxpass_users()

    group_members = None
    if FOXPASS_GROUP:
        group_members = set(get_foxpass_users_in_group(FOXPASS_GROUP))

    # make a set of foxpass users that should be in duo. they must be active and if a group is
    # specified, they must be in that group
    foxpass_sync_set = list()
    for user in foxpass_users:
        if user['active'] and (not group_members or user['username'] in group_members) and user not in foxpass_sync_set:
            foxpass_sync_set.append(user)

    # duo_email_set is all duo email addresses
    # foxpass_sync_set is all active foxpass users
    # enroll into duo every foxpass user that's not already there
    for user in foxpass_sync_set:
        if user['email'] in list(duo_email_set.keys()):
            if not FOXPASS_DUO_DO_SYNC:
                logger.info("[DRY RUN] Would update {}".format(user['email']))
            else:
                logger.info("Updating {} ...".format(user['email']))
                admin_api.update_user(duo_email_set[user['email']]['user_id'],
                                      user['username'],
                                      '{} {}'.format(user['first_name'], user['last_name']),
                                      'active',
                                      'Automatically synced from foxpass',
                                      user['email'],
                                      user['first_name'],
                                      user['last_name'])
            continue

        if not FOXPASS_DUO_DO_SYNC:
            logger.info("[DRY RUN] Would create {}".format(user['email']))
        else:
            logger.info("Creating {} ...".format(user['email']))
            admin_api.add_user(user['username'],
                               '{} {}'.format(user['first_name'], user['last_name']),
                               'active',
                               'Automatically synced from foxpass',
                               user['email'],
                               user['first_name'],
                               user['last_name'])

    if not FOXPASS_DUO_DO_SYNC:
        logger.info('--do was not specified, no users synced')
        logger.info('Re-run script with --do to actually run sync process')

# This is one is to be used when triggering script as AWS Lambda
# Since it does not need any external input from Lambda trigger
# context and input are ignored
def lambda_handler(json_input, context):
    # The Lambda environment pre-configures a handler logging to stderr. If a handler is already configured,
    # `.basicConfig` does not execute. Thus we set the level directly.
    logging.getLogger().setLevel(logging.INFO)
    main()

def main():
    while True:
        try:
            sync()
        except KeyboardInterrupt:
            return
        except:
            logger.exception('Unhandled exception during sync')

        if FOXPASS_DUO_SYNC_ONCE:
            return

        logger.info('Sleeping for {} minuntes'.format(ARGS.interval))
        time.sleep(ARGS.interval * 60) # interval is in minutes. Covert to seconds.

if __name__ == '__main__':
    main()
