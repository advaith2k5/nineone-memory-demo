# AGENTS.md — what we know about this network (RCA agent, RAN_A8)

This file changes only when a person releases a new version. It holds nothing about today's cell.

## Versions in force

| Item | Version |
|---|---|
| Root-cause category list | `demo-0.1` (placeholder. The real list must be agreed with the customer.) |
| Track-record format | v3 section 6.3 |

## Names and conventions

- A cell id is the letters `RNA`, then 10 digits, then `_` and the cell number. A site id is `TOK-` and a number.
- All feeds give times in UTC.
- Accessibility is a percentage. The target for a cell comes with the case facts. It is never in this file.

## Rulings already settled by the experts

- A MINOR alarm that is not service-affecting does not give a fault category on its own.
- A parameter change that was **not authorised** and happened **before** the problem started counts as
  evidence for the config category.
- Two findings count as two separate opinions only if they read from different sources. Coverage and
  performance both reading the same measurement reports count as one.

## How track records are used

- A track record is about a kind of finding on a kind of cell. It is never about one cell.
- Below 30 cases it is shown as "neutral". A record built on a handful of cases is not a record.
- Always say the period the record covers.

## Known gaps

- There is no digital twin in this setup. You cannot say what is "normal" for a cell, only compare with
  its target.
- There is no knowledge graph. You cannot look up cause-and-effect paths.
- There is no topology feed. If a case depends on neighbouring cells or shared transport, say so and stop.
- There is no subscriber data, by design.
