import time
import sys
import logging
import os

import common
from autotest_lib.server import afe_utils
from autotest_lib.server.hosts import repair_utils
from autotest_lib.server.hosts import factory
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.server.cros.dynamic_suite import tools

# Script created to perform update EC+AP on the host and then provision it.
# Perform steps:
#   1) Dump host-info file to folder /tr (please update for local run)
#   2) Run update EC+AP from provided faft image for firmware (part of stable version section in host-info file)
#   3) Run QuickProvisioning on the host
#
# Requirements of the script:
#   1) Installed Shivas CLI
#   2) Host registered in inventory
#
# Example to run the script
#   `python handy_tools/flash_faft_fw_by_servo_and_provision.py <target_host_name>`

# pylint: disable=missing-docstring


def get_host_info_path(host):
    """Generate path to host-info file."""
    return '/tr/host_info_store/%s.store' % host


def dump_host_info(host):
    """Save host information to host-info file."""
    cmd = 'shivas get dut -host-info-store %s > %s'
    os.system(cmd % (host, get_host_info_path(host)))


def provision(host):
    """Run quick-provisioning on the target host."""
    image_name = host.get_cros_repair_image_name()
    logging.info('Staging build for provision: %s', image_name)
    devserver = dev_server.ImageServer.resolve(image_name, host.hostname)
    devserver.trigger_download(image_name, synchronous=False)
    update_url = tools.image_url_pattern() % (devserver.url(), image_name)
    afe_utils.machine_install_and_update_labels(host, update_url)


def flash_fw(host):
    """Perform firmeware update on the target host."""
    repair_utils.require_servo(host, ignore_state=True)
    info = host.host_info_store.get()
    build = afe_utils.get_stable_faft_version_v2(info)
    message('Stable version: %s', build)
    if build:
        host.firmware_install(build)
    else:
        raise Exception('Fail to find Firmware version to flash')


def message(*args):
    """Print message to the log for quick find it."""
    logging.info('==========')
    logging.info(*args)
    logging.info('==========')


def main():
    if len(sys.argv) == 1:
        return
    hostname = sys.argv[1]
    message('START HOST: %s', hostname)

    dump_host_info(hostname)

    need_servod = True
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
        flash_fw(host)
        if host.is_up():
            message('HOST IS UP')
        provision(host)
        message('DONE')


if __name__ == "__main__":
    main()
