# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ctypes
import datetime
import logging
import multiprocessing
import os
import pexpect
import six.moves.queue
import re
import threading
import time

from config import rpm_config
import rpm_logging_config
import retry
import error
from six.moves import range

RPM_CALL_TIMEOUT_MINS = rpm_config.getint('RPM_INFRASTRUCTURE',
                                          'call_timeout_mins')
SET_POWER_STATE_TIMEOUT_SECONDS = rpm_config.getint(
        'RPM_INFRASTRUCTURE', 'set_power_state_timeout_seconds')
PROCESS_TIMEOUT_BUFFER = 30


class RPMController(object):
    """
    This abstract class implements RPM request queueing and
    processes queued requests.

    The actual interaction with the RPM device will be implemented
    by the RPM specific subclasses.

    It assumes that you know the RPM hostname and that the device is on
    the specified RPM.

    This class also allows support for RPM devices that can be accessed
    directly or through a hydra serial concentrator device.

    Implementation details:
    This is an abstract class, subclasses must implement the methods
    listed here. You must not instantiate this class but should
    instantiate one of those leaf subclasses. Subclasses should
    also set TYPE class attribute to indicate device type.

    @var behind_hydra: boolean value to represent whether or not this RPM is
                        behind a hydra device.
    @var hostname: hostname for this rpm device.
    @var is_running_lock: lock used to control access to _running.
    @var request_queue: queue used to store requested outlet state changes.
    @var queue_lock: lock used to control access to request_queue.
    @var _running: boolean value to represent if this controller is currently
                   looping over queued requests.
    """

    SSH_LOGIN_CMD = ('ssh -l %s -o StrictHostKeyChecking=no '
                     '-o ConnectTimeout=90 -o UserKnownHostsFile=/dev/null %s')
    USERNAME_PROMPT = 'Username:'
    HYRDA_RETRY_SLEEP_SECS = 10
    HYDRA_MAX_CONNECT_RETRIES = 3
    LOGOUT_CMD = 'logout'
    CLI_CMD = 'CLI'
    CLI_HELD = r'The administrator \[root\] has an active .* session.'
    CLI_KILL_PREVIOUS = 'cancel'
    CLI_PROMPT = 'cli>'
    HYDRA_PROMPT = '#'
    PORT_STATUS_CMD = 'portStatus'
    QUIT_CMD = 'quit'
    SESSION_KILL_CMD_FORMAT = 'administration sessions kill %s'
    HYDRA_CONN_HELD_MSG_FORMAT = 'is being used'
    CYCLE_SLEEP_TIME = 5

    # Global Variables that will likely be changed by subclasses.
    DEVICE_PROMPT = '$'
    PASSWORD_PROMPT = 'Password:'
    # The state change command can be any string format but must accept 2 vars:
    # state followed by device/Plug name.
    SET_STATE_CMD = '%s %s'
    SUCCESS_MSG = None  # Some RPM's may not return a success msg.

    NEW_STATE_ON = 'ON'
    NEW_STATE_OFF = 'OFF'
    NEW_STATE_CYCLE = 'CYCLE'
    TYPE = 'Should set TYPE in subclass.'

    def __init__(self, rpm_hostname, hydra_hostname=None):
        """
        RPMController Constructor.
        To be called by subclasses.

        @param rpm_hostname: hostname of rpm device to be controlled.
        """
        self._dns_zone = os.environ.get('DOCKER_DUT_DNS_ZONE')
        if not self._dns_zone:
            # Use default zone if not specified in env var.
            self._dns_zone = rpm_config.get('CROS', 'dns_zone')
        self.hostname = rpm_hostname
        self.request_queue = six.moves.queue.Queue()
        self._running = False
        self.is_running_lock = threading.Lock()
        # If a hydra name is provided by the subclass then we know we are
        # talking to an rpm behind a hydra device.
        self.hydra_hostname = hydra_hostname if hydra_hostname else None
        self.behind_hydra = type(hydra_hostname) is str and len(
                hydra_hostname) > 0

    def _start_processing_requests(self):
        """
        Check if there is a thread processing requests.
        If not start one.
        """
        with self.is_running_lock:
            if not self._running:
                self._running = True
                self._running_thread = threading.Thread(target=self._run)
                self._running_thread.start()

    def _stop_processing_requests(self):
        """
        Called if the request request_queue is empty.
        Set running status to false.
        """
        with self.is_running_lock:
            logging.debug(
                    'Request queue is empty. RPM Controller for %s'
                    ' is terminating.', self.hostname)
            self._running = False
        if not self.request_queue.empty():
            # This can occur if an item was pushed into the queue after we
            # exited the while-check and before the _stop_processing_requests
            # call was made. Therefore we need to start processing again.
            self._start_processing_requests()

    def _run(self):
        """
        Processes all queued up requests for this RPM Controller.
        Callers should first request_queue up atleast one request and if this
        RPM Controller is not running then call run.

        Caller can either simply call run but then they will be blocked or
        can instantiate a new thread to process all queued up requests.
        For example:
          threading.Thread(target=rpm_controller.run).start()

        Requests are in the format of:
          [powerunit_info, new_state, condition_var, result]
        Run will set the result with the correct value.
        """
        while not self.request_queue.empty():
            try:
                result = multiprocessing.Value(ctypes.c_bool, False)
                request = self.request_queue.get()
                device_hostname = request['powerunit_info'].device_hostname
                if (datetime.datetime.utcnow() >
                    (request['start_time'] +
                     datetime.timedelta(minutes=RPM_CALL_TIMEOUT_MINS))):
                    logging.error('The request was waited for too long to be '
                                  "processed. It is timed out and won't be "
                                  'processed.')
                    request['result_queue'].put(False)
                    continue

                is_timeout = multiprocessing.Value(ctypes.c_bool, False)
                process = multiprocessing.Process(target=self._process_request,
                                                  args=(request, result,
                                                        is_timeout))
                process.start()
                process.join(SET_POWER_STATE_TIMEOUT_SECONDS +
                             PROCESS_TIMEOUT_BUFFER)
                if process.is_alive():
                    logging.debug(
                            '%s: process (%s) still running, will be '
                            'terminated!', device_hostname, process.pid)
                    process.terminate()
                    is_timeout.value = True

                if is_timeout.value:
                    raise error.TimeoutException(
                            'Attempt to set power state is timed out after %s '
                            'seconds.' % SET_POWER_STATE_TIMEOUT_SECONDS)
                if not result.value:
                    logging.error('Request to change %s to state %s failed.',
                                  device_hostname, request['new_state'])
            except Exception as e:
                logging.error(
                        'Request to change %s to state %s failed: '
                        'Raised exception: %s', device_hostname,
                        request['new_state'], e)
                result.value = False

            # Put result inside the result Queue to allow the caller to resume.
            request['result_queue'].put(result.value)
        self._stop_processing_requests()

    def _process_request(self, request, result, is_timeout):
        """Process the request to change a device's outlet state.

        The call of set_power_state is made in a new running process. If it
        takes longer than SET_POWER_STATE_TIMEOUT_SECONDS, the request will be
        timed out.

        @param request: A request to change a device's outlet state.
        @param result: A Value object passed to the new process for the caller
                       thread to retrieve the result.
        @param is_timeout: A Value object passed to the new process for the
                           caller thread to retrieve the information about if
                           the set_power_state call timed out.
        """
        try:
            logging.getLogger().handlers = []
            is_timeout_value, result_value = retry.timeout(
                    rpm_logging_config.set_up_logging_to_server,
                    timeout_sec=10)
            if is_timeout_value:
                raise Exception('Setup local log server handler timed out.')
        except Exception as e:
            # Fail over to log to a new file.
            LOG_FILENAME_FORMAT = rpm_config.get('GENERAL',
                                                 'dispatcher_logname_format')
            log_filename_format = LOG_FILENAME_FORMAT.replace(
                    'dispatcher', 'controller_%d' % os.getpid())
            logging.getLogger().handlers = []
            rpm_logging_config.set_up_logging_to_file(
                    log_dir='./logs', log_filename_format=log_filename_format)
            logging.info('Failed to set up logging through log server: %s', e)
        kwargs = {
                'powerunit_info': request['powerunit_info'],
                'new_state': request['new_state']
        }
        try:
            is_timeout_value, result_value = retry.timeout(
                    self.set_power_state,
                    args=(),
                    kwargs=kwargs,
                    timeout_sec=SET_POWER_STATE_TIMEOUT_SECONDS)
            result.value = result_value
            is_timeout.value = is_timeout_value
        except Exception as e:
            # This method runs in a subprocess. Must log the exception,
            # otherwise exceptions raised in set_power_state just get lost.
            # Need to convert e to a str type, because our logging server
            # code doesn't handle the conversion very well.
            logging.error(
                    'Request to change %s to state %s failed: '
                    'Raised exception: %s',
                    request['powerunit_info'].device_hostname,
                    request['new_state'], str(e))
            raise e

    def queue_request(self, powerunit_info, new_state):
        """
        Queues up a requested state change for a device's outlet.

        Requests are in the format of:
          [powerunit_info, new_state, condition_var, result]
        Run will set the result with the correct value.

        @param powerunit_info: And PowerUnitInfo instance.
        @param new_state: ON/OFF/CYCLE - state or action we want to perform on
                          the outlet.
        """
        request = {}
        request['powerunit_info'] = powerunit_info
        request['new_state'] = new_state
        request['start_time'] = datetime.datetime.utcnow()
        # Reserve a spot for the result to be stored.
        request['result_queue'] = six.moves.queue.Queue()
        # Place in request_queue
        self.request_queue.put(request)
        self._start_processing_requests()
        # Block until the request is processed.
        result = request['result_queue'].get(block=True)
        return result

    def _kill_previous_connection(self):
        """
        In case the port to the RPM through the hydra serial concentrator is in
        use, terminate the previous connection so we can log into the RPM.

        It logs into the hydra serial concentrator over ssh, launches the CLI
        command, gets the port number and then kills the current session.
        """
        ssh = self._authenticate_with_hydra(admin_override=True)
        if not ssh:
            return
        ssh.expect(RPMController.PASSWORD_PROMPT, timeout=60)
        ssh.sendline(rpm_config.get('HYDRA', 'admin_password'))
        ssh.expect(RPMController.HYDRA_PROMPT)
        ssh.sendline(RPMController.CLI_CMD)
        cli_prompt_re = re.compile(RPMController.CLI_PROMPT)
        cli_held_re = re.compile(RPMController.CLI_HELD)
        response = ssh.expect_list([cli_prompt_re, cli_held_re], timeout=60)
        if response == 1:
            # Need to kill the previous adminstator's session.
            logging.error(
                    "Need to disconnect previous administrator's CLI "
                    "session to release the connection to RPM device %s.",
                    self.hostname)
            ssh.sendline(RPMController.CLI_KILL_PREVIOUS)
            ssh.expect(RPMController.CLI_PROMPT)
        ssh.sendline(RPMController.PORT_STATUS_CMD)
        ssh.expect(': %s' % self.hostname)
        ports_status = ssh.before
        port_number = ports_status.split(' ')[-1]
        ssh.expect(RPMController.CLI_PROMPT)
        ssh.sendline(RPMController.SESSION_KILL_CMD_FORMAT % port_number)
        ssh.expect(RPMController.CLI_PROMPT)
        self._logout(ssh, admin_logout=True)

    def _hydra_login(self, ssh):
        """
        Perform the extra steps required to log into a hydra serial
        concentrator.

        @param ssh: pexpect.spawn object used to communicate with the hydra
                    serial concentrator.

        @return: True if the login procedure is successful. False if an error
                 occurred. The most common case would be if another user is
                 logged into the device.
        """
        try:
            response = ssh.expect_list([
                    re.compile(RPMController.PASSWORD_PROMPT),
                    re.compile(RPMController.HYDRA_CONN_HELD_MSG_FORMAT)
            ],
                                       timeout=15)
        except pexpect.TIMEOUT:
            # If there was a timeout, this ssh tunnel could be set up to
            # not require the hydra password.
            ssh.sendline('')
            try:
                ssh.expect(re.compile(RPMController.USERNAME_PROMPT))
                logging.debug('Connected to rpm through hydra. Logging in.')
                return True
            except pexpect.ExceptionPexpect:
                return False
        if response == 0:
            try:
                ssh.sendline(rpm_config.get('HYDRA', 'password'))
                ssh.sendline('')
                response = ssh.expect_list([
                        re.compile(RPMController.USERNAME_PROMPT),
                        re.compile(RPMController.HYDRA_CONN_HELD_MSG_FORMAT)
                ],
                                           timeout=60)
            except pexpect.EOF:
                # Did not receive any of the expect responses, retry.
                return False
            except pexpect.TIMEOUT:
                logging.debug('Timeout occurred logging in to hydra.')
                return False
        # Send the username that the subclass will have set in its
        # construction.
        if response == 1:
            logging.debug('SSH Terminal most likely serving another'
                          ' connection, retrying.')
            # Kill the connection for the next connection attempt.
            try:
                self._kill_previous_connection()
            except pexpect.ExceptionPexpect:
                logging.error('Failed to disconnect previous connection, '
                              'retrying.')
                raise
            return False
        logging.debug('Connected to rpm through hydra. Logging in.')
        return True

    def _authenticate_with_hydra(self, admin_override=False):
        """
        Some RPM's are behind a hydra serial concentrator and require their ssh
        connection to be tunneled through this device. This can fail if another
        user is logged in; therefore this will retry multiple times.

        This function also allows us to authenticate directly to the
        administrator interface of the hydra device.

        @param admin_override: Set to True if we are trying to access the
                               administrator interface rather than tunnel
                               through to the RPM.

        @return: The connected pexpect.spawn instance if the login procedure is
                 successful. None if an error occurred. The most common case
                 would be if another user is logged into the device.
        """
        if admin_override:
            username = rpm_config.get('HYDRA', 'admin_username')
        else:
            username = '%s:%s' % (rpm_config.get('HYDRA',
                                                 'username'), self.hostname)
        cmd = RPMController.SSH_LOGIN_CMD % (username, self.hydra_hostname)
        num_attempts = 0
        while num_attempts < RPMController.HYDRA_MAX_CONNECT_RETRIES:
            try:
                ssh = pexpect.spawn(cmd)
            except pexpect.ExceptionPexpect:
                return None
            if admin_override:
                return ssh
            if self._hydra_login(ssh):
                return ssh
            # Authenticating with hydra failed. Sleep then retry.
            time.sleep(RPMController.HYRDA_RETRY_SLEEP_SECS)
            num_attempts += 1
        logging.error(
                'Failed to connect to the hydra serial concentrator after'
                ' %d attempts.', RPMController.HYDRA_MAX_CONNECT_RETRIES)
        return None

    def _login(self):
        """
        Log in into the RPM Device, should be implemented in each subclass.

        The login process should be able to connect to the device whether or not
        it is behind a hydra serial concentrator.

        @return: ssh - a pexpect.spawn instance if the connection was successful
                 or None if it was not.
        """
        raise NotImplementedError

    def _logout(self, ssh, admin_logout=False):
        """
        Log out of the RPM device.

        Send the device specific logout command and if the connection is through
        a hydra serial concentrator, kill the ssh connection.

        @param admin_logout: Set to True if we are trying to logout of the
                             administrator interface of a hydra serial
                             concentrator, rather than an RPM.
        @param ssh: pexpect.spawn instance to use to send the logout command.
        """
        if admin_logout:
            ssh.sendline(RPMController.QUIT_CMD)
            ssh.expect(RPMController.HYDRA_PROMPT)
        ssh.sendline(self.LOGOUT_CMD)
        if self.behind_hydra and not admin_logout:
            # Terminate the hydra session.
            ssh.sendline('~.')
            # Wait a bit so hydra disconnects completely. Launching another
            # request immediately can cause a timeout.
            time.sleep(5)

    def set_power_state(self, powerunit_info, new_state):
        """
        Set the state of the dut's outlet on this RPM.

        For ssh based devices, this will create the connection either directly
        or through a hydra tunnel and call the underlying _change_state function
        to be implemented by the subclass device.

        For non-ssh based devices, this method should be overloaded with the
        proper connection and state change code. And the subclass will handle
        accessing the RPM devices.

        @param powerunit_info: An instance of PowerUnitInfo.
        @param new_state: ON/OFF/CYCLE - state or action we want to perform on
                          the outlet.

        @return: True if the attempt to change power state was successful,
                 False otherwise.
        """
        ssh = self._login()
        if not ssh:
            return False
        if new_state == self.NEW_STATE_CYCLE:
            logging.debug('Beginning Power Cycle for device: %s',
                          powerunit_info.device_hostname)
            result = self._change_state(powerunit_info, self.NEW_STATE_OFF,
                                        ssh)
            if not result:
                return result
            time.sleep(RPMController.CYCLE_SLEEP_TIME)
            result = self._change_state(powerunit_info, self.NEW_STATE_ON, ssh)
        else:
            # Try to change the state of the device's power outlet.
            result = self._change_state(powerunit_info, new_state, ssh)

        # Terminate hydra connection if necessary.
        self._logout(ssh)
        ssh.close(force=True)
        return result

    def _change_state(self, powerunit_info, new_state, ssh):
        """
        Perform the actual state change operation.

        Once we have established communication with the RPM this method is
        responsible for changing the state of the RPM outlet.

        @param powerunit_info: An instance of PowerUnitInfo.
        @param new_state: ON/OFF - state or action we want to perform on
                          the outlet.
        @param ssh: The ssh connection used to execute the state change commands
                    on the RPM device.

        @return: True if the attempt to change power state was successful,
                 False otherwise.
        """
        outlet = powerunit_info.outlet
        device_hostname = powerunit_info.device_hostname
        if not outlet:
            logging.error(
                    'Request to change outlet for device: %s to new '
                    'state %s failed: outlet is unknown, please '
                    'make sure POWERUNIT_OUTLET exist in the host\'s '
                    'attributes in afe.', device_hostname, new_state)
        ssh.sendline(self.SET_STATE_CMD % (new_state, outlet))
        if self.SUCCESS_MSG:
            # If this RPM device returns a success message check for it before
            # continuing.
            try:
                ssh.expect(self.SUCCESS_MSG, timeout=60)
            except pexpect.ExceptionPexpect:
                logging.error(
                        'Request to change outlet for device: %s to new '
                        'state %s failed.', device_hostname, new_state)
                return False
        logging.debug('Outlet for device: %s set to %s', device_hostname,
                      new_state)
        return True

    def type(self):
        """
        Get the type of RPM device we are interacting with.
        Class attribute TYPE should be set by the subclasses.

        @return: string representation of RPM device type.
        """
        return self.TYPE


