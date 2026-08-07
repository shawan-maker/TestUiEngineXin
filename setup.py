from setuptools import setup, find_packages
import codecs
import os

here = os.path.abspath(os.path.dirname(__file__))

with codecs.open(os.path.join(here, "README.md"), encoding="utf-8") as fh:
    long_description = "\n" + fh.read()

setup(
    name="ui_engine_xin",
    version="0.0.9",
    author="Shawn",
    author_email="xiaoh0525@xiaoh.com",
    description="基于 Playwright 的关键字驱动 UI 自动化测试引擎",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://pypi.org/project/ui_engine_xin/",
    packages=find_packages(),
    package_data={
        "UIEngine": ["config/*.yaml"],
    },
    python_requires=">=3.9",
    install_requires=[
        "playwright>=1.40.0",
        "pyyaml>=6.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-playwright>=0.4",
        ],
    },
    license="MIT",
    keywords=["python", "playwright", "ui-automation", "keyword-driven", "testing", "uiEngine"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
)
