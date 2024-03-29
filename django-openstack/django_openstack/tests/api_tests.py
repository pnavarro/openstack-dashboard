# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2011 Fourth Paradigm Development, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import cloudfiles
import httplib
import json
import mox

from django import http
from django.conf import settings
from django_openstack import api
from glance import client as glance_client
from mox import IsA
from openstack import compute as OSCompute
from openstackx import admin as OSAdmin
from openstackx import auth as OSAuth
from openstackx import extras as OSExtras


from django_openstack import test
from django_openstack.middleware import keystone


TEST_CONSOLE_KIND = 'vnc'
TEST_EMAIL = 'test@test.com'
TEST_HOSTNAME = 'hostname'
TEST_INSTANCE_ID = '2'
TEST_PASSWORD = '12345'
TEST_PORT = 8000
TEST_RETURN = 'retValue'
TEST_TENANT_DESCRIPTION = 'tenantDescription'
TEST_TENANT_ID = '1234'
TEST_TOKEN = 'aToken'
TEST_TOKEN_ID = 'userId'
TEST_URL = 'http://%s:%s/something/v1.0' % (TEST_HOSTNAME, TEST_PORT)
TEST_USERNAME = 'testUser'


class Server(object):
    """ More or less fakes what the api is looking for """
    def __init__(self, id, image, attrs=None):
        self.id = id
        
        self.image = image
        if attrs is not None:
            self.attrs = attrs

    def __eq__(self, other):
        if self.id != other.id or \
            self.image['id'] != other.image['id']:
                return False

        for k in self.attrs:
            if other.attrs.__getattr__(k) != v:
                return False

        return True

    def __ne__(self, other):
        return not self == other


class Tenant(object):
    """ More or less fakes what the api is looking for """
    def __init__(self, id, description, enabled):
        self.id = id
        self.description = description
        self.enabled = enabled

    def __eq__(self, other):
        return self.id == other.id and \
               self.description == other.description and \
               self.enabled == other.enabled

    def __ne__(self, other):
        return not self == other


class Token(object):
    """ More or less fakes what the api is looking for """
    def __init__(self, id, username, tenant_id, serviceCatalog=None):
        self.id = id
        self.username = username
        self.tenant_id = tenant_id
        self.serviceCatalog = serviceCatalog

    def __eq__(self, other):
        return self.id == other.id and \
               self.username == other.username and \
               self.tenant_id == other.tenant_id and \
               self.serviceCatalog == other.serviceCatalog

    def __ne__(self, other):
        return not self == other


class APIResource(api.APIResourceWrapper):
    """ Simple APIResource for testing """
    _attrs = ['foo', 'bar', 'baz']

    @staticmethod
    def get_instance(innerObject=None):
        if innerObject is None:
            class InnerAPIResource(object):
                pass
            innerObject = InnerAPIResource()
            innerObject.foo = 'foo'
            innerObject.bar = 'bar'
        return APIResource(innerObject)


class APIDict(api.APIDictWrapper):
    """ Simple APIDict for testing """
    _attrs = ['foo', 'bar', 'baz']

    @staticmethod
    def get_instance(innerDict=None):
        if innerDict is None:
            innerDict = {'foo': 'foo',
                         'bar': 'bar'}
        return APIDict(innerDict)


class APIResourceWrapperTests(test.TestCase):
    def test_get_attribute(self):
        resource = APIResource.get_instance()
        self.assertEqual(resource.foo, 'foo')

    def test_get_invalid_attribute(self):
        resource = APIResource.get_instance()
        self.assertNotIn('missing', resource._attrs,
                msg="Test assumption broken.  Find new missing attribute")
        with self.assertRaises(AttributeError):
            resource.missing

    def test_get_inner_missing_attribute(self):
        resource = APIResource.get_instance()
        with self.assertRaises(AttributeError):
            resource.baz


class APIDictWrapperTests(test.TestCase):
    # APIDict allows for both attribute access and dictionary style [element]
    # style access.  Test both
    def test_get_item(self):
        resource = APIDict.get_instance()
        self.assertEqual(resource.foo, 'foo')
        self.assertEqual(resource['foo'], 'foo')

    def test_get_invalid_item(self):
        resource = APIDict.get_instance()
        self.assertNotIn('missing', resource._attrs,
                msg="Test assumption broken.  Find new missing attribute")
        with self.assertRaises(AttributeError):
            resource.missing
        with self.assertRaises(KeyError):
            resource['missing']

    def test_get_inner_missing_attribute(self):
        resource = APIDict.get_instance()
        with self.assertRaises(AttributeError):
            resource.baz
        with self.assertRaises(KeyError):
            resource['baz']

    def test_get_with_default(self):
        resource = APIDict.get_instance()

        self.assertEqual(resource.get('foo'), 'foo')

        self.assertIsNone(resource.get('baz'))

        self.assertEqual('retValue', resource.get('baz', 'retValue'))


# Wrapper classes that only define _attrs don't need extra testing.
# Wrapper classes that have other attributes or methods need testing
class ImageWrapperTests(test.TestCase):
    dict_with_properties = {
            'properties':
                {'image_state': 'running'},
            'size': 100,
            }
    dict_without_properties = {
            'size': 100,
            }

    def test_get_properties(self):
        image = api.Image(self.dict_with_properties)
        image_props = image.properties
        self.assertIsInstance(image_props, api.ImageProperties)
        self.assertEqual(image_props.image_state, 'running')

    def test_get_other(self):
        image = api.Image(self.dict_with_properties)
        self.assertEqual(image.size, 100)

    def test_get_properties_missing(self):
        image = api.Image(self.dict_without_properties)
        with self.assertRaises(AttributeError):
            image.properties

    def test_get_other_missing(self):
        image = api.Image(self.dict_without_properties)
        with self.assertRaises(AttributeError):
            self.assertNotIn('missing', image._attrs,
                msg="Test assumption broken.  Find new missing attribute")
            image.missing


