# Lint as: python2, python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.server.cros.servo import chrome_cr50


class ChromeTi50(chrome_cr50.ChromeCr50):
    """Manages control of a Chrome Ti50.

    We control the Chrome Ti50 via the console of a Servo board. Chrome Ti50
    provides many interfaces to set and get its behavior via console commands.
    This class is to abstract these interfaces.
    """
    # The version has four groups: the partition, the header version, debug
    # descriptor and then version string.
    # There are two partitions A and B. The active partition is marked with a
    # '*'. If it is a debug image '/DBG' is added to the version string. If the
    # image has been corrupted, the version information will be replaced with
    # 'Error'.
    # So the output may look something like this.
    #   RW_A:    0.0.11 ti50 common:v0.0.1734-e5675dd9
    #   RW_B:  * 0.0.11 ti50 common:v0.0.1734-e5675dd9
    # Or like this if the region was corrupted.
    #   RW_A:  * 0.0.11 ti50 common:v0.0.1734-e5675dd9
    #   RW_B:    Empty
    VERSION_FORMAT = '\nRW_(A|B): +%s +(\d+\.\d+\.\d+|Empty)(/DBG)?([\S ]+)?\s'

    def __init__(self, servo, faft_config):
        """Initializes a ChromeCr50 object.

        @param servo: A servo object.
        @param faft_config: A faft config object.
        """
        super(ChromeTi50, self).__init__(servo, 'cr50_uart')
        self.faft_config = faft_config
