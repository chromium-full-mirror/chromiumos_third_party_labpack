# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import logging
import logging.handlers
import os
import time

from config import rpm_config
import log_socket_server
import rpm_infrastructure_exception

LOGGING_FORMAT = rpm_config.get('GENERAL', 'logging_format')


def set_up_logging_to_file(log_dir, log_filename_format=None):
    """
    Correctly set up logging to have the correct format/level, log to a file,
    and send out email notifications in case of error level messages.

    @param log_dir: The directory in which log files should be created.
    @param log_filename_format: Format to use to create the log file.

    @returns email_handler: Logging handler used to send out email alerts.
    """
    logging.basicConfig(filename=_logfile_path(log_dir, log_filename_format),
                        level=logging.INFO,
                        format=LOGGING_FORMAT)
    _set_common_logger_options()


def start_log_server(log_dir, log_filename_format):
    """Start log server to accept logging through a TCP server.

    @param log_dir: The directory in which log files should be created.
    @param log_filename_format: Format to use to create the log file.
    """
    log_filename = _logfile_path(log_dir, log_filename_format)
    log_socket_server.LogSocketServer.start(filename=log_filename,
                                            level=logging.INFO,
                                            format=LOGGING_FORMAT)


def set_up_logging_to_server():
    """Sets up logging option when using a logserver."""
    if log_socket_server.LogSocketServer.port is None:
        raise rpm_infrastructure_exception.RPMLoggingSetupError(
                'set_up_logging failed: Log server port is unknown.')
    socketHandler = logging.handlers.SocketHandler(
            'localhost', log_socket_server.LogSocketServer.port)
    logging.getLogger().addHandler(socketHandler)
    _set_common_logger_options()


def _logfile_path(log_dir, log_filename_format):
    """Get file name of log based on given log_filename_format.

    @param log_filename_format: Format to use to create the log file.
    """
    log_filename = time.strftime(log_filename_format)
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    return os.path.join(log_dir, log_filename)


def _set_common_logger_options():
    """Sets the options common to both file and server based logging."""
    logger = logging.getLogger()
    if rpm_config.getboolean('GENERAL', 'debug'):
        logger.setLevel(logging.DEBUG)