class ServerWrapperTests(test.TestCase):
    HOST = 'hostname'
    ID = '1'
    IMAGE_NAME = 'imageName'
    IMAGE_OBJ = { 'id': '3', 'links': [{'href': '3', u'rel': u'bookmark'}] }

    def setUp(self):
        super(ServerWrapperTests, self).setUp()

        # these are all objects "fetched" from the api
        self.inner_attrs = {'host': self.HOST}

        self.inner_server = Server(self.ID, self.IMAGE_OBJ, self.inner_attrs)
        self.inner_server_no_attrs = Server(self.ID, self.IMAGE_OBJ)

        #self.request = self.mox.CreateMock(http.HttpRequest)

    def test_get_attrs(self):
        server = api.Server(self.inner_server, self.request)
        attrs = server.attrs
        # for every attribute in the "inner" object passed to the api wrapper,
        # see if it can be accessed through the api.ServerAttribute instance
        for k in self.inner_attrs:
            self.assertEqual(attrs.__getattr__(k), self.inner_attrs[k])

    def test_get_other(self):
        server = api.Server(self.inner_server, self.request)
        self.assertEqual(server.id, self.ID)

    def test_get_attrs_missing(self):
        server = api.Server(self.inner_server_no_attrs, self.request)
        with self.assertRaises(AttributeError):
            server.attrs

    def test_get_other_missing(self):
        server = api.Server(self.inner_server, self.request)
        with self.assertRaises(AttributeError):
            self.assertNotIn('missing', server._attrs,
                msg="Test assumption broken.  Find new missing attribute")
            server.missing

    def test_image_name(self):
        self.mox.StubOutWithMock(api, 'image_get')
        api.image_get(IsA(http.HttpRequest),
                      self.IMAGE_OBJ['id']
                      ).AndReturn(api.Image({'name': self.IMAGE_NAME}))

        server = api.Server(self.inner_server, self.request)

        self.mox.ReplayAll()

        image_name = server.image_name

        self.assertEqual(image_name, self.IMAGE_NAME)

        self.mox.VerifyAll()


class ApiHelperTests(test.TestCase):
    """ Tests for functions that don't use one of the api objects """

    def test_url_for(self):
        GLANCE_URL = 'http://glance/glanceapi/'
        NOVA_URL = 'http://nova/novapi/'

        url = api.url_for(self.request, 'glance')
        self.assertEqual(url, GLANCE_URL + 'internal')

        url = api.url_for(self.request, 'glance', admin=False)
        self.assertEqual(url, GLANCE_URL + 'internal')

        url = api.url_for(self.request, 'glance', admin=True)
        self.assertEqual(url, GLANCE_URL + 'admin')

        url = api.url_for(self.request, 'nova')
        self.assertEqual(url, NOVA_URL + 'internal')

        url = api.url_for(self.request, 'nova', admin=False)
        self.assertEqual(url, NOVA_URL + 'internal')

        url = api.url_for(self.request, 'nova', admin=True)
        self.assertEqual(url, NOVA_URL + 'admin')

        self.assertNotIn('notAnApi', self.request.user.service_catalog,
                         'Select a new nonexistent service catalog key')
        with self.assertRaises(api.ServiceCatalogException):
            url = api.url_for(self.request, 'notAnApi')

    def test_token_info(self):
        """ This function uses the keystone api, but not through an
            api client, because there doesn't appear to be one for
            keystone
        """
        GLANCE_URL = 'http://glance/glance_api/'
        KEYSTONE_HOST = 'keystonehost'
        KEYSTONE_PORT = 8080
        KEYSTONE_URL = 'http://%s:%d/keystone/' % (KEYSTONE_HOST,
                                                   KEYSTONE_PORT)

        serviceCatalog = {
                'glance': [{'adminURL': GLANCE_URL + 'admin',
                            'internalURL': GLANCE_URL + 'internal'},
                          ],
                'identity': [{'adminURL': KEYSTONE_URL + 'admin',
                          'internalURL': KEYSTONE_URL + 'internal'},
                        ],
                }

        token = Token(TEST_TOKEN_ID, TEST_TENANT_ID,
                      TEST_USERNAME, serviceCatalog)

        jsonData = {
                'auth': {
                    'token': {
                        'expires': '2011-07-02T02:01:19.382655',
                        'id': '3c5748d5-bec6-4215-843a-f959d589f4b0',
                        },
                    'user': {
                        'username': 'joeuser',
                        'roleRefs': [{'roleId': 'Minion'}],
                        'tenantId': u'1234'
                        }
                    }
                }

        jsonDataAdmin = {
                'auth': {
                    'token': {
                        'expires': '2011-07-02T02:01:19.382655',
                        'id': '3c5748d5-bec6-4215-843a-f959d589f4b0',
                        },
                    'user': {
                        'username': 'joeuser',
                        'roleRefs': [{'roleId': 'Admin'}],
                        'tenantId': u'1234'
                        }
                    }
                }

        # setup test where user is not admin
        self.mox.StubOutClassWithMocks(httplib, 'HTTPConnection')

        conn = httplib.HTTPConnection(KEYSTONE_HOST, KEYSTONE_PORT)
        response = self.mox.CreateMock(httplib.HTTPResponse)

        conn.request(IsA(str), IsA(str), headers=IsA(dict))
        conn.getresponse().AndReturn(response)

        response.read().AndReturn(json.dumps(jsonData))

        expected_nonadmin_val = {
                'tenant': '1234',
                'user': 'joeuser',
                'admin': False
                }

        # setup test where user is admin
        conn = httplib.HTTPConnection(KEYSTONE_HOST, KEYSTONE_PORT)
        response = self.mox.CreateMock(httplib.HTTPResponse)

        conn.request(IsA(str), IsA(str), headers=IsA(dict))
        conn.getresponse().AndReturn(response)

        response.read().AndReturn(json.dumps(jsonDataAdmin))

        expected_admin_val = {
                'tenant': '1234',
                'user': 'joeuser',
                'admin': True
                }

        self.mox.ReplayAll()

        ret_val = api.token_info(None, token)

        self.assertDictEqual(ret_val, expected_nonadmin_val)

        ret_val = api.token_info(None, token)

        self.assertDictEqual(ret_val, expected_admin_val)

        self.mox.VerifyAll()


