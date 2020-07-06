# StochOptFormat

This repository describes a file-format for stochastic optimization problems
called _StochOptFormat_ with the file extension `.sof.json`.

**Maintainers**

- Oscar Dowson (Northwestern)
- Joaquim Garcia (PSR-Inc, PUC-Rio)

_Note: this file format is in development. Things may change! If you have
suggestions or comments, please open an issue._

## Preliminaries

StochOptFormat is based on two recently developed concepts:

- The _Policy Graph_ decomposition of a multistage stochastic program [1].
- _MathOptFormat_, a file format for mathematical optimization problems [2].

**Do not read further without reading both papers first.**

## Example

Consider a two-stage newsvendor problem. In the first stage, the agent chooses
`x`, the number of newspapers to buy at a cost \$1/newspaper. In the second
stage, the uncertain demand of `d` newspapers is realized, and the agent sells
`u` newspapers at a price of \$1.50/newspaper, with the constraint that
`u = min{x, d}`. The demand is a either 10 units with probability 0.4, or 14
units with probability 0.6.

First-stage:
```
  V₀(x) = max: -1 * x'
          s.t. x' >= 0
```
Second-stage:
```
  V₁(x, d) = max: 1.5 * u
             s.t. u - x     <= 0
                      x - d <= 0
                  u         >= 0
```

Encoded in StochOptFormat, this example becomes:
```json
{
  "root": {
    "name": "root",
    "states": [{"name": "x", "initial_value": 0}]
  },
  "nodes": [{
    "name": "first_stage",
    "states": [
      {"name": "x", "in": "x_in", "out": "x_out"}
    ],
    "subproblem": {
      "version": {"major": 0, "minor": 4},
      "variables": [{"name": "x_in"}, {"name": "x_out"}],
      "objective": {
        "sense": "max",
        "function": {
          "head": "ScalarAffineFunction",
          "terms": [{"variable": "x_out", "coefficient": -1}],
          "constant": 0
        }
      },
      "constraints": [{
        "function": {"head": "SingleVariable", "variable": "x_out"},
        "set": {"head": "GreaterThan", "lower": 0}
      }]
    }
  }, {
    "name": "second_stage",
    "states": [
      {"name": "x", "in": "x_in", "out": "x_out"}
    ],
    "parameters": [
      {"name": "d"}
    ],
    "subproblem": {
      "version": {"major": 0, "minor": 4},
      "variables": [
        {"name": "x_in"}, {"name": "x_out"}, {"name": "u"}, {"name": "d"}
      ],
      "objective": {
        "sense": "max",
        "function": {
          "head": "ScalarAffineFunction",
          "terms": [{"variable": "u", "coefficient": 1.5}],
          "constant": 0
        }
      },
      "constraints": [{
        "function": {
          "head": "ScalarAffineFunction",
          "terms": [
            {"variable": "u", "coefficient": 1},
            {"variable": "x", "coefficient": -1}
          ]
        },
        "set": {"head": "LessThan", "lower": 0}
      }, {
        "function": {
          "head": "ScalarAffineFunction",
          "terms": [
            {"variable": "u", "coefficient": 1},
            {"variable": "d", "coefficient": -1}
          ]
        },
        "set": {"head": "LessThan", "lower": 0}
      }, {
        "function": {"head": "SingleVariable", "variable": "u"},
        "set": {"head": "GreaterThan", "lower": 0}
      }, ]
    },
    "noise_terms": [{
      "probabilty": 0.4, "support": [{"parameter": "d", "value": 10}]
    }, {
      "probabilty": 0.6, "support": [{"parameter": "d", "value": 14}]
    }]
  }],
  "edges": [
    {"from": "root", "to": "first_stage", "probability": 1.0},
    {"from": "first_stage", "to": "second_stage", "probability": 1.0}
  ]
}
```

## The schema

## References

[1] Dowson, O. (2020). The policy grpah decompisition of multistage stochastic
  programming problems. Networks, 71(1), 3-23.
  doi: https://onlinelibrary.wiley.com/doi/full/10.1002/net.21932
  [preprint](http://www.optimization-online.org/DB_HTML/2018/11/6914.html)

[2] Legat, B., Dowson, O., Garcia, J.D., Lubin, M. (2020). MathOptInterface: a
  data structure for mathematical optimization problems.
  [preprint](http://www.optimization-online.org/DB_HTML/2020/02/7609.html)
  [repository](https://github.com/jump-dev/MathOptFormat)
