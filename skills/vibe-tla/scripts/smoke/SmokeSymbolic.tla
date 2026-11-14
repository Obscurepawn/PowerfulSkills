------------------------- MODULE SmokeSymbolic -------------------------
EXTENDS Integers

\* @type: Int;
VARIABLE x

Init ==
    /\ x \in Int
    /\ x >= 0

Next ==
    /\ x' = x + 1

Inv == x >= 0
========================================================================
