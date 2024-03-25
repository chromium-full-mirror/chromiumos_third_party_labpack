#!/usr/bin/python2
# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import six.moves.builtins
import mox
import os
import unittest
import time
from six import StringIO

import utils


class TestUtils(mox.MoxTestBase):
    """Test utility functions."""

    def test_LRU_cache(self):
        """Test LRUCache."""
        p1 = utils.PowerUnitInfo('host1',
                                 utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                                 'rpm1', 'hydra1')
        p2 = utils.PowerUnitInfo('host2',
                                 utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                                 'rpm2', 'hydra2')
        p3 = utils.PowerUnitInfo('host3',
                                 utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                                 'rpm3', 'hydra3')
        # Initialize an LRU with size 2, items never expire.
        cache = utils.LRUCache(2, expiration_secs=None)
        # Add two items, LRU should be full now
        cache['host1'] = p1
        cache['host2'] = p2
        self.assertEqual(len(cache.cache), 2)
        # Visit host2 and add one more item
        # host1 should be removed from cache
        _ = cache['host2']
        cache['host3'] = p3
        self.assertEqual(len(cache.cache), 2)
        self.assertTrue('host1' not in cache)
        self.assertTrue('host2' in cache)
        self.assertTrue('host3' in cache)

    def test_LRU_cache_expires(self):
        """Test LRUCache expires."""
        self.mox.StubOutWithMock(time, 'time')
        time.time().AndReturn(10)
        time.time().AndReturn(25)
        p1 = utils.PowerUnitInfo('host1',
                                 utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                                 'rpm1', 'hydra1')

        self.mox.ReplayAll()
        # Initialize an LRU with size 1, items exppire after 10 secs.
        cache = utils.LRUCache(1, expiration_secs=10)
        # Add two items, LRU should be full now
        cache['host1'] = p1
        check_contains_1 = 'host1' in cache
        check_contains_2 = 'host2' in cache
        self.mox.VerifyAll()
        self.assertFalse(check_contains_1)
        self.assertFalse(check_contains_2)

    def test_LRU_cache_full_with_expries(self):
        """Test timestamp is removed properly when cache is full."""
        self.mox.StubOutWithMock(time, 'time')
        time.time().AndReturn(10)
        time.time().AndReturn(25)
        p1 = utils.PowerUnitInfo('host1',
                                 utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                                 'rpm1', 'hydra1')
        p2 = utils.PowerUnitInfo('host2',
                                 utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                                 'rpm2', 'hydra2')
        self.mox.ReplayAll()
        # Initialize an LRU with size 1, items expire after 10 secs.
        cache = utils.LRUCache(1, expiration_secs=10)
        # Add two items, LRU should be full now
        cache['host1'] = p1
        cache['host2'] = p2
        self.mox.VerifyAll()
        self.assertEqual(len(cache.timestamps), 1)
        self.assertEqual(len(cache.cache), 1)
        self.assertTrue('host2' in cache.timestamps)
        self.assertTrue('host2' in cache.cache)


if __name__ == '__main__':
    unittest.main()
