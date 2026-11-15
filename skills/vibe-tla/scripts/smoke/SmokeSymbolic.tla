------------------------- MODULE SmokeSymbolic -------------------------
EXTENDS Integers

VARIABLES
    \* @type: Int;
    x

Init ==
    /\ x \in Int
    /\ x >= 0

Next ==
    /\ x' = x + 1

Inv == x >= 0

IndInv ==
    /\ x \in Int
    /\ x >= 0
========================================================================
