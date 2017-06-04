import logging
import requests
import json
from bs4 import BeautifulSoup
from requests_toolbelt.utils import dump
import datetime
import codecs
import tempfile
import pkg_resources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('postcard-creator-wrapper')


class Debug(object):
    debug = False
    trace = False

    @staticmethod
    def log(msg):
        if Debug.debug:
            logger.info(msg)

    @staticmethod
    def debug_request(response):
        if Debug.trace:
            data = dump.dump_all(response)
            try:
                logger.info(data.decode())
            except Exception:
                logger.error(response)


class Token(object):
    base = 'https://account.post.ch'
    token_url = 'https://postcardcreator.post.ch/saml/SSO/alias/defaultAlias'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0.1; LG-D855 Build/M4B30X; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/52.0.2743.98 Mobile Safari/537.36',
        'Origin': 'https://account.post.ch'
    }

    def __init__(self):
        self.token = None
        self.token_type = None
        self.token_expires_in = None
        self.token_fetched_at = None
        self.cache_token = False

    def fetch_token(self, username, password):
        if username is None or password is None:
            raise Exception('No username/ password given')

        if self.cache_token:
            tmp_dir = tempfile.gettempdir() # TODO, option to cache token

        session = requests.Session()
        payload = {
            'RelayState': 'https://postcardcreator.post.ch?inMobileApp=true&inIframe=false&lang=en',
            'SAMLResponse': self._get_saml_response(session, username, password)
        }

        response = session.post(url=self.token_url, headers=self.headers, data=payload)
        Debug.debug_request(response)

        try:
            access_token = json.loads(response.text)

            self.token = access_token['access_token']
            self.token_type = access_token['token_type']
            self.token_expires_in = access_token['expires_in']
            self.token_fetched_at = datetime.datetime.now()

            if response.status_code is not 200 or self.token is None:
                raise Exception()

        except Exception:
            raise Exception(
                'Could not get access_token. Something broke. set debug=True to debug why\n' + response.text)

    def _get_saml_response(self, session, username, password):
        url = '{}/SAML/IdentityProvider/'.format(self.base)
        query = '?login&app=pcc&service=pcc&targetURL=https%3A%2F%2Fpostcardcreator.post.ch&abortURL=https%3A%2F%2Fpostcardcreator.post.ch&inMobileApp=true'
        data = {
            'isiwebuserid': username,
            'isiwebpasswd': password,
            'confirmLogin': ''
        }
        response1 = session.get(url=url + query, headers=self.headers)
        Debug.debug_request(response1)

        response2 = session.post(url=url + query, headers=self.headers, data=data)
        Debug.debug_request(response2)

        response3 = session.post(url=url + query, headers=self.headers)
        Debug.debug_request(response3)

        if any(e.status_code is not 200 for e in [response1, response2, response3]):
            raise Exception('Wrong user credentials')

        soup = BeautifulSoup(response3.text, 'html.parser')
        saml_response = soup.find('input', {'name': 'SAMLResponse'})

        if saml_response is None or saml_response.get('value') is None:
            raise Exception('The host site very likely changed and broke this API. set debug=True to debug')

        return saml_response.get('value')

    def to_json(self):
        return {
            'fetched_at': self.token_fetched_at,
            'token': self.token,
            'expires_in': self.token_expires_in,
            'type': self.token_type,
        }


class Sender(object):
    def __init__(self, prename, lastname, street, zip_code, place, company=''):
        self.prename = prename
        self.lastname = lastname
        self.street = street
        self.zip_code = zip_code
        self.place = place
        self.company = company

    def is_valid(self):
        return all(field is not None and field is not '' for field in
                   [self.prename, self.lastname, self.street, self.zip_code, self.place])


