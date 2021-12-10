#!/usr/bin/python2
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import mox
import pexpect
import unittest

import rpm_controller
import utils


class TestRPMControllerQueue(mox.MoxTestBase):
    """Test request can be queued and processed in controller."""

    def setUp(self):
        super(TestRPMControllerQueue, self).setUp()
        self.rpm = rpm_controller.SentryRPMController('chromeos-rack1-host8')
        self.powerunit_info = utils.PowerUnitInfo(
                device_hostname='chromos-rack1-host8',
                powerunit_hostname='chromeos-rack1-rpm1',
                powerunit_type=utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                outlet='.A100',
                hydra_hostname=None)

    def testQueueRequest(self):
        """Should create a new process to handle request."""
        new_state = 'ON'
        process = self.mox.CreateMockAnything()
        rpm_controller.multiprocessing.Process = self.mox.CreateMockAnything()
        rpm_controller.multiprocessing.Process(
                target=mox.IgnoreArg(),
                args=mox.IgnoreArg()).AndReturn(process)
        process.start()
        process.join()
        self.mox.ReplayAll()
        self.assertFalse(self.rpm.queue_request(self.powerunit_info,
                                                new_state))
        self.mox.VerifyAll()


class TestSentryRPMController(mox.MoxTestBase):
    """Test SentryRPMController."""

    def setUp(self):
        super(TestSentryRPMController, self).setUp()
        self.ssh = self.mox.CreateMockAnything()
        rpm_controller.pexpect.spawn = self.mox.CreateMockAnything()
        rpm_controller.pexpect.spawn(mox.IgnoreArg()).AndReturn(self.ssh)
        self.rpm = rpm_controller.SentryRPMController('chromeos-rack1-host8')
        self.powerunit_info = utils.PowerUnitInfo(
                device_hostname='chromos-rack1-host8',
                powerunit_hostname='chromeos-rack1-rpm1',
                powerunit_type=utils.PowerUnitInfo.POWERUNIT_TYPES.RPM,
                outlet='.A100',
                hydra_hostname=None)

    def testSuccessfullyChangeOutlet(self):
        """Should return True if change was successful."""
        prompt = ['Switched CDU:', 'Switched PDU:', 'password:', 'Password:']
        password = 'admn'
        new_state = 'ON'
        self.ssh.expect('Password:', timeout=60)
        self.ssh.sendline(password)
        self.ssh.expect(prompt, timeout=60)
        self.ssh.sendline('%s %s' % (new_state, self.powerunit_info.outlet))
        self.ssh.expect('Command successful', timeout=60)
        self.ssh.sendline('logout')
        self.ssh.close(force=True)
        self.mox.ReplayAll()
        self.assertTrue(
                self.rpm.set_power_state(self.powerunit_info, new_state))
        self.mox.VerifyAll()

    def testUnsuccessfullyChangeOutlet(self):
        """Should return False if change was unsuccessful."""
        prompt = ['Switched CDU:', 'Switched PDU:', 'password:', 'Password:']
        password = 'admn'
        new_state = 'ON'
        self.ssh.expect('Password:', timeout=60)
        self.ssh.sendline(password)
        self.ssh.expect(prompt, timeout=60)
        self.ssh.sendline('%s %s' % (new_state, self.powerunit_info.outlet))
        self.ssh.expect('Command successful',
                        timeout=60).AndRaise(pexpect.TIMEOUT('Timed Out'))
        self.ssh.sendline('logout')
        self.ssh.close(force=True)
        self.mox.ReplayAll()
        self.assertFalse(
                self.rpm.set_power_state(self.powerunit_info, new_state))
        self.mox.VerifyAll()


if __name__ == "__main__":
    unittest.main()
