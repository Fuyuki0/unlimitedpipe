# Expressions

`filter` keeps events for which an expression is true. `map` sets fields from expressions.
The language is small on purpose and is parsed, never passed to `eval`.

```bash
unlimited filter 'price > 100'
unlimited filter 'availability == "InStock" and price <= 50'
unlimited filter 'title contains "security" or categories contains "security"'
unlimited filter 'country in ["Thailand", "Vietnam"]'
unlimited filter 'not exists(summary)'
unlimited map 'price=number(price)' 'title=upper(title)' 'cheap=price < 20'
```

Quote the whole expression for the shell (`'...'`) and text values inside it (`"..."`).

## Values

| Syntax | Meaning |
| --- | --- |
| `price`, `offers.0.price`, `metadata.status` | A field. Missing fields are `null`. |
| `` `og:title` `` | A field whose name has unusual characters |
| `"InStock"`, `'InStock'` | Text |
| `42`, `-1.5` | Numbers |
| `true`, `false`, `null` | Literals |
| `["a", "b"]` | A list |

## Operators

| Operator | True when |
| --- | --- |
| `==`, `!=` | Equal / not equal. Numbers compare numerically, also when stored as text (`"89.00" == 89`). Text is case-sensitive. |
| `>`, `>=`, `<`, `<=` | Numeric comparison, or text comparison when both sides are text. Anything compared with `null` is false. |
| `contains` | Text contains text (ignoring case), or a list contains a value. |
| `in` | Value is in a list, or text is inside text (ignoring case). |
| `startswith`, `endswith` | Text starts / ends with text (ignoring case). |
| `matches` | A Python regular expression matches somewhere in the text. |
| `and`, `or`, `not` | Logic (`&&`, `\|\|`, `!` also work). `not` binds tighter than `and`, which binds tighter than `or`. Use parentheses when in doubt. |

A field on its own is true when it is present and not empty, zero or false.

## Functions

| Function | Returns |
| --- | --- |
| `lower(x)`, `upper(x)`, `trim(x)` | Text transformed |
| `len(x)` | Length of text, a list or an object |
| `number(x)` | A number from text such as `"$1,299.00"`, `"1.299,00 €"` or `"฿1,299"` |
| `exists(field)` | Whether the field is present at all (even if empty) |
| `replace(text, pattern, replacement)` | Text with a regular expression substituted |
| `round(x)`, `round(x, digits)` | A number rounded; `round(price * 1.07, 2)` |
| `abs(x)` | A number without its sign |
| `short(x)` | A number the way people say it: `1400000000` becomes `"1.4B"`, `250000` becomes `"250K"` |
| `commas(x)`, `commas(x, digits)` | A number with thousands separators: `commas(84079.69, 2)` is `"84,079.69"` |
| `title(s)` | Capital first letters: `title("the open network")` is `"The Open Network"` |
| `date(x)` | ISO 8601 UTC time from ISO 8601 or RFC 2822 text, or a Unix time in seconds or milliseconds (`published_at=date(properties.time)`) |

`+` joins text and adds numbers: `"https://nvd.nist.gov/vuln/detail/" + cveID`.
`-`, `*` and `/` do arithmetic, with the usual precedence and parentheses:
`change=supply - supply_yesterday`, `"$" + short(shares * price)`. Put spaces around `-`,
because `a-b` is read as a field name. A calculation with a missing or non-numeric value, or a
division by zero, gives `null`.

## Without expression syntax

For the common case, `filter` accepts a field and a test:

```bash
unlimited filter --field country --eq Thailand
unlimited filter --field price --gt 10 --lt 100
unlimited filter --field title --contains launch
```

## Errors

Mistakes point at the problem:

```text
error: invalid expression: expected a value
  price >
         ^
hint: quote text values, e.g. availability == "InStock"
```
