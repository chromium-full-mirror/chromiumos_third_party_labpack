import time
import sys
import logging
import os

import common

from autotest_lib.server.hosts import factory
from device_provide_remove_fail_general_repair_stat import schedule_repair, get_host_info_path, dump_host_info, message

# Script created to perform the following steps:
#   1) Dump host-info file to folder /tr (please update for local run)
#   2) Turn off the power to the DUT
#   3) Boot the DUT in recovery mode
#   4) Reinstall chromeos image on the DUT
#
# Requirements of the script:
#   1) Installed Shivas CLI
#   2) Host registered in inventory
#
# Example to run the script
#   `python handy_tools/override_usb_drive_failures.py <target_host_name>`

# pylint: disable=missing-docstring


def main():

    if len(sys.argv) == 1:
        return
    hostname = sys.argv[1]
    message('START HOST: %s', hostname)

    dump_host_info(hostname)

    need_servod = True
    need_pd_sink = True
    host_info_path = get_host_info_path(hostname)
    host_object = factory.create_target_host(hostname,
                                             host_info_path=host_info_path,
                                             try_lab_servo=need_servod,
                                             try_servo_repair=need_servod,
                                             try_servo_recovery=need_servod)
    with host_object as host:
        if not host._servo_host:
            message('SERVO NOT INITIALIZED')
            return
        message('TARGET HOST CREATED')
        host.servo.get_power_state_controller().power_off()
        host.boot_in_recovery_mode(need_snk=need_pd_sink)
        host.run_install_image(install_timeout=host.ADMIN_INSTALL_TIMEOUT * 2,
                               need_snk=need_pd_sink,
                               is_repair=True)
        if host.is_up():
            message('HOST IS UP')
        message('SCHEDULING REPAIR on %s', hostname)
        schedule_repair(hostname)
        message('DONE')


if __name__ == "__main__":
    main()