class SentryRPMController(RPMController):
    """
    This class implements power control for Sentry Switched CDU
    http://www.servertech.com/products/switched-pdus/

    Example usage:
      rpm = SentrySwitchedCDU('chromeos-rack1-rpm1')
      rpm.queue_request('chromeos-rack1-host1', 'ON')

    @var _username: username used to access device.
    @var _password: password used to access device.
    """
    SET_STATE_CMD = '%s %s'
    SUCCESS_MSG = 'Command successful'
    NUM_OF_OUTLETS = 17
    TYPE = 'Sentry'

    # Constants for login workflow.
    WRONG_PASSWORD_PROMPT = ['password:', 'Password:']
    DEVICE_PROMPT = ['Switched CDU:', 'Switched PDU:']

    # Constants for change password workflow.
    CHANGE_PASSWORD_TIMEOUT = 10
    CHANGE_PASSWORD_CMD = 'PASSWORD'
    CURRENT_PASSWORD_PROMPT = 'Current Password:'
    NEW_PASSWORD_PROMPT = 'New Password:'
    VERIFY_PASSWORD_PROMPT = 'Verify Password:'

    def __init__(self, hostname, hydra_hostname=None):
        super(SentryRPMController, self).__init__(hostname, hydra_hostname)
        self._username = rpm_config.get('SENTRY', 'username')
        # For RPM in Lab, we use a password defined in k8s deployment.
        self._password = os.environ.get('RPM_PASSWORD')
        # This is for RPM at first deployment, which use default password.
        self._default_password = rpm_config.get('SENTRY', 'password')
        if not self._password:
            self._password = self._default_password

    def _login(self):
        """
        Log in into the Sentry RPM device..

        The login process should be able to connect to the device whether or not
        it is behind a hydra serial concentrator.

        @return: ssh - a pexpect.spawn instance if the connection was successful
                 or None if it was not.
        """
        if self.behind_hydra:
            # Tunnel the connection through the hydra.
            ssh = self._authenticate_with_hydra()
            if not ssh:
                return None
            ssh.sendline(self._username)
        else:
            # Connect directly to the RPM over SSH.
            hostname = '%s.%s' % (self.hostname, self._dns_zone)
            cmd = RPMController.SSH_LOGIN_CMD % (self._username, hostname)
            try:
                ssh = pexpect.spawn(cmd)
            except pexpect.ExceptionPexpect:
                return None
        # Flag to mark if we need to update password for the PDU.
        need_update_password = False
        # Wait for the password prompt
        try:
            ssh.expect(self.PASSWORD_PROMPT, timeout=60)
            ssh.sendline(self._password)
            # Response 0 or 1 represents a success login while 2 or 3 meaning
            # wrong password.
            res = ssh.expect(self.DEVICE_PROMPT + self.WRONG_PASSWORD_PROMPT,
                             timeout=60)
            # Handle the case if the PDU is still on default password.
            if res == 2 or res == 3:
                logging.info(
                        'The password configured was incorrect, will'
                        ' re-try with default password.', self.hostname)
                ssh.sendline(self._default_password)
                ssh.expect(self.DEVICE_PROMPT, timeout=60)
                need_update_password = True
                logging.info('Successfully logged in %s with default password',
                             self.hostname)
        except pexpect.ExceptionPexpect as e:
            ssh.close()
            logging.error('Failed to login %s, error: %s', self.hostname,
                          str(e))
            return None
        # This means the device is still on default password, so we need to
        # update it.
        if need_update_password:
            self._update_password(ssh)
        return ssh

    def _update_password(self, ssh):
        logging.info('Updating password for %s', self.hostname)
        try:
            ssh.sendline(self.CHANGE_PASSWORD_CMD)
            ssh.expect(self.CURRENT_PASSWORD_PROMPT,
                       timeout=self.CHANGE_PASSWORD_TIMEOUT)
            ssh.sendline(self._default_password)
            ssh.expect(self.NEW_PASSWORD_PROMPT,
                       timeout=self.CHANGE_PASSWORD_TIMEOUT)
            ssh.sendline(self._password)
            ssh.expect(self.VERIFY_PASSWORD_PROMPT,
                       timeout=self.CHANGE_PASSWORD_TIMEOUT)
            ssh.sendline(self._password)
            ssh.expect(self.SUCCESS_MSG)
            logging.info('Successfully updated password for %s.',
                         self.hostname)
        except Exception as e:
            logging.error('Failed to update password for %s, error: %s',
                          self.hostname, str(e))

    def _setup_test_user(self, ssh):
        """Configure the test user for the RPM

        @param ssh: Pexpect object to use to configure the RPM.
        """
        # Create and configure the testing user profile.
        testing_user = rpm_config.get('SENTRY', 'testing_user')
        testing_password = rpm_config.get('SENTRY', 'testing_password')
        ssh.sendline('create user %s' % testing_user)
        response = ssh.expect_list(
                [re.compile('not unique'),
                 re.compile(self.PASSWORD_PROMPT)])
        if not response:
            return
        # Testing user is not set up yet.
        ssh.sendline(testing_password)
        ssh.expect('Verify Password:')
        ssh.sendline(testing_password)
        ssh.expect(self.SUCCESS_MSG)
        ssh.expect(self.DEVICE_PROMPT)
        ssh.sendline('add outlettouser all %s' % testing_user)
        ssh.expect(self.SUCCESS_MSG)
        ssh.expect(self.DEVICE_PROMPT)

    def _clear_outlet_names(self, ssh):
        """
        Before setting the outlet names, we need to clear out all the old
        names so there are no conflicts. For example trying to assign outlet
        2 a name already assigned to outlet 9.
        """
        for outlet in range(1, self.NUM_OF_OUTLETS):
            outlet_name = 'Outlet_%d' % outlet
            ssh.sendline(self.SET_OUTLET_NAME_CMD % (outlet, outlet_name))
            ssh.expect(self.SUCCESS_MSG)
            ssh.expect(self.DEVICE_PROMPT)

    def setup(self, outlet_naming_map):
        """
        Configure the RPM by adding the test user and setting up the outlet
        names.

        Note the rpm infrastructure does not rely on the outlet name to map a
        device to its outlet any more. We keep this method in case there is
        a need to label outlets for other reasons. We may deprecate
        this method if it has been proved the outlet names will not be used
        in any scenario.

        @param outlet_naming_map: Dictionary used to map the outlet numbers to
                                  host names. Keys must be ints. And names are
                                  in the format of 'hostX'.

        @return: True if setup completed successfully, False otherwise.
        """
        ssh = self._login()
        if not ssh:
            logging.error('Could not connect to %s.', self.hostname)
            return False
        try:
            self._setup_test_user(ssh)
            # Set up the outlet names.
            # Hosts have the same name format as the RPM hostname except they
            # end in hostX instead of rpmX.
            dut_name_format = re.sub('-rpm[0-9]*', '', self.hostname)
            if self.behind_hydra:
                # Remove "chromeosX" from DUTs behind the hydra due to a length
                # constraint on the names we can store inside the RPM.
                dut_name_format = re.sub('chromeos[0-9]*-', '',
                                         dut_name_format)
            dut_name_format = dut_name_format + '-%s'
            self._clear_outlet_names(ssh)
            for outlet, name in outlet_naming_map.items():
                dut_name = dut_name_format % name
                ssh.sendline(self.SET_OUTLET_NAME_CMD % (outlet, dut_name))
                ssh.expect(self.SUCCESS_MSG)
                ssh.expect(self.DEVICE_PROMPT)
        except pexpect.ExceptionPexpect as e:
            logging.error('Setup failed. %s', e)
            return False
        finally:
            self._logout(ssh)
        return True
