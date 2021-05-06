#!/usr/bin/env python2
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

from autotest_lib.site_utils.admin_audit import constants


class WifiValidator(object):
    """WifiValidator does wifi chip detection on the host.

    The values for wifi state are:
    - NORMAL - wifi chip detected on the host.
    - NOT_DETECTED - the host does not carry wifi device.
    - UNKNOWN - verification failed, or was blocked while checking the
    presence of wifi device on the host.
    - NEED_REPLACEMENT - wifi chip is expected but not detected on the
    device.
    """

    # command to check whether the wifi device has been recognized and
    # its device driver been loaded by the kernel.
    _WIFI_DETECTION_CMD = 'lspci -vvn | grep iwlwifi'

    # the timeout in seconds for wifi detection command
    _WIFI_DETECTION_TIMEOUT = 60

    def __init__(self, host):
        """Initialize the wifi validator.

        @params host CrosHost instance.
        """
        self._host = host

    def is_wifi_expected(self):
        """
        Check if a wifi chip is expected on the device based on host-info.

        @returns:  bool, True if chip is expected, otherwise False
        """
        host_info = self._host.host_info_store.get()
        return host_info.has_label('wifi_chip')

    def validate(self):
        """Validate the wifi chip and update state.

        Detect if the DUT has wifi device listed in the output of 'lspci'
        command.
        """
        state = constants.HW_STATE_UNKNOWN
        try:
            result = self._host.run(self._WIFI_DETECTION_CMD,
                                    ignore_status=True,
                                    timeout=self._WIFI_DETECTION_TIMEOUT)
        except Exception as e:
            logging.debug('(Not critical) %s', e)
        else:
            if result:
                if result.exit_status == 0:
                    # successfully detected
                    state = constants.HW_STATE_NORMAL
                else:
                    # If wifi chip is not detected, but was expected by setup
                    # info then we set needs_replacement as it is probably
                    # a hardware issue
                    if self.is_wifi_expected():
                        state = constants.HW_STATE_NEED_REPLACEMENT
                    else:
                        state = constants.HW_STATE_NOT_DETECTED
        return self._update_host_info(state)

    def _update_host_info(self, state):
        """Update state value of wifi_state in the host_info

        @param state: new state value for the label
        """
        if self._host:
            state_prefix = constants.WIFI_STATE_PREFIX
            host_info = self._host.host_info_store.get()
            old_state = host_info.get_label_value(state_prefix)
            host_info.set_version_label(state_prefix, state)
            logging.debug('Set %s as `%s` (previous: `%s`)', state_prefix,
                          state, old_state)
            self._host.host_info_store.commit(host_info)
        return state
