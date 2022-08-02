#!/usr/bin/env python
import sys

import logging

from ncclient import manager


def connect(host, port, user, password):
    conn = manager.connect(host=host,
                           port=port,
                           username=user,
                           password=password,
                           timeout=60,
                           device_params={'name': 'junos'},
                           hostkey_verify=False)

    conn.lock()

    # configuration as a string
    load_config_result = conn.load_configuration(action='set', config='set system host-name foo')
    logging.info(load_config_result)

    # configuration as a list
    location = [
        'set system location building "Main Campus, C"',
        'set system location floor 15',
        'set system location rack 1117',
    ]

    load_config_result = conn.load_configuration(action='set', config=location)
    logging.info(load_config_result)

    validate_result = conn.validate()
    logging.info(validate_result)

    compare_config_result = conn.compare_configuration()
    logging.info(compare_config_result)

    conn.commit()
    conn.unlock()
    conn.close_session()


if __name__ == '__main__':
    LOG_FORMAT = '%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s'
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=LOG_FORMAT)

    connect('router', '22', 'netconf', 'juniper!')
