#!/usr/bin/env python2
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

from autotest_lib.site_utils.admin_audit import constants


class BluetoothValidator(object):
    """BluetoothValidator does bluetooth detection on the host.

    The values for bluetooth state are:
    - NORMAL - bluetooth detected on the host.
    - NOT_DETECTED - the host does not carry bluetooth.
    - UNKNOWN - verification failed, or was blocked while checking the
    presence of bluetooth on the host.
    - NEED_REPLACEMENT - bluetooth is expected but not detected on the
    device.
    """

    # Command to check whether the bluetooth device is powered-on and
    # responsive on system DBus.
    _BLUETOOTH_DETECTION_CMD = ('dbus-send --print-reply --system '
                                '--dest=org.bluez /org/bluez/hci0 '
                                'org.freedesktop.DBus.Properties.Get '
                                'string:"org.bluez.Adapter1" string:"Powered"')

    # the timeout in seconds for bluetooth detection command
    _BLUETOOTH_DETECTION_TIMEOUT = 60

    # the label for bluetooth in host-info data.
    _BLUETOOTH_LABEL = 'bluetooth'

    def __init__(self, host):
        """Initialize the bluetooth validator.

        @params host CrosHost instance.
        """
        self._host = host

    def is_bluetooth_expected(self):
        """
        Check if bluetooth is expected on the device based on host-info.

        @returns:  bool, True if bluetooth is expected, otherwise False
        """
        host_info = self._host.host_info_store.get()
        return host_info.has_label(self._BLUETOOTH_LABEL)

    def validate(self):
        """Validate bluetooth and update state.

        Detect if the bluetooth adaptor is powered-on, and is responding
        on the system DBus.
        """
        state = constants.HW_STATE_UNKNOWN
        try:
            result = self._host.run(self._BLUETOOTH_DETECTION_CMD,
                                    ignore_status=True,
                                    timeout=self._BLUETOOTH_DETECTION_TIMEOUT)
        except Exception as e:
            logging.debug('(Not critical) %s', e)
        else:
            if result:
                if result.exit_status == 0:
                    # dbus-send command completed with success
                    lines = result.stdout.splitlines()
                    if len(lines) == 2:
                        if lines[-1].split() == ['variant', 'boolean', 'true']:
                            state = constants.HW_STATE_NORMAL
                else:
                    # If bluetooth is not detected, but was expected by setup
                    # info then we set needs_replacement as it is probably
                    # a hardware issue
                    if self.is_bluetooth_expected():
                        state = constants.HW_STATE_NEED_REPLACEMENT
                    else:
                        state = constants.HW_STATE_NOT_DETECTED
        return self._update_host_info(state)

    def _update_host_info(self, state):
        """Update state value of bluetooth_state in the host_info

        @param state: new state value for the label
        """
        if self._host:
            state_prefix = constants.BLUETOOTH_STATE_PREFIX
            host_info = self._host.host_info_store.get()
            old_state = host_info.get_label_value(state_prefix)
            host_info.set_version_label(state_prefix, state)
            logging.debug('Set %s as `%s` (previous: `%s`)', state_prefix,
                          state, old_state)
            self._host.host_info_store.commit(host_info)
        return state