class Recipient(object):
    def __init__(self, prename, lastname, street, zip_code, place, company='', company_addition='', salutation=''):
        self.salutation = salutation
        self.prename = prename
        self.lastname = lastname
        self.street = street
        self.zip_code = zip_code
        self.place = place
        self.company = company
        self.company_addition = company_addition

    def is_valid(self):
        return all(field is not None and field is not '' for field in
                   [self.prename, self.lastname, self.street, self.zip_code, self.place])

    def to_json(self):
        return {'recipientFields': [
            {'name': 'Salutation', 'addressField': 'SALUTATION'},
            {'name': 'Given Name', 'addressField': 'GIVEN_NAME'},
            {'name': 'Family Name', 'addressField': 'FAMILY_NAME'},
            {'name': 'Company', 'addressField': 'COMPANY'},
            {'name': 'Company', 'addressField': 'COMPANY_ADDITION'},
            {'name': 'Street', 'addressField': 'STREET'},
            {'name': 'Post Code', 'addressField': 'ZIP_CODE'},
            {'name': 'Place', 'addressField': 'PLACE'}],
            'recipients': [
                [self.salutation, self.prename,
                 self.lastname, self.company,
                 self.company_addition, self.street,
                 self.zip_code, self.place]]}


class Postcard(object):
    def __init__(self, picture_location, sender, recipient, message=''):
        self.recipient = recipient
        self.message = message
        self.picture_location = picture_location
        self.sender = sender

    def get_picture_as_bytes(self):
        f = codecs.open(self.picture_location, 'rb')
        return f.read()

    def is_valid(self):
        return self.recipient is not None \
               and self.recipient.is_valid() \
               and self.sender is not None \
               and self.sender.is_valid()

    def validate(self):
        if self.recipient is None or not self.recipient.is_valid():
            raise Exception('Not all required attributes in recipient set')
        if self.recipient is None or not self.recipient.is_valid():
            raise Exception('Not all required attributes in sender set')

    def get_default_svg_page_1(self, user_id):
        file_name = pkg_resources.resource_string(__name__, '/'.join('page_2.svg'))
        f = codecs.open(file_name, 'r')
        svg = f.read()

        svg = svg.replace('{user_id}', str(user_id))
        return svg

    def get_default_svg_page_2(self):
        file_name = pkg_resources.resource_string(__name__, '/'.join('page_2.svg'))
        f = codecs.open(file_name, 'r')
        svg = f.read()

        svg = svg.replace('{first_name}', self.recipient.prename)
        svg = svg.replace('{last_name}', self.recipient.lastname)
        svg = svg.replace('{company}', self.recipient.company)
        svg = svg.replace('{company_addition}', self.recipient.company_addition)
        svg = svg.replace('{street}', self.recipient.street)
        svg = svg.replace('{zip_code}', str(self.recipient.zip_code))
        svg = svg.replace('{place}', self.recipient.place)

        svg = svg.replace('{sender_company}', self.sender.company)
        svg = svg.replace('{sender_name}', self.sender.prename + ' ' + self.sender.lastname)
        svg = svg.replace('{sender_adress}', self.sender.street)
        svg = svg.replace('{sender_zip_code}', str(self.sender.zip_code))
        svg = svg.replace('{sender_place}', self.sender.place)

        return svg


