# setup.py

from setuptools import setup

setup(
    name='nakbot',
    version='1.0',
    packages=['nakbot'],
    entry_points={
        'console_scripts': ['nakbot=nakbot.__main__:main']
    },
)
