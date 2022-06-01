import os
from distutils.command.build import build

from django.core import management
from setuptools import find_packages, setup

from pretix_invoice_modification import __version__


try:
    with open(
        os.path.join(os.path.dirname(__file__), "README.rst"), encoding="utf-8"
    ) as f:
        long_description = f.read()
except Exception:
    long_description = ""


class CustomBuild(build):
    def run(self):
        management.call_command("compilemessages", verbosity=1)
        build.run(self)


cmdclass = {"build": CustomBuild}


setup(
    name="pretix-invoice-modification",
    version=__version__,
    description="Short description",
    long_description=long_description,
    url="https://github.com/marenz2569/pretix-invoice-modification",
    author="Markus Schmidl",
    author_email="markus.schmidl@mailbox.tu-dresden.de",
    license="pretix Enterprise",
    install_requires=[],
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    cmdclass=cmdclass,
    entry_points="""
[pretix.plugin]
pretix_invoice_modification=pretix_invoice_modification:PretixPluginMeta
""",
)
