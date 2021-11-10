import time
import sys
import logging
import os

import common
from autotest_lib.server.hosts import repair_utils
from autotest_lib.server.hosts import factory

# This script is created to repair DUTs in a deep broken state(where recovery mode is break, and may or may not on test signed firmware/OS)
# Perform steps:
#   1) Fetch host-info from ufs via shivas tool and dump host_info_store file to /tmp/host_info_store folder
#   2) Ensure stable_version image is staged on usbkey.
#   3) Flash AP firmware with overwriting gbb flags to 0x18, which means:
#          VB2_GBB_FLAG_FORCE_DEV_SWITCH_ON
#          VB2_GBB_FLAG_FORCE_DEV_BOOT_USB
#   4) Boot DUT into USB drive by passing ctrl+U via servo.
#   5) Re-install ChromeOS image from usbkey.
#
# Requirements of the script:
#   1) Installed Shivas CLI
#   2) Host registered in inventory
#
# Example to run the script
#   `python handy_tools/deep_repair.py <target_host_name>`

# pylint: disable=missing-docstring

HOST_INFO_STORE_DIR = '/tmp/host_info_store'


def get_host_info_path(host):
    """Generate path to host-info file."""
    return '%s/%s.store' % (HOST_INFO_STORE_DIR, host)


def dump_host_info(host):
    """Save host information to host-info file."""
    if not os.path.isdir(HOST_INFO_STORE_DIR):
        os.mkdir(HOST_INFO_STORE_DIR)
    cmd = 'shivas get dut -host-info-store %s > %s'
    os.system(cmd % (host, get_host_info_path(host)))


def message(*args):
    """Print message to the log for quick find it."""
    logging.info('==========')
    logging.info(*args)
    logging.info('==========')


def install_test_image(host):
    """Initial install a test image on a DUT.

    This function assumes that the required image is already downloaded onto the
    USB key connected to the DUT via servo, and the DUT is in dev mode with
    dev_boot_usb enabled.

    @param host   servers.host.Host object.
    """
    servo = host.servo
    # First power on.  We sleep to allow the firmware plenty of time
    # to display the dev-mode screen; some boards take their time to
    # be ready for the ctrl+U after power on.
    servo.get_power_state_controller().power_off()
    time.sleep(host.SHUTDOWN_TIMEOUT)
    servo.switch_usbkey('dut')
    servo.get_power_state_controller().power_on()

    # Type ctrl+U repeatedly for up to BOOT_TIMEOUT or until DUT boots.
    boot_deadline = time.time() + host.BOOT_TIMEOUT
    while time.time() < boot_deadline:
        logging.info("Pressing ctrl+u")
        servo.ctrl_u()
        if host.ping_wait_up(timeout=5):
            break
    else:
        raise Exception('DUT failed to boot from USB for install test image.')

    host.run('chromeos-install --yes', timeout=host.ADMIN_INSTALL_TIMEOUT * 2)

    logging.info("Rebooting DUT to boot from hard drive.")
    host.reboot()
    logging.info("Install test image completed successfully.")


def validate_image_usbkey(host, expected_version):
    image_from_usbkey = host._servo_host.validate_image_usbkey()
    logging.info("Expected image on usbkey: %s. Actual image on usbkey: %s",
                 (expected_version, image_from_usbkey))
    return expected_version == image_from_usbkey


def repair(host):
    """Perform firmeware update on the target host."""
    repair_utils.require_servo(host, ignore_state=True)
    host.servo.get_power_state_controller().power_off()
    image_name = host.get_cros_repair_image_name()
    message("Use stable_version: %s for repair." % image_name)
    # Ensure stable_version image is on usbkey.
    if not validate_image_usbkey(host, image_name):
        message("Image is not staged on usbkey, staging image now...")
        host.install_image_to_servo_usb(image_url=image_name)
        # Check again after download image to usbkey.
        if not validate_image_usbkey(host, image_name):
            raise Exception(
                    "Failed to validate image on usbkey after download.")
    # Flash firmware with gbb flags 0x18.
    message("Start to flash AP firmware with overwrtting GBB flags to 0x18.")
    _, bios_image = host._servo_host.prepare_repair_firmware_image()
    host._servo_host.flash_ap_firmware_via_servo(image=bios_image,
                                                 gbb_flags=24)
    time.sleep(10)
    # Install OS image
    message("Start to boot DUT into usbkey.")
    install_test_image(host)


def main():
    hostname = sys.argv[1]
    message('START HOST: %s', hostname)
    dump_host_info(hostname)
    host_info_path = get_host_info_path(hostname)
    host_object = factory.create_target_host(hostname,
                                             host_info_path=host_info_path,
                                             try_lab_servo=True,
                                             try_servo_repair=True,
                                             try_servo_recovery=True)
    with host_object as host:
        if not host._servo_host:
            message('SERVO NOT INITIALIZED')
            return
        message('TARGET HOST CREATED')
        if host.is_up_fast() and host.is_up():
            message('HOST IS ALREADY UP, SKIP REPAIR!')
            return
        repair(host)
        if host.is_up():
            message('HOST HAS BEEN SUCCESSFULLY RECOVERED.')
        else:
            raise Exception('HOST IS STILL DOWN AFTER REPAIR.')
        message('DONE')


if __name__ == "__main__":
    main()
