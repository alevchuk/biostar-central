## Biostar: Building Scientific Communities

[![Build Status][build-image]][build-url] 
[![License](http://img.shields.io/:license-mit-blue.svg)](http://doge.mit-license.org)

[build-image]: https://travis-ci.org/alevchuk/ln-central.svg?branch=4.0
[build-url]: https://travis-ci.org/alevchuk/ln-central/builds

Biostar is a Python and Django based Q&A software.
It is a simple, generic, flexible and extensible Q&A framework.

The site has been developed by **scientists and for scientists**. It aims
to address the requirements and needs that scientific communities have.
Biostar is used to run several science oriented Q&A sites:

 * Lightning Network Q&A at: https://ln.support
 * Biostars Bioinformatics Q&A at: https://www.biostars.org
 * Bioconductor User Support: https://support.bioconductor.org

The software is open source and free to use under the MIT License.

### Features

* Q&A: questions, answers, comments,voting, reputation, badges, threaded discussions, bounties
* Lightning Network integration
* Low resource utilization and easy deployment

### Documentation

The documentation:

* [Manage](docs/manage.md)
* [Deploy](docs/deploy.md)

The source for the documentation can be found in  the [docs](./docs) folder.

### Quick Start

Prerequisites:
* Python 2.7
* Python 2.7 virtualenv
* Python 3
* Python 3 virtualenv

From the Biostar source directory:

    # Install virtualenv
    sudo pip2.7 install virtualenv
    sudo pip3 install virtualenv

    # Clone source code
    git clone https://github.com/alevchuk/ln-central
    cd ln-central

    # Initialize virtual envrionment and install the requirements.
    ./biostar.sh install

    # Initialize database, import test data, index for searching and run the server.
    ./biostar.sh init import index run

Visit `http://www.lvh.me:8080` to see the site loaded with demo data.

The `www.lvh.me` domain resolves to `127.0.0.1` your local host 
with a proper domain name. You may just as well use `http://localhost:8080` or `http://127.0.0.1`.

Enjoy.

### Development

See docs https://github.com/alevchuk/ln-central/tree/master/docs

Documentation of dependencies:
* [django](http://www.djangoproject.com/)
* [django-rest-framework](https://www.django-rest-framework.org/)

### Citing

* Parnell LD, Lindenbaum P, Shameer K, Dall'Olio GM, Swan DC, et al.
  [2011 BioStar: An Online Question & Answer Resource for the Bioinformatics Community.](http://www.ploscompbiol.org/article/info%3Adoi%2F10.1371%2Fjournal.pcbi.1002216)
  PLoS Comput Biol 7(10): e1002216. doi:10.1371/journal.pcbi.1002216

### Contributors

List of contributors: https://github.com/alevchuk/ln-central/graphs/contributors