class AccountApiTests(test.TestCase):
    def stub_account_api(self):
        self.mox.StubOutWithMock(api, 'account_api')
        account_api = self.mox.CreateMock(OSExtras.Account)
        api.account_api(IsA(http.HttpRequest)).AndReturn(account_api)
        return account_api

    def test_get_account_api(self):
        self.mox.StubOutClassWithMocks(OSExtras, 'Account')
        OSExtras.Account(auth_token=TEST_TOKEN, management_url=TEST_URL)

        self.mox.StubOutWithMock(api, 'url_for')
        api.url_for(
                IsA(http.HttpRequest), 'identity', True).AndReturn(TEST_URL)
        api.url_for(
                IsA(http.HttpRequest), 'identity', True).AndReturn(TEST_URL)

        self.mox.ReplayAll()

        self.assertIsNotNone(api.account_api(self.request))

        self.mox.VerifyAll()

    def test_tenant_create(self):
        DESCRIPTION = 'aDescription'
        ENABLED = True

        account_api = self.stub_account_api()

        account_api.tenants = self.mox.CreateMockAnything()
        account_api.tenants.create(TEST_TENANT_ID, DESCRIPTION,
                                   ENABLED).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.tenant_create(self.request, TEST_TENANT_ID,
                                    DESCRIPTION, ENABLED)

        self.assertIsInstance(ret_val, api.Tenant)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_tenant_get(self):
        account_api = self.stub_account_api()

        account_api.tenants = self.mox.CreateMockAnything()
        account_api.tenants.get(TEST_TENANT_ID).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.tenant_get(self.request, TEST_TENANT_ID)

        self.assertIsInstance(ret_val, api.Tenant)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_tenant_list(self):
        tenants = (TEST_RETURN, TEST_RETURN + '2')

        account_api = self.stub_account_api()

        account_api.tenants = self.mox.CreateMockAnything()
        account_api.tenants.list().AndReturn(tenants)

        self.mox.ReplayAll()

        ret_val = api.tenant_list(self.request)

        self.assertEqual(len(ret_val), len(tenants))
        for tenant in ret_val:
            self.assertIsInstance(tenant, api.Tenant)
            self.assertIn(tenant._apiresource, tenants)

        self.mox.VerifyAll()

    def test_tenant_update(self):
        DESCRIPTION = 'aDescription'
        ENABLED = True

        account_api = self.stub_account_api()

        account_api.tenants = self.mox.CreateMockAnything()
        account_api.tenants.update(TEST_TENANT_ID, DESCRIPTION,
                                   ENABLED).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.tenant_update(self.request, TEST_TENANT_ID,
                                    DESCRIPTION, ENABLED)

        self.assertIsInstance(ret_val, api.Tenant)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_user_create(self):
        account_api = self.stub_account_api()

        account_api.users = self.mox.CreateMockAnything()
        account_api.users.create(TEST_USERNAME, TEST_EMAIL, TEST_PASSWORD,
                                TEST_TENANT_ID, True).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.user_create(self.request, TEST_USERNAME, TEST_EMAIL,
                                  TEST_PASSWORD, TEST_TENANT_ID, True)

        self.assertIsInstance(ret_val, api.User)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_user_delete(self):
        account_api = self.stub_account_api()

        account_api.users = self.mox.CreateMockAnything()
        account_api.users.delete(TEST_USERNAME).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.user_delete(self.request, TEST_USERNAME)

        self.assertIsNone(ret_val)

        self.mox.VerifyAll()

    def test_user_get(self):
        account_api = self.stub_account_api()

        account_api.users = self.mox.CreateMockAnything()
        account_api.users.get(TEST_USERNAME).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.user_get(self.request, TEST_USERNAME)

        self.assertIsInstance(ret_val, api.User)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_user_list(self):
        users = (TEST_USERNAME, TEST_USERNAME + '2')

        account_api = self.stub_account_api()
        account_api.users = self.mox.CreateMockAnything()
        account_api.users.list().AndReturn(users)

        self.mox.ReplayAll()

        ret_val = api.user_list(self.request)

        self.assertEqual(len(ret_val), len(users))
        for user in ret_val:
            self.assertIsInstance(user, api.User)
            self.assertIn(user._apiresource, users)

        self.mox.VerifyAll()

    def test_user_update_email(self):
        account_api = self.stub_account_api()
        account_api.users = self.mox.CreateMockAnything()
        account_api.users.update_email(TEST_USERNAME,
                                       TEST_EMAIL).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.user_update_email(self.request, TEST_USERNAME,
                                        TEST_EMAIL)

        self.assertIsInstance(ret_val, api.User)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_user_update_password(self):
        account_api = self.stub_account_api()
        account_api.users = self.mox.CreateMockAnything()
        account_api.users.update_password(TEST_USERNAME,
                                          TEST_PASSWORD).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.user_update_password(self.request, TEST_USERNAME,
                                           TEST_PASSWORD)

        self.assertIsInstance(ret_val, api.User)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_user_update_tenant(self):
        account_api = self.stub_account_api()
        account_api.users = self.mox.CreateMockAnything()
        account_api.users.update_tenant(TEST_USERNAME,
                                        TEST_TENANT_ID).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.user_update_tenant(self.request, TEST_USERNAME,
                                           TEST_TENANT_ID)

        self.assertIsInstance(ret_val, api.User)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()