class PostcardCreatorWrapper(object):
    def __init__(self, token=None):
        if token.token is None:
            raise Exception('No Token given')

        self.token = token
        self.session = requests.Session()

        self.host = 'https://postcardcreator.post.ch/rest/2.1'

    def _get_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0.1; LG-D855 Build/M4B30X; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/52.0.2743.98 Mobile Safari/537.36',
            'Authorization': 'Bearer {}'.format(self.token.token)
        }

    def _do_op(self, method, endpoint, params=None, data=None, json=None, files=None, headers=None):
        if not endpoint.endswith('/'): endpoint += '/'
        url = self.host + endpoint

        if headers is None:
            headers = self._get_headers()

        rest_metod = getattr(self.session, method)
        Debug.log(' {}: {}'.format(method, url))

        response = rest_metod(url, params=params, data=data, json=json, headers=headers, files=files)
        Debug.debug_request(response)
        if response.status_code not in [200, 201, 204]:
            raise Exception('Error in request {}. status_code: {}, response: {}'
                            .format(url, response.status_code, response.text))
        return response

    def do_get(self, endpoint, params=None, headers=None):
        return self._do_op('get', endpoint=endpoint, params=params, headers=headers)

    def do_post(self, endpoint, params=None, data=None, json=None, files=None, headers=None):
        return self._do_op('post', endpoint=endpoint, params=params, data=data, json=json, files=files, headers=headers)

    def do_put(self, endpoint, params=None, data=None, json=None, files=None, headers=None):
        return self._do_op('put', endpoint=endpoint, params=params, data=data, json=json, files=files, headers=headers)

    def get_user_info(self):
        endpoint = '/users/current'
        return self.do_get(endpoint).json()

    def get_billing_saldo(self):
        user = self.get_user_info()
        endpoint = '/users/{}/billingOnlineAccountSaldo'.format(user['userId'])

        return self.do_get(endpoint).json()

    def get_quota(self):
        user = self.get_user_info()
        endpoint = '/users/{}/quota'.format(user['userId'])

        return self.do_get(endpoint).json()

    def has_free_postcard(self):
        return self.get_quota()['available']

    def send_free_card(self, postcard):
        if not self.has_free_postcard():
            raise Exception('Limit of free postcards exceeded. Try again tomorrow at ' + self.get_quota()['next'])
        if postcard is None:
            raise Exception('Postcard must be set')

        postcard.validate()
        user = self.get_user_info()
        user_id = user['userId']
        card_id = self._create_card(user)

        self._upload_asset(user, postcard=postcard)
        self._set_card_recipient(user_id=user_id, card_id=card_id, postcard=postcard)
        self._set_svg_page1(user_id, card_id, postcard)
        self._set_svg_page2(user_id, card_id, postcard)
        response = self._do_order(user_id, card_id)

    def _create_card(self, user):
        endpoint = '/users/{}/mailings'.format(user['userId'])

        mailing_payload = {
            'name': 'Mobile App Mailing {}'.format(datetime.datetime.now().strftime('%Y-%m-%d %H:%M')),
            # 2017-05-28 17:27
            'addressFormat': 'PERSON_FIRST',
            'paid': False
        }

        mailing_response = self.do_post(endpoint, json=mailing_payload)
        return mailing_response.headers['Location'].partition('mailings/')[2]

    def _upload_asset(self, user, postcard):
        endpoint = '/users/{}/assets'.format(user['userId'])

        bytes = postcard.get_picture_as_bytes()
        files = {
            'title': (None, 'Title of image'),
            'asset': ('asset.png', bytes, 'image/jpeg')
        }
        headers = self._get_headers()
        headers['Origin'] = 'file://'
        return self.do_post(endpoint, files=files, headers=headers)

    def _set_card_recipient(self, user_id, card_id, postcard):
        endpoint = '/users/{}/mailings/{}/recipients'.format(user_id, card_id)

        return self.do_put(endpoint, json=postcard.recipient.to_json())

    def _set_svg_page1(self, user_id, card_id, postcard):
        endpoint = '/users/{}/mailings/{}/pages/1'.format(user_id, card_id)

        headers = self._get_headers()
        headers['Origin'] = 'file://'
        headers['Content-Type'] = 'image/svg+xml'

        return self.do_put(endpoint, data=postcard.get_default_svg_page_1(user_id=user_id), headers=headers)

    def _set_svg_page2(self, user_id, card_id, postcard):
        endpoint = '/users/{}/mailings/{}/pages/2'.format(user_id, card_id)

        headers = self._get_headers()
        headers['Origin'] = 'file://'
        headers['Content-Type'] = 'image/svg+xml'

        return self.do_put(endpoint, data=postcard.get_default_svg_page_2(), headers=headers)

    def _do_order(self, user_id, card_id):
        endpoint = '/users/{}/mailings/{}/order'.format(user_id, card_id)
        return self.do_post(endpoint, json={})


if __name__ == '__main__':
    Debug.debug = True
    Debug.trace = True

    token = Token()
    token.fetch_token(username='', password='')
    recipient = Recipient(prename='', lastname='', street='', place='', zip_code=0000)
    sender = Sender(prename='', lastname='', street='', place='', zip_code=0000)
    card = Postcard(message='', recipient=recipient, sender=sender, picture_location='./asset.jpg')

    w = PostcardCreatorWrapper(token)
    w.send_free_card(postcard=card)