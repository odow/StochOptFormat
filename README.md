# StochOptFormat

This repository describes a file-format for stochastic optimization problems
called _StochOptFormat_ with the file extension `.sof.json`.

For convenience, we often refer to StochOptFormat as _SOF_.

**Maintainers**

- Oscar Dowson (Northwestern)
- Joaquim Garcia (PSR-Inc, PUC-Rio)

_Note: this file format is in development. Things may change! If you have
suggestions or comments, please open an issue._

## Preliminaries

SOF is based on two recently developed concepts:

- The _Policy Graph_ decomposition of a multistage stochastic program [1].
- _MathOptFormat_, a file format for mathematical optimization problems [2].

**Do not read further without reading sections 1, 2, and 3 of [1] and sections
1, 2, and 5 of [2].**

## Example

There are alot of concepts to unpack in SOF. We present a simple example first,
and then explain each section in detail.

Consider a two-stage newsvendor problem. In the first stage, the agent chooses
`x`, the number of newspapers to buy at a cost \$1/newspaper. In the second
stage, the uncertain demand of `d` newspapers is realized, and the agent sells
`u` newspapers at a price of \$1.50/newspaper, with the constraint that
`u = min{x, d}`. The demand is a either 10 units with probability 0.4, or 14
units with probability 0.6.

The first-stage subproblem is:
```
  V₀(x) = max: -1 * x′
          s.t.      x′ >= 0,
```
and the second-stage is:
```
  V₁(x, d) = max: 1.5 * u
             s.t. u - x     <= 0
                  u     - d <= 0
                  u         >= 0.
```

Encoded in StochOptFormat, this example becomes:
```json
{
  "version": {"major": 0, "minor": 1},
  "author": "Oscar Dowson",
  "name": "Two-stage newsvendor",
  "description": "An SOF implementation of the classical two-stage newsvendor problem.",
  "root": {
    "name": "root",
    "state_variables": {
      "x": {"initial_value": 0.0}
    }
  },
  "nodes": {
    "first_stage": {
      "state_variables": {
        "x": {"in": "x_in", "out": "x_out"}
      },
      "random_variables": {},
      "subproblem": {
        "version": {"major": 0, "minor": 4},
        "variables": [{"name": "x_in"}, {"name": "x_out"}],
        "objective": {
          "sense": "max",
          "function": {
            "head": "ScalarAffineFunction",
            "terms": [{"variable": "x_out", "coefficient": -1.0}],
            "constant": 0.0
          }
        },
        "constraints": [{
          "function": {"head": "SingleVariable", "variable": "x_out"},
          "set": {"head": "GreaterThan", "lower": 0.0}
        }]
      }
    },
    "second_stage": {
      "state_variables": {
        "x": {"in": "x_in", "out": "x_out"}
      },
      "random_variables": {
        "d": {}
      },
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
            "constant": 0.0
          }
        },
        "constraints": [{
          "function": {
            "head": "ScalarAffineFunction",
            "terms": [
              {"variable": "u", "coefficient": 1.0},
              {"variable": "x_in", "coefficient": -1.0}
            ],
            "constant": 0.0
          },
          "set": {"head": "LessThan", "upper": 0.0}
        }, {
          "function": {
            "head": "ScalarAffineFunction",
            "terms": [
              {"variable": "u", "coefficient": 1.0},
              {"variable": "d", "coefficient": -1.0}
            ],
            "constant": 0.0
          },
          "set": {"head": "LessThan", "upper": 0.0}
        }, {
          "function": {"head": "SingleVariable", "variable": "u"},
          "set": {"head": "GreaterThan", "lower": 0.0}
        }]
      },
      "noise_terms": [
        {"probability": 0.4, "support": {"d": 10.0}},
        {"probability": 0.6, "support": {"d": 14.0}}
      ]
    }
  },
  "edges": [
    {"from": "root", "to": "first_stage", "probability": 1.0},
    {"from": "first_stage", "to": "second_stage", "probability": 1.0}
  ]
}
```

### Explanation

SOF is a JSON document. The model is stored as a single JSON object. JSON
objects are key-value mappings enclused by curly braces. There are four required
keys at the top-level.