class AdminApiTests(test.TestCase):
    def stub_admin_api(self, count=1):
        self.mox.StubOutWithMock(api, 'admin_api')
        admin_api = self.mox.CreateMock(OSAdmin.Admin)
        for i in range(count):
            api.admin_api(IsA(http.HttpRequest)).AndReturn(admin_api)
        return admin_api

    def test_get_admin_api(self):
        self.mox.StubOutClassWithMocks(OSAdmin, 'Admin')
        OSAdmin.Admin(auth_token=TEST_TOKEN, management_url=TEST_URL)

        self.mox.StubOutWithMock(api, 'url_for')
        api.url_for(IsA(http.HttpRequest), 'nova', True).AndReturn(TEST_URL)
        api.url_for(IsA(http.HttpRequest), 'nova', True).AndReturn(TEST_URL)

        self.mox.ReplayAll()

        self.assertIsNotNone(api.admin_api(self.request))

        self.mox.VerifyAll()

    def test_flavor_create(self):
        FLAVOR_DISK = 1000
        FLAVOR_ID = 6
        FLAVOR_MEMORY = 1024
        FLAVOR_NAME = 'newFlavor'
        FLAVOR_VCPU = 2

        admin_api = self.stub_admin_api()

        admin_api.flavors = self.mox.CreateMockAnything()
        admin_api.flavors.create(FLAVOR_NAME, FLAVOR_MEMORY, FLAVOR_VCPU,
                                 FLAVOR_DISK, FLAVOR_ID).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.flavor_create(self.request, FLAVOR_NAME,
                                    str(FLAVOR_MEMORY), str(FLAVOR_VCPU),
                                    str(FLAVOR_DISK), FLAVOR_ID)

        self.assertIsInstance(ret_val, api.Flavor)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_flavor_delete(self):
        FLAVOR_ID = 6

        admin_api = self.stub_admin_api(count=2)

        admin_api.flavors = self.mox.CreateMockAnything()
        admin_api.flavors.delete(FLAVOR_ID, False).AndReturn(TEST_RETURN)
        admin_api.flavors.delete(FLAVOR_ID, True).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.flavor_delete(self.request, FLAVOR_ID)
        self.assertIsNone(ret_val)

        ret_val = api.flavor_delete(self.request, FLAVOR_ID, purge=True)
        self.assertIsNone(ret_val)

    def test_service_get(self):
        NAME = 'serviceName'

        admin_api = self.stub_admin_api()
        admin_api.services = self.mox.CreateMockAnything()
        admin_api.services.get(NAME).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.service_get(self.request, NAME)

        self.assertIsInstance(ret_val, api.Services)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_service_list(self):
        services = (TEST_RETURN, TEST_RETURN + '2')

        admin_api = self.stub_admin_api()
        admin_api.services = self.mox.CreateMockAnything()
        admin_api.services.list().AndReturn(services)

        self.mox.ReplayAll()

        ret_val = api.service_list(self.request)

        for service in ret_val:
            self.assertIsInstance(service, api.Services)
            self.assertIn(service._apiresource, services)

        self.mox.VerifyAll()

    def test_service_update(self):
        ENABLED = True
        NAME = 'serviceName'

        admin_api = self.stub_admin_api()
        admin_api.services = self.mox.CreateMockAnything()
        admin_api.services.update(NAME, ENABLED).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.service_update(self.request, NAME, ENABLED)

        self.assertIsInstance(ret_val, api.Services)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()


