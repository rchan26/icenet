import setuptools

from setuptools import setup, find_packages

from icenet2 import __version__ as icenet_version

"""Setup module for Icenet2 - draft module
"""

with open("README.md", "r") as fh:
    long_description = fh.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = [ ]

test_requirements = ['pytest>=3', ]

setup(
    name="icenet2",
    version=icenet_version,
    author="Tom Andersson/James Byrne",
    author_email="jambyr@bas.ac.uk",
    description="",
    long_description=long_description + '\n\n' + history,
    long_description_content_type="text/markdown",
    url="https://www.bas.ac.uk",
    packages=find_packages(include=['icenet2', 'icenet2.*']),
    keywords="",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    entry_points={
        # TODO: refactor to single entry point using click
        "console_scripts": [
            "icenet_data_masks = icenet2.data.sic.mask:main",

            "icenet_data_cmip = icenet2.data.interfaces.esgf:main",
            "icenet_data_era5 = icenet2.data.interfaces.cds:main",
            "icenet_data_hres = icenet2.data.interfaces.mars:main",
            "icenet_data_sic = icenet2.data.sic.osisaf:main",

            "icenet_data_reproc_monthly = "
            "icenet2.data.interfaces.utils:reprocess_main",
            "icenet_data_add_time_dim = "
            "icenet2.data.interfaces.utils:add_time_dim_main",

            "icenet_process_cmip = icenet2.data.processors.cmip:main",
            "icenet_process_era5 = icenet2.data.processors.era5:main",
            "icenet_process_hres = icenet2.data.processors.hres:main",
            "icenet_process_sic = icenet2.data.processors.osi:main",

            "icenet_process_metadata = icenet2.data.processors.meta:main",

            "icenet_dataset_check = icenet2.data.utils:check",
            "icenet_dataset_create = icenet2.data.loader:main",

            "icenet_train = icenet2.model.train:main",
            "icenet_predict = icenet2.model.predict:main",
            "icenet_upload_azure = icenet2.process.azure:upload",
            "icenet_upload_local = icenet2.process.local:upload",

            "icenet_plot_set = icenet2.plotting.data:plot_set",

            "icenet_video_data = icenet2.plotting.video:data_cli",

            "icenet_output = icenet2.process.predict:create_cf_output"
        ],
    },
    python_requires='>=3.7, <4',
    install_requires=requirements,
    include_package_data=True,
    test_suite='tests',
    tests_require=test_requirements,
    zip_safe=False,
)
