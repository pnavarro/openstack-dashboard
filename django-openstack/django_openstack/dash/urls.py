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

from django.conf.urls.defaults import *

INSTANCES = r'^(?P<tenant_id>[^/]+)/instances/(?P<instance_id>[^/]+)/%s$'
IMAGES = r'^(?P<tenant_id>[^/]+)/images/(?P<image_id>[^/]+)/%s$'
KEYPAIRS = r'^(?P<tenant_id>[^/]+)/keypairs/%s$'
SNAPSHOTS = r'^(?P<tenant_id>[^/]+)/snapshots/(?P<instance_id>[^/]+)/%s$'
CONTAINERS = r'^(?P<tenant_id>[^/]+)/containers/%s$'
OBJECTS = r'^(?P<tenant_id>[^/]+)/containers/(?P<container_name>[^/]+)/%s$'

urlpatterns = patterns('django_openstack.dash.views.instances',
    url(r'^(?P<tenant_id>[^/]+)/$', 'usage', name='dash_usage'),
    url(r'^(?P<tenant_id>[^/]+)/instances/$', 'index', name='dash_instances'),
    url(r'^(?P<tenant_id>[^/]+)/instances/refresh$', 'refresh', name='dash_instances_refresh'),
    url(INSTANCES % 'console', 'console', name='dash_instances_console'),
    url(INSTANCES % 'vnc', 'vnc', name='dash_instances_vnc'),
    url(INSTANCES % 'update', 'update', name='dash_instances_update'),
)

urlpatterns += patterns('django_openstack.dash.views.images',
    url(r'^(?P<tenant_id>[^/]+)/images/$', 'index', name='dash_images'),
    url(IMAGES % 'launch', 'launch', name='dash_images_launch'),
)

urlpatterns += patterns('django_openstack.dash.views.keypairs',
    url(r'^(?P<tenant_id>[^/]+)/keypairs/$', 'index', name='dash_keypairs'),
    url(KEYPAIRS % 'create', 'create', name='dash_keypairs_create'),
)

urlpatterns += patterns('django_openstack.dash.views.snapshots',
    url(r'^(?P<tenant_id>[^/]+)/snapshots/$', 'index', name='dash_snapshots'),
    url(SNAPSHOTS % 'create', 'create', name='dash_snapshots_create'),
)

# Swift containers and objects.
urlpatterns += patterns('django_openstack.dash.views.containers',
    url(CONTAINERS % '', 'index', name='dash_containers'),
    url(CONTAINERS % 'create', 'create', name='dash_containers_create'),
)

urlpatterns += patterns('django_openstack.dash.views.objects',
    url(OBJECTS % '', 'index', name='dash_objects'),
    url(OBJECTS % 'upload', 'upload', name='dash_objects_upload'),
    url(OBJECTS % '(?P<object_name>[^/]+)/copy',
        'copy', name='dash_object_copy'),
    url(OBJECTS % '(?P<object_name>[^/]+)/download',
        'download', name='dash_objects_download'),
)