class AuthApiTests(test.TestCase):
    def test_get_auth_api(self):
        settings.OPENSTACK_KEYSTONE_URL = TEST_URL
        self.mox.StubOutClassWithMocks(OSAuth, 'Auth')
        OSAuth.Auth(management_url=settings.OPENSTACK_KEYSTONE_URL)

        self.mox.ReplayAll()

        self.assertIsNotNone(api.auth_api())

        self.mox.VerifyAll()

    def test_token_get_tenant(self):
        self.mox.StubOutWithMock(api, 'auth_api')
        auth_api_mock = self.mox.CreateMockAnything()
        api.auth_api().AndReturn(auth_api_mock)

        tenants_mock = self.mox.CreateMockAnything()
        auth_api_mock.tenants = tenants_mock

        tenant_list = [Tenant('notTheDroid',
                              'notTheDroid_desc',
                              False),
                       Tenant(TEST_TENANT_ID,
                              TEST_TENANT_DESCRIPTION,
                              True),
                      ]
        tenants_mock.for_token('aToken').AndReturn(tenant_list)

        self.request.session = {'token': 'aToken'}

        self.mox.ReplayAll()

        ret_val = api.token_get_tenant(self.request, TEST_TENANT_ID)
        self.assertEqual(tenant_list[1], ret_val)

        self.mox.VerifyAll()

    def test_token_get_tenant_no_tenant(self):
        self.mox.StubOutWithMock(api, 'auth_api')
        auth_api_mock = self.mox.CreateMockAnything()
        api.auth_api().AndReturn(auth_api_mock)

        tenants_mock = self.mox.CreateMockAnything()
        auth_api_mock.tenants = tenants_mock

        tenant_list = [Tenant('notTheDroid',
                              'notTheDroid_desc',
                              False),
                      ]
        tenants_mock.for_token('aToken').AndReturn(tenant_list)

        self.request.session = {'token': 'aToken'}

        self.mox.ReplayAll()

        ret_val = api.token_get_tenant(self.request, TEST_TENANT_ID)
        self.assertIsNone(ret_val)

        self.mox.VerifyAll()

    def test_token_list_tenants(self):
        self.mox.StubOutWithMock(api, 'auth_api')
        auth_api_mock = self.mox.CreateMockAnything()
        api.auth_api().AndReturn(auth_api_mock)

        tenants_mock = self.mox.CreateMockAnything()
        auth_api_mock.tenants = tenants_mock

        tenant_list = [Tenant('notTheDroid',
                              'notTheDroid_desc',
                              False),
                       Tenant(TEST_TENANT_ID,
                              TEST_TENANT_DESCRIPTION,
                              True),
                      ]
        tenants_mock.for_token('aToken').AndReturn(tenant_list)

        self.mox.ReplayAll()

        ret_val = api.token_list_tenants(self.request, 'aToken')
        for tenant in ret_val:
            self.assertIn(tenant, tenant_list)

        self.mox.VerifyAll()

    def test_token_create(self):
        self.mox.StubOutWithMock(api, 'auth_api')
        auth_api_mock = self.mox.CreateMockAnything()
        api.auth_api().AndReturn(auth_api_mock)

        tokens_mock = self.mox.CreateMockAnything()
        auth_api_mock.tokens = tokens_mock

        test_token = Token(TEST_TOKEN_ID, TEST_USERNAME, TEST_TENANT_ID)

        tokens_mock.create(TEST_TENANT_ID, TEST_USERNAME,
                           TEST_PASSWORD).AndReturn(test_token)

        self.mox.ReplayAll()

        ret_val = api.token_create(self.request, TEST_TENANT_ID,
                                   TEST_USERNAME, TEST_PASSWORD)

        self.assertEqual(test_token, ret_val)

        self.mox.VerifyAll()


class ComputeApiTests(test.TestCase):
    def stub_compute_api(self, count=1):
        self.mox.StubOutWithMock(api, 'compute_api')
        compute_api = self.mox.CreateMock(OSCompute.Compute)
        for i in range(count):
            api.compute_api(IsA(http.HttpRequest)).AndReturn(compute_api)
        return compute_api

    def test_get_compute_api(self):
        class ComputeClient(object):
            __slots__ = ['auth_token', 'management_url']

        self.mox.StubOutClassWithMocks(OSCompute, 'Compute')
        compute_api = OSCompute.Compute(auth_token=TEST_TOKEN,
                                        management_url=TEST_URL)

        compute_api.client = ComputeClient()

        self.mox.StubOutWithMock(api, 'url_for')
        # called three times?  Looks like a good place for optimization
        api.url_for(IsA(http.HttpRequest), 'nova').AndReturn(TEST_URL)
        api.url_for(IsA(http.HttpRequest), 'nova').AndReturn(TEST_URL)
        api.url_for(IsA(http.HttpRequest), 'nova').AndReturn(TEST_URL)

        self.mox.ReplayAll()

        compute_api = api.compute_api(self.request)

        self.assertIsNotNone(compute_api)
        self.assertEqual(compute_api.client.auth_token, TEST_TOKEN)
        self.assertEqual(compute_api.client.management_url, TEST_URL)

        self.mox.VerifyAll()

    def test_flavor_get(self):
        FLAVOR_ID = 6

        compute_api = self.stub_compute_api()

        compute_api.flavors = self.mox.CreateMockAnything()
        compute_api.flavors.get(FLAVOR_ID).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.flavor_get(self.request, FLAVOR_ID)
        self.assertIsInstance(ret_val, api.Flavor)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_server_delete(self):
        INSTANCE = 'anInstance'

        compute_api = self.stub_compute_api()

        compute_api.servers = self.mox.CreateMockAnything()
        compute_api.servers.delete(INSTANCE).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.server_delete(self.request, INSTANCE)

        self.assertIsNone(ret_val)

        self.mox.VerifyAll()

    def test_server_reboot(self):
        INSTANCE_ID = '2'
        HARDNESS = 'diamond'

        self.mox.StubOutWithMock(api, 'server_get')

        server = self.mox.CreateMock(OSCompute.Server)
        server.reboot(OSCompute.servers.REBOOT_HARD).AndReturn(TEST_RETURN)
        api.server_get(IsA(http.HttpRequest), INSTANCE_ID).AndReturn(server)

        server = self.mox.CreateMock(OSCompute.Server)
        server.reboot(HARDNESS).AndReturn(TEST_RETURN)
        api.server_get(IsA(http.HttpRequest), INSTANCE_ID).AndReturn(server)

        self.mox.ReplayAll()

        ret_val = api.server_reboot(self.request, INSTANCE_ID)
        self.assertIsNone(ret_val)

        ret_val = api.server_reboot(self.request, INSTANCE_ID,
                                    hardness=HARDNESS)
        self.assertIsNone(ret_val)

        self.mox.VerifyAll()


