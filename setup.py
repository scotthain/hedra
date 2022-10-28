import os
from setuptools import (
    setup,
    find_packages
)

current_directory = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(current_directory, 'README.md'), "r") as readme:
    package_description = readme.read()

setup(
    name="hedra",
    version="0.5.7",
    description="Powerful performance testing made easy.",
    long_description=package_description,
    long_description_content_type="text/markdown",
    author="Sean Corbett",
    author_email="sean.corbett@umconnect.edu",
    url="https://github.com/scorbettUM/hedra",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent"
    ],
    install_requires=[
        'attr',
        'networkx',
        'aiodns',
        'h2',
        'click',
        'psutil',
        'fastapi',
        'alive-progress',
        'dill',
        'scipy',
        'art',
        'scikit-learn',
        'uvloop',
        'tdigest'
    ],
    entry_points = {
        'console_scripts': [
            'hedra=hedra.cli:run',
            'hedra-server=hedra.run_uwsgi:run_uwsgi'
        ],
    },
    extras_require = {
        'playwright': [
            'playwright',
        ],
        'azure': [
            'azure-cosmos'
        ],
        'honeycomb': [
            'libhoney'
        ],
        'influxdb': [
            'influxdb_client'
        ],
        'newrelic': [
            'newrelic'
        ],
        'statsd': [
            'aio_statsd'
        ],
        'prometheus': [
            'prometheus-client',
            'prometheus-api-client',
        ],
        'cassandra': [
            'cassandra-driver'
        ],
        'datadog': [
            'datadog'
        ],
        'mongodb': [
            'motor'
        ],
        'redis': [
            'redis',
            'aioredis'
        ],
        'kafka': [
            'aiokafka'
        ],
        'sql': [
            'aiomysql',
            'psycopg2-binary',
            'aiopg',
            'sqlalchemy',
        ],
        'aws': [
            'boto3'
        ],
        'grpc': [
            'grpcio',
            'grpcio-tools'
        ],
        'graphql': [
            'graphql'
        ],
        'snowflake': [
            'snowflake-connector-python'
        ],
        'google': [
            'google-cloud-bigquery',
            'google-cloud-bigtable',
            'google-cloud-storage',
        ]
    },
    python_requires='>=3.8'
)
