# Maconomy to CaseWare Cloud integration

This folder records the four current sync paths and the work needed to make
Maconomy the primary owner of CaseWare mapping IDs and sync checkpoints.

- [Current data flow](current-data-flow.md) describes the behavior implemented
  in the repository today, including create and update processing.
- [Maconomy-first checkpoint requirements](maconomy-first-checkpoints.md)
  identifies the current database dependencies, required Maconomy contract,
  and acceptance scenarios for the change.

The functional document for the **completed** Maconomy-first integration should
be written after that contract is confirmed and the code has been changed and
verified. The existing documents in `backend/documentation` describe older
behavior and should not be used as the specification for the new checkpoint.
