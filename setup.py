from setuptools import setup, find_packages

setup(
    name="sshmngr",
    version="1.0.0",
    description="SSH connection manager with interactive search and jumphost support",
    author="silveX",
    packages=find_packages(),
    install_requires=[
        "paramiko",
        "prompt_toolkit",
        "keyring",
    ],
    entry_points={
        "console_scripts": [
            "sshmngr=sshmngr.sshmngr:main",
        ],
    },
    python_requires=">=3.9",
    include_package_data=True,
    license="MIT",
)
