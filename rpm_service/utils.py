# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""This file provides util functions used by RPM infrastructure."""

import collections
import csv
import logging
import os
import time

import rpm_infrastructure_exception
from config import rpm_config
import autotest_enum

POWERUNIT_HOSTNAME_KEY = 'powerunit_hostname'
POWERUNIT_OUTLET_KEY = 'powerunit_outlet'
HYDRA_HOSTNAME_KEY = 'hydra_hostname'
DEFAULT_EXPIRATION_SECS = 60 * 30


class PowerUnitInfo(object):
    """A class that wraps rpm information of a device."""

    POWERUNIT_TYPES = autotest_enum.AutotestEnum('RPM',
                                                 string_value=True)

    def __init__(self,
                 device_hostname,
                 powerunit_type,
                 powerunit_hostname,
                 outlet,
                 hydra_hostname=None):
        self.device_hostname = device_hostname
        self.powerunit_type = powerunit_type
        self.powerunit_hostname = powerunit_hostname
        self.outlet = outlet
        self.hydra_hostname = hydra_hostname


class LRUCache(object):
    """A simple implementation of LRU Cache."""

    def __init__(self, size, expiration_secs=DEFAULT_EXPIRATION_SECS):
        """Initialize.

        @param size: Size of the cache.
        @param expiration_secs: The items expire after |expiration_secs|
                                Set to None so that items never expire.
                                Default to DEFAULT_EXPIRATION_SECS.
        """
        self.size = size
        self.cache = collections.OrderedDict()
        self.timestamps = {}
        self.expiration_secs = expiration_secs

    def __getitem__(self, key):
        """Get an item from the cache"""
        # pop and insert the element again so that it
        # is moved to the end.
        value = self.cache.pop(key)
        self.cache[key] = value
        return value

    def __setitem__(self, key, value):
        """Insert an item into the cache."""
        if key in self.cache:
            self.cache.pop(key)
        elif len(self.cache) == self.size:
            removed_key, _ = self.cache.popitem(last=False)
            self.timestamps.pop(removed_key)
        self.cache[key] = value
        self.timestamps[key] = time.time()

    def __contains__(self, key):
        """Check whether a key is in the cache."""
        if (
                self.expiration_secs is not None and key in self.timestamps
                and time.time() - self.timestamps[key] > self.expiration_secs):
            self.cache.pop(key)
            self.timestamps.pop(key)
        return key in self.cache