class ExtrasApiTests(test.TestCase):
    def stub_extras_api(self, count=1):
        self.mox.StubOutWithMock(api, 'extras_api')
        extras_api = self.mox.CreateMock(OSExtras.Extras)
        for i in range(count):
            api.extras_api(IsA(http.HttpRequest)).AndReturn(extras_api)
        return extras_api

    def test_get_extras_api(self):
        self.mox.StubOutClassWithMocks(OSExtras, 'Extras')
        OSExtras.Extras(auth_token=TEST_TOKEN, management_url=TEST_URL)

        self.mox.StubOutWithMock(api, 'url_for')
        api.url_for(IsA(http.HttpRequest), 'nova').AndReturn(TEST_URL)
        api.url_for(IsA(http.HttpRequest), 'nova').AndReturn(TEST_URL)

        self.mox.ReplayAll()

        self.assertIsNotNone(api.extras_api(self.request))

        self.mox.VerifyAll()

    def test_console_create(self):
        extras_api = self.stub_extras_api(count=2)
        extras_api.consoles = self.mox.CreateMockAnything()
        extras_api.consoles.create(
                TEST_INSTANCE_ID, TEST_CONSOLE_KIND).AndReturn(TEST_RETURN)
        extras_api.consoles.create(
                TEST_INSTANCE_ID, 'text').AndReturn(TEST_RETURN + '2')

        self.mox.ReplayAll()

        ret_val = api.console_create(self.request,
                                     TEST_INSTANCE_ID,
                                     TEST_CONSOLE_KIND)
        self.assertIsInstance(ret_val, api.Console)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        ret_val = api.console_create(self.request, TEST_INSTANCE_ID)
        self.assertIsInstance(ret_val, api.Console)
        self.assertEqual(ret_val._apiresource, TEST_RETURN + '2')

        self.mox.VerifyAll()

    def test_flavor_list(self):
        flavors = (TEST_RETURN, TEST_RETURN + '2')
        extras_api = self.stub_extras_api()
        extras_api.flavors = self.mox.CreateMockAnything()
        extras_api.flavors.list().AndReturn(flavors)

        self.mox.ReplayAll()

        ret_val = api.flavor_list(self.request)

        self.assertEqual(len(ret_val), len(flavors))
        for flavor in ret_val:
            self.assertIsInstance(flavor, api.Flavor)
            self.assertIn(flavor._apiresource, flavors)

        self.mox.VerifyAll()

    def test_keypair_create(self):
        NAME = '1'

        extras_api = self.stub_extras_api()
        extras_api.keypairs = self.mox.CreateMockAnything()
        extras_api.keypairs.create(NAME).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.keypair_create(self.request, NAME)
        self.assertIsInstance(ret_val, api.KeyPair)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_keypair_delete(self):
        KEYPAIR_ID = '1'

        extras_api = self.stub_extras_api()
        extras_api.keypairs = self.mox.CreateMockAnything()
        extras_api.keypairs.delete(KEYPAIR_ID).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.keypair_delete(self.request, KEYPAIR_ID)
        self.assertIsNone(ret_val)

        self.mox.VerifyAll()

    def test_keypair_list(self):
        NAME = 'keypair'
        keypairs = (NAME + '1', NAME + '2')

        extras_api = self.stub_extras_api()
        extras_api.keypairs = self.mox.CreateMockAnything()
        extras_api.keypairs.list().AndReturn(keypairs)

        self.mox.ReplayAll()

        ret_val = api.keypair_list(self.request)

        self.assertEqual(len(ret_val), len(keypairs))
        for keypair in ret_val:
            self.assertIsInstance(keypair, api.KeyPair)
            self.assertIn(keypair._apiresource, keypairs)

        self.mox.VerifyAll()

    def test_server_create(self):
        NAME = 'server'
        IMAGE = 'anImage'
        FLAVOR = 'cherry'
        USER_DATA = {'nuts': 'berries'}
        KEY = 'user'

        extras_api = self.stub_extras_api()
        extras_api.servers = self.mox.CreateMockAnything()
        extras_api.servers.create(NAME, IMAGE, FLAVOR, user_data=USER_DATA,
                                  key_name=KEY).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.server_create(self.request, NAME, IMAGE, FLAVOR,
                                    KEY, USER_DATA)

        self.assertIsInstance(ret_val, api.Server)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_server_list(self):
        servers = (TEST_RETURN, TEST_RETURN + '2')

        extras_api = self.stub_extras_api()

        extras_api.servers = self.mox.CreateMockAnything()
        extras_api.servers.list().AndReturn(servers)

        self.mox.ReplayAll()

        ret_val = api.server_list(self.request)

        self.assertEqual(len(ret_val), len(servers))
        for server in ret_val:
            self.assertIsInstance(server, api.Server)
            self.assertIn(server._apiresource, servers)

        self.mox.VerifyAll()

    def test_usage_get(self):
        extras_api = self.stub_extras_api()

        extras_api.usage = self.mox.CreateMockAnything()
        extras_api.usage.get(TEST_TENANT_ID, 'start',
                             'end').AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.usage_get(self.request, TEST_TENANT_ID, 'start', 'end')

        self.assertIsInstance(ret_val, api.Usage)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_usage_list(self):
        usages = (TEST_RETURN, TEST_RETURN + '2')

        extras_api = self.stub_extras_api()

        extras_api.usage = self.mox.CreateMockAnything()
        extras_api.usage.list('start', 'end').AndReturn(usages)

        self.mox.ReplayAll()

        ret_val = api.usage_list(self.request, 'start', 'end')

        self.assertEqual(len(ret_val), len(usages))
        for usage in ret_val:
            self.assertIsInstance(usage, api.Usage)
            self.assertIn(usage._apiresource, usages)

        self.mox.VerifyAll()

    def test_server_get(self):
        INSTANCE_ID = '2'

        extras_api = self.stub_extras_api()
        extras_api.servers = self.mox.CreateMockAnything()
        extras_api.servers.get(INSTANCE_ID).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.server_get(self.request, INSTANCE_ID)

        self.assertIsInstance(ret_val, api.Server)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()


