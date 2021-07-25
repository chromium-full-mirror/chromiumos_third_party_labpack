# Copyright (c) 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Lint as: python2, python3
#pylint: disable-msg=C0111
"""
Internal global error types
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
from traceback import format_exception

# Add names you want to be imported by 'from errors import *' to this list.
# This must be list not a tuple as we modify it to include all of our
# the Exception classes we define below at the end of this file.
__all__ = ['format_error']


def format_error():
    t, o, tb = sys.exc_info()
    trace = format_exception(t, o, tb)
    # Clear the backtrace to prevent a circular reference
    # in the heap -- as per tutorial
    tb = ''

    return ''.join(trace)


class TimeoutException(Exception):
    """Generic exception raised on retry timeouts."""


# This MUST remain at the end of the file.
# Limit 'from error import *' to only import the exception instances.
for _name, _thing in list(locals().items()):
    try:
        if issubclass(_thing, Exception):
            __all__.append(_name)
    except TypeError:
        pass  # _thing not a class
__all__ = tuple(__all__)
