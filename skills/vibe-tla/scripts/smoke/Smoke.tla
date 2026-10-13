---------------------------- MODULE Smoke ----------------------------
\* Trivial spec used by install_tlc.sh to confirm TLC actually executes.
EXTENDS Naturals
VARIABLE x
Init == x = 0
Next == x' = (x + 1) % 3
Spec == Init /\ [][Next]_x
Inv  == x \in 0..2
======================================================================