class GlanceApiTests(test.TestCase):
    def stub_glance_api(self, count=1):
        self.mox.StubOutWithMock(api, 'glance_api')
        glance_api = self.mox.CreateMock(glance_client.Client)
        for i in range(count):
            api.glance_api(IsA(http.HttpRequest)).AndReturn(glance_api)
        return glance_api

    def test_get_glance_api(self):
        self.mox.StubOutClassWithMocks(glance_client, 'Client')
        glance_client.Client(TEST_HOSTNAME, TEST_PORT)

        self.mox.StubOutWithMock(api, 'url_for')
        api.url_for(IsA(http.HttpRequest), 'glance').AndReturn(TEST_URL)

        self.mox.ReplayAll()

        self.assertIsNotNone(api.glance_api(self.request))

        self.mox.VerifyAll()

    def test_image_create(self):
        IMAGE_FILE = 'someData'
        IMAGE_META = {'metadata': 'foo'}

        glance_api = self.stub_glance_api()
        glance_api.add_image(IMAGE_META, IMAGE_FILE).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.image_create(self.request, IMAGE_META, IMAGE_FILE)

        self.assertIsInstance(ret_val, api.Image)
        self.assertEqual(ret_val._apidict, TEST_RETURN)

        self.mox.VerifyAll()

    def test_image_delete(self):
        IMAGE_ID = '1'

        glance_api = self.stub_glance_api()
        glance_api.delete_image(IMAGE_ID).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.image_delete(self.request, IMAGE_ID)

        self.assertEqual(ret_val, TEST_RETURN)

        self.mox.VerifyAll()

    def test_image_get(self):
        IMAGE_ID = '1'

        glance_api = self.stub_glance_api()
        glance_api.get_image(IMAGE_ID).AndReturn([TEST_RETURN])

        self.mox.ReplayAll()

        ret_val = api.image_get(self.request, IMAGE_ID)

        self.assertIsInstance(ret_val, api.Image)
        self.assertEqual(ret_val._apidict, TEST_RETURN)

    def test_image_list_detailed(self):
        images = (TEST_RETURN, TEST_RETURN + '2')
        glance_api = self.stub_glance_api()
        glance_api.get_images_detailed().AndReturn(images)

        self.mox.ReplayAll()

        ret_val = api.image_list_detailed(self.request)

        self.assertEqual(len(ret_val), len(images))
        for image in ret_val:
            self.assertIsInstance(image, api.Image)
            self.assertIn(image._apidict, images)

        self.mox.VerifyAll()

    def test_image_update(self):
        IMAGE_ID = '1'
        IMAGE_META = {'metadata': 'foobar'}

        glance_api = self.stub_glance_api(count=2)
        glance_api.update_image(IMAGE_ID, image_meta={}).AndReturn(TEST_RETURN)
        glance_api.update_image(IMAGE_ID,
                                image_meta=IMAGE_META).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.image_update(self.request, IMAGE_ID)

        self.assertIsInstance(ret_val, api.Image)
        self.assertEqual(ret_val._apidict, TEST_RETURN)

        ret_val = api.image_update(self.request,
                                   IMAGE_ID,
                                   image_meta=IMAGE_META)

        self.assertIsInstance(ret_val, api.Image)
        self.assertEqual(ret_val._apidict, TEST_RETURN)

        self.mox.VerifyAll()


