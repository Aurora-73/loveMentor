"""Run a zero-dependency, fully synthetic LoveMentor preview.

This module intentionally does not read a local database, chat archive, or
network service.  It gives contributors a safe first-run experience.
"""
from __future__ import annotations


REPORT = """\
LoveMentor — synthetic demo (no personal data used)
===================================================

Profile: Demo contact
Period: last 30 days (illustrative)

Observable signals
------------------
- Message activity: stable, with a recent uptick
- Reply rhythm: generally balanced
- Topic continuity: 3 conversations continued naturally
- Event: interaction frequency increased

Interpretation
--------------
The data suggests a change worth observing, not a conclusion about intent.
Use real-world context and respect a clear no before making any invitation.

Next low-pressure action
------------------------
If appropriate, make one specific, easy-to-decline invitation.  Treat both
acceptance and refusal as useful feedback; do not infer certainty from metrics.

To analyse real data, configure an optional WCD or WeFlow provider locally.
"""


def main() -> int:
    print(REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