- `version`

  An object describing the minimum version of MathOptFormat needed to parse
  the file. This is included to safeguard against later revisions. It contains
  two keys: `major` and `minor`. These keys should be interpreted using
  [SemVer](https://semver.org).

- `root`

  An object describing the root node of the policy graph. It has two required
  keys:

  - `name`

    A unique string name for the root node to distinguish it from other nodes.

  - `states`

    A list of objects describing the state variables in the model. Each element
    is an object with two required keys:

    - `name`

      A unique string name for the state variable.

    - `initial_value`

      The value of the state variable at the root node.

- `nodes`

  A list of objects with one element for each node in the policy graph. Each
  node has four required keys:

  - `name`

    A unique string name for the node to distinguish it from other nodes.

  - `states`

    A list of objects to map the states to the variables inside the
    subproblem. Each object has three required keys:

    - `name`

      The name of the state variable as defined in the root node.

    - `in`

      The name of the variable representing the incoming state variable in the
      subproblem.

    - `out`

      The name of the variable representing the outgoing state variable in the
      subproblem.

  - `parameters`

    A list of objects describing the parameters in the model. Each element
    is an object with one required key:

    - `name`

    Within the subproblem, parameters are represented by decision variables.
    This `name` is the name of a decision variable in `subproblem` that should
    be interpreted as a parameter.

  - `subproblem`

    The subproblem corresponding to the node as a MathOptFormat object.

- `edges`

  A list of objects with one element for each edge in the policy graph. Each
  object has three required keys:

  - `from`

    The name of the node that the edge exits.

  - `to`

    The name of the node that the edge enters. This cannot be the root node.

  - `probability`

    The nominal probability of transitioning from node `from` to node `to`.

## FAQ

- Q: The policy graph is too complicated. I just want a format for linear
  T-stage stochastic programs.

  A: The policy graph does take some getting used to. But for a T-stage problem,
  our format requires T subproblems, a list of the state variables, and a
  sequence of edges. Of those things, only the list of edges would be
  superfluous in a purely T-stage format. So, for the sake of a list of objects
  like `{"from": "1", "to": "2", "probability": 1}`, we get a format that
  trivially extends to infinite horizon problems and problems with a stochastic
  process that is not stagewise independent.

- Q: MathOptFormat is too complicated. Why can't we use LP or MPS files?

  A: Please read Section 2 of [2].

- Q: You don't expect me to write these by hand do you?

  A: No. We expect high-level libraries like [SDDP.jl](https://github.com/odow/SDDP.jl)
  to do the reading and writing for you.

- Q: What happened to SMPS?

  A: SMPS is too limiting for multistage problems. We hope to implement a
  converter between SMPS and StochOptFormat at some point... Want to help?

- Q: This seems catered to SDDP; I just have some scenarios.

  A: The policy graph can represent any scenario tree. Go read [1].

- Q: I want continuous random variables.

  A: In this initial version of the format, we only consider finite discrete
  random variables. We might consider adding continuous onces in the future.

- Q: My stochastic process is not stagewise-independent.

  A: Two options: expand the state-space, or create a scenario tree. For more
  information, read Sections 1, 2, and 3 of [1].

- Q: I don't like JSON.

  A: We're open to better ideas. JSON is universal support in every major
  programming language, and is human-readable(-ish).

- Q: JSON seems too verbose.

  A: JSON files compress well. For example, for models in the MIPLIB 2017
  benchmark set, compressed MathOptFormat files are only 37% larger than their
  compressed MPS equivalents.

- Q: Why isn't `parameters` a list of strings?

  A: So we have the option to add additional fields (e.g., a default) in the
  future in a backwards compatible way.

- Q: I want the uncertainty to be an objective/constraint coefficient.

  A: Formulate the objective/constraint as a `ScalarQuadraticFunction`. It's up
  to the reader to infer from the list of the parameters if this is a
  parameterized `ScalarAffineFunction`, or a `ScalarQuadraticFunction` without
  parameters.

- Q: Follow up to the previous. I want to have `parameter * x * y`.

  A: Changing the quadratic coefficient matrices in solvers is slow, and doing
  so could easily make the problem non-convex. If you really want to, you could
  add a slack variable (and equality constraint) `z == parameter * x`, and then
  use `z * y`.

- Q: Why haven't you written an interface to ⟨INSERT LANGUAGE HERE⟩ yet?

  A: Does ⟨INSERT LANGUAGE HERE⟩ have a JSON reader? Just import the file!

## References

[1] Dowson, O. (2020). The policy graph decomposition of multistage stochastic
  programming problems. Networks, 71(1), 3-23.
  doi: https://onlinelibrary.wiley.com/doi/full/10.1002/net.21932
  [[preprint]](http://www.optimization-online.org/DB_HTML/2018/11/6914.html)

[2] Legat, B., Dowson, O., Garcia, J.D., Lubin, M. (2020). MathOptInterface: a
  data structure for mathematical optimization problems.
  [[preprint]](http://www.optimization-online.org/DB_HTML/2020/02/7609.html)
  [[repository]](https://github.com/jump-dev/MathOptFormat)
