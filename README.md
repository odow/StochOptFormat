# StochOptFormat

This repository describes a file-format for stochastic optimization problems
called _StochOptFormat_ with the file extension `.sof.json`.

**Maintainers**

- Oscar Dowson (Northwestern)
- Joaquim Garcia (PSR-Inc, PUC-Rio)

_Note: this file format is in development. Things may change!_

## Preliminaries

StochOptFormat is based on two recently developed concepts:

1. The _Policy Graph_ decomposition of a multistage stochastic program

  Dowson, O. (2020). The policy grpah decompisition of multistage stochastic
  programming problems. Networks, 71(1), 3-23. doi:
  https://onlinelibrary.wiley.com/doi/full/10.1002/net.21932

  A pre-print of a paper is [also available](http://www.optimization-online.org/DB_HTML/2018/11/6914.html).

2. _MathOptFormat_, a file format for mathematical optimization problems.

  Legat, B., Dowson, O., Garcia, J.D., Lubin, M. (2020). MathOptInterface: a
  data structure for mathematical optimization problems. URL:
  http://www.optimization-online.org/DB_HTML/2020/02/7609.html.

**Do not read further without reading both papers first.**