class SwiftApiTests(test.TestCase):
    def setUp(self):
        self.mox = mox.Mox()

        self.request = http.HttpRequest()
        self.request.session = dict()
        self.request.session['token'] = TEST_TOKEN

    def tearDown(self):
        self.mox.UnsetStubs()

    def stub_swift_api(self, count=1):
        self.mox.StubOutWithMock(api, 'swift_api')
        swift_api = self.mox.CreateMock(cloudfiles.connection.Connection)
        for i in range(count):
            api.swift_api(IsA(http.HttpRequest)).AndReturn(swift_api)
        return swift_api

    def test_swift_get_containers(self):
        containers = (TEST_RETURN, TEST_RETURN + '2')

        swift_api = self.stub_swift_api()

        swift_api.get_all_containers().AndReturn(containers)

        self.mox.ReplayAll()

        ret_val = api.swift_get_containers(self.request)

        self.assertEqual(len(ret_val), len(containers))
        for container in ret_val:
            self.assertIsInstance(container, api.Container)
            self.assertIn(container._apiresource, containers)

        self.mox.VerifyAll()

    def test_swift_create_container(self):
        NAME = 'containerName'

        swift_api = self.stub_swift_api()
        self.mox.StubOutWithMock(api, 'swift_container_exists')

        api.swift_container_exists(self.request,
                                   NAME).AndReturn(False)
        swift_api.create_container(NAME).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.swift_create_container(self.request, NAME)

        self.assertIsInstance(ret_val, api.Container)
        self.assertEqual(ret_val._apiresource, TEST_RETURN)

        self.mox.VerifyAll()

    def test_swift_delete_container(self):
        NAME = 'containerName'

        swift_api = self.stub_swift_api()

        swift_api.delete_container(NAME).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.swift_delete_container(self.request, NAME)

        self.assertIsNone(ret_val)

        self.mox.VerifyAll()

    def test_swift_get_objects(self):
        NAME = 'containerName'

        swift_objects = (TEST_RETURN, TEST_RETURN + '2')
        container = self.mox.CreateMock(cloudfiles.container.Container)
        container.get_objects(prefix=None).AndReturn(swift_objects)

        swift_api = self.stub_swift_api()

        swift_api.get_container(NAME).AndReturn(container)

        self.mox.ReplayAll()

        ret_val = api.swift_get_objects(self.request, NAME)

        self.assertEqual(len(ret_val), len(swift_objects))
        for swift_object in ret_val:
            self.assertIsInstance(swift_object, api.SwiftObject)
            self.assertIn(swift_object._apiresource, swift_objects)

        self.mox.VerifyAll()

    def test_swift_get_objects_with_prefix(self):
        NAME = 'containerName'
        PREFIX = 'prefacedWith'

        swift_objects = (TEST_RETURN, TEST_RETURN + '2')
        container = self.mox.CreateMock(cloudfiles.container.Container)
        container.get_objects(prefix=PREFIX).AndReturn(swift_objects)

        swift_api = self.stub_swift_api()

        swift_api.get_container(NAME).AndReturn(container)

        self.mox.ReplayAll()

        ret_val = api.swift_get_objects(self.request,
                                        NAME,
                                        prefix=PREFIX)

        self.assertEqual(len(ret_val), len(swift_objects))
        for swift_object in ret_val:
            self.assertIsInstance(swift_object, api.SwiftObject)
            self.assertIn(swift_object._apiresource, swift_objects)

        self.mox.VerifyAll()

    def test_swift_upload_object(self):
        CONTAINER_NAME = 'containerName'
        OBJECT_NAME = 'objectName'
        OBJECT_DATA = 'someData'

        swift_api = self.stub_swift_api()
        container = self.mox.CreateMock(cloudfiles.container.Container)
        swift_object = self.mox.CreateMock(cloudfiles.storage_object.Object)

        swift_api.get_container(CONTAINER_NAME).AndReturn(container)
        container.create_object(OBJECT_NAME).AndReturn(swift_object)
        swift_object.write(OBJECT_DATA).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.swift_upload_object(self.request,
                                          CONTAINER_NAME,
                                          OBJECT_NAME,
                                          OBJECT_DATA)

        self.assertIsNone(ret_val)

        self.mox.VerifyAll()

    def test_swift_delete_object(self):
        CONTAINER_NAME = 'containerName'
        OBJECT_NAME = 'objectName'

        swift_api = self.stub_swift_api()
        container = self.mox.CreateMock(cloudfiles.container.Container)

        swift_api.get_container(CONTAINER_NAME).AndReturn(container)
        container.delete_object(OBJECT_NAME).AndReturn(TEST_RETURN)

        self.mox.ReplayAll()

        ret_val = api.swift_delete_object(self.request,
                                          CONTAINER_NAME,
                                          OBJECT_NAME)

        self.assertIsNone(ret_val)

        self.mox.VerifyAll()

    def test_swift_get_object_data(self):
        CONTAINER_NAME = 'containerName'
        OBJECT_NAME = 'objectName'
        OBJECT_DATA = 'objectData'

        swift_api = self.stub_swift_api()
        container = self.mox.CreateMock(cloudfiles.container.Container)
        swift_object = self.mox.CreateMock(cloudfiles.storage_object.Object)

        swift_api.get_container(CONTAINER_NAME).AndReturn(container)
        container.get_object(OBJECT_NAME).AndReturn(swift_object)
        swift_object.stream().AndReturn(OBJECT_DATA)

        self.mox.ReplayAll()

        ret_val = api.swift_get_object_data(self.request,
                                            CONTAINER_NAME,
                                            OBJECT_NAME)

        self.assertEqual(ret_val, OBJECT_DATA)

        self.mox.VerifyAll()

    def test_swift_object_exists(self):
        CONTAINER_NAME = 'containerName'
        OBJECT_NAME = 'objectName'

        swift_api = self.stub_swift_api()
        container = self.mox.CreateMock(cloudfiles.container.Container)
        swift_object = self.mox.CreateMock(cloudfiles.Object)

        swift_api.get_container(CONTAINER_NAME).AndReturn(container)
        container.get_object(OBJECT_NAME).AndReturn(swift_object)

        self.mox.ReplayAll()

        ret_val = api.swift_object_exists(self.request,
                                          CONTAINER_NAME,
                                          OBJECT_NAME)
        self.assertTrue(ret_val)

        self.mox.VerifyAll()

    def test_swift_copy_object(self):
        CONTAINER_NAME = 'containerName'
        OBJECT_NAME = 'objectName'

        swift_api = self.stub_swift_api()
        container = self.mox.CreateMock(cloudfiles.container.Container)
        self.mox.StubOutWithMock(api, 'swift_object_exists')

        swift_object = self.mox.CreateMock(cloudfiles.Object)

        swift_api.get_container(CONTAINER_NAME).AndReturn(container)
        api.swift_object_exists(self.request,
                                CONTAINER_NAME,
                                OBJECT_NAME).AndReturn(False)

        container.get_object(OBJECT_NAME).AndReturn(swift_object)
        swift_object.copy_to(CONTAINER_NAME, OBJECT_NAME)

        self.mox.ReplayAll()

        ret_val = api.swift_copy_object(self.request, CONTAINER_NAME,
                                        OBJECT_NAME, CONTAINER_NAME,
                                        OBJECT_NAME)

        self.assertIsNone(ret_val)
        self.mox.VerifyAll()
