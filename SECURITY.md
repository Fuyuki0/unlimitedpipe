# Security

## Reporting a vulnerability

Please report security problems privately with GitHub's **Report a vulnerability** button on
the repository's Security tab, not in public issues. Include the version, the command or
pipeline, and what an attacker could do. You will get a reply within a few days.

Relevant areas include: pipeline files or event input that could execute code or write
outside expected paths, and anything that leaks secrets (tokens marked `secret` must never
appear in provenance or output).

## Abuse and takedown reports

If a published UnlimitedPipe feed or recipe contains personal data, infringes your rights, or
targets your site against its terms, use the same private channel or open an issue. Recipes and
connectors that break the [responsible-use rules](docs/responsible-use.md) are removed.

Site owners can opt out of default UnlimitedPipe traffic in robots.txt:

```text
User-agent: UnlimitedPipe
Disallow: /
```
