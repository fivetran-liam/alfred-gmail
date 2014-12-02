import httplib2
import time
from time import sleep, strftime
from email.utils import parsedate

from apiclient.discovery import build
from apiclient.http import BatchHttpRequest
from oauth2client.client import flow_from_clientsecrets, OAuth2Credentials
from oauth2client.tools import run

from workflow import Workflow, PasswordNotFound

import config

WF = Workflow()
EMAIL_LIST = dict((x,[]) for x in config.SYSTEM_LABELS.keys())


class PseudoStorage():

    def put(self, value):
        pass


def list_threads(label, request_id, response, exception):
    if exception is None:
        thread = {
            'Date': None,
            'From': None,
            'id': None,
            'messages_count': None,
            'snippet': None,
            'Subject': None,
            'threadId': None,
            'unread': None,
        }
        if 'messages' in response and len(response['messages']) > 0:
            latest_message = response['messages'][-1]
            if 'id' in latest_message:
                thread['id'] = latest_message['id']

            if 'threadId' in latest_message:
                thread['threadId'] = latest_message['threadId']

            if 'snippet' in latest_message:
                thread['snippet'] = WF.decode(response[
                    'messages'][-1]['snippet'])

            for header in latest_message['payload']['headers']:
                if header['name'] in thread:
                    thread[header['name']] = WF.decode(header[
                        'value'])
                    if header['name'] == "Date":
                        thread[header['name']] = get_date(header[
                            'value'])
                    else:
                        thread[header['name']] = WF.decode(header[
                            'value'])

            thread['messages_count'] = len(response['messages'])
            thread['unread'] = 'UNREAD' in latest_message['labelIds']

            if label in config.SYSTEM_LABELS:
                EMAIL_LIST[label].append(thread)


def get_date(date_str):
    return strftime("%m/%d/%Y %H:%M", parsedate(date_str))


def get_list(http, service, label):
    if label in config.SYSTEM_LABELS.keys():
        # Retrieve a page of threads
        threads = service.users().threads().list(
            userId='me', labelIds=[label.upper()], maxResults=100).execute()

        if threads['resultSizeEstimate'] == 0:
            return []

        batch = BatchHttpRequest()
        if 'threads' in threads and len(threads['threads']) > 0:
            fields = 'messages/id,messages/threadId,messages/labelIds,messages/snippet,messages/payload/headers'

            def wrapper(request_id, response, exception):
                list_threads(label, request_id, response, exception)

            for thread in threads['threads']:
                batch.add(service.users().threads().get(
                    userId='me', id=thread['id'], fields=fields), callback=wrapper)

            batch.execute(http=http)

        return EMAIL_LIST[label]


def get_labels(service):
    try:
        response = service.users().labels().list(userId='me').execute()
        return response['labels']
    except errors.HttpError, error:
        WF.logger.debug('An error occurred: %s' % error)
        return []


def refresh_cache(labels=None):
    labels = labels if labels is not None else config.SYSTEM_LABELS.keys()
    flow = flow_from_clientsecrets(
        config.CLIENT_SECRET_FILE, scope=config.OAUTH_SCOPE)
    http = httplib2.Http()

    try:
        credentials = OAuth2Credentials.from_json(
            WF.get_password('gmail_credentials'))
        if credentials is None or credentials.invalid:
            credentials = run(flow, PseudoStorage(), http=http)
            WF.save_password('gmail_credentials', credentials.to_json())
            WF.logger.debug('Credentials securely updated')

        http = credentials.authorize(http)
        gmail_service = build('gmail', 'v1', http=http)

        for label in labels:
            WF.cache_data('gmail_%s' % label.lower(), get_list(http, gmail_service, label))
            time.sleep(2)
        if not WF.cached_data_fresh('gmail_labels', max_age=300):
            WF.cache_data('gmail_labels', get_labels(gmail_service))

    except PasswordNotFound:
        WF.logger.debug('Credentials not found')
        credentials = run(flow, PseudoStorage(), http=http)
        WF.save_password('gmail_credentials', credentials.to_json())
        WF.logger.debug('New Credentials securely saved')

if __name__ == '__main__':
    refresh_cache()
