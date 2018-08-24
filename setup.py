#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name='beets-listenmanager',
    version='0.0.1',
    namespace_packages=['beetsplug'],
    packages=['beetsplug'],
    author='Arnaud Grausem',
    author_email='arnaud.grausem@gmail.com',
    license='MIT',
    description='Beets plugin to manage playlists',
    long_description=open('README.rst').read(),
    url='https://github.com/agrausem/beets-listenmanager',
    install_requires=[
        'beets',
    ]
)
