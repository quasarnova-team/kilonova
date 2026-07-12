# Security policy

## Supported versions

The latest minor release receives security fixes. Older versions: please upgrade.

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's
[private vulnerability reporting](https://github.com/quasarnova-team/kilonova/security/advisories/new)
("Security" tab → "Report a vulnerability"). Do not open a public issue.

We aim to acknowledge reports within **72 hours** and to publish a fix or a mitigation
plan within 30 days of confirmation. Credit is given in the advisory unless you prefer
otherwise.

## Scope notes

kilonova is an OPC UA server framework: deployments should read the security section of
the documentation (endpoint policies, user/password logon, and the current limitations —
client-certificate trust lists are not yet enforced). Hardening guidance lives in the
docs and is being expanded.
