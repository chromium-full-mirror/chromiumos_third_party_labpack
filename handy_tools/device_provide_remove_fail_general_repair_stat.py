import time
import sys
import logging
import os

import common
from autotest_lib.server.hosts import ServoHost
from autotest_lib.server.hosts import file_store
from autotest_lib.server.cros.device_health_profile import device_health_profile
from autotest_lib.server.cros.device_health_profile import profile_constants

# Script created to perform action to reset sta of repair action 'general_firmware' to 0.
# Perform steps:
#   1) Dump host-info file to folder /tr (please update for local run)
#   2) Copy and initial device provile to local folder /tr
#   3) Reset data for repair action.
#
# Requirements of the script:
#   1) Installed Shivas CLI
#   2) Host registered in inventory
#
# Example to run the script
#   `python handy_tools/device_provide_remove_fail_general_repair_stat.py <target_host_name1> <target_host_name2> ...`

# pylint: disable=missing-docstring


def get_host_info_path(host):
    """Generate path to host-info file."""
    return '/tr/host_info_store/%s.store' % host


def dump_host_info(host):
    """Save host information to host-info file."""
    cmd = 'shivas get dut -host-info-store %s > %s'
    os.system(cmd % (host, get_host_info_path(host)))


def schedule_repair(host):
    """Save host information to host-info file."""
    cmd = 'shivas repair-duts -expiration-mins 600 %s'
    os.system(cmd % host)
    message('TASK SCHEDULED')


def message(*args):
    """Print message to the log for quick find it."""
    logging.info('==========')
    logging.info(*args)
    logging.info('==========')


def run(hostname):
    message('START HOST: %s', hostname)
    dump_host_info(hostname)
    host_info_path = get_host_info_path(hostname)
    host_info = file_store.FileStore(host_info_path).get()
    if not host_info.attributes:
        message('NO ATTRIBUTES')
        return
    servo_host = host_info.attributes['servo_host']
    servo_port = host_info.attributes['servo_port']

    host = ServoHost(servo_host=servo_host, servo_port=servo_port)

    # Copy init device provide.
    health_profile = device_health_profile.DeviceHealthProfile(
            hostname=hostname, host_info=host_info, result_dir='/tr')
    health_profile.init_profile(host)

    if not health_profile.is_loaded():
        message('DEVICE IS NOT LOADED')
        return

    actions = health_profile.get_failed_repair_actions()
    actions['general_firmware'] = 0
    health_profile._update_profile(profile_constants.FAILED_REPAIR_ACTIONS_KEY,
                                   actions)
    # Saving device provide.
    health_profile.close()
    schedule_repair(hostname)
    message('DONE')


def main():
    if len(sys.argv) == 1:
        return
    for hostname in sys.argv[1:]:
        run(hostname)


if __name__ == "__main__":
    main()
