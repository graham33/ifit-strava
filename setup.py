from setuptools import setup

setup(
    name='ifit_strava',
    version='0.1',
    py_modules=['ifit_strava'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
    install_requires=[
        'Click',
    ],
    entry_points='''
        [console_scripts]
        ifit_strava=ifit_strava:ifit_strava
    ''',
)
