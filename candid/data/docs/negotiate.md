# Negotiate: playbook, scripts, counters

The offer is the starting point, not the answer. candid gives you a
negotiation playbook, word-for-word scripts for the hard moments, and
counter-offer email drafts.

## The commands

```bash
python -m candid negotiate playbook
python -m candid negotiate script --which lowball_anchor
python -m candid negotiate script --which competing_offer --set company=Acme --set number=190000
python -m candid negotiate counter --person Jane --role "Data Scientist" --company Acme --base-ask "190k base"
```

## Subcommands

- `playbook` — the full negotiation playbook: principles, sequencing,
  what to ask for first, and common traps.
- `script` — a script for one scenario. `--which` is required, one of:
  `lowball_anchor`, `competing_offer`, `exploding_deadline`,
  `level_pushback`, `leveling_up_push`, `remote_flexibility`.
  `--set key=value` (repeatable) fills template fields, e.g.
  `--set company=Acme --set number=190000`.
- `counter` — draft a counter-offer email. `--person`, `--role`,
  `--company`, and `--base-ask` are required; optional: `--location`,
  `--second-item` (default `"Sign-on bonus"`), `--second-ask`, `--target`,
  `--call-time` (default `"tomorrow"`).

## The core principles (from the playbook)

1. **Never accept on the call.** Thank them, express enthusiasm, ask for
   the details in writing and a few days to decide.
2. **Negotiate the whole package.** Base, sign-on, equity, level, start
   date, remote flexibility — trade across them, not just base salary.
3. **Anchor with data.** Your `salary lookup` ranges and LCA imports are
   your evidence; "the market data I have says..." beats "I was hoping
   for...".
4. **Competing offers are leverage; bluffs are not.** Only reference offers
   you actually have. `offer compare` keeps your real numbers straight.
5. **Get the final number in writing** before you withdraw from other
   processes.

## Sequencing

`offer add` every offer -> `offer compare` to rank them -> `negotiate
playbook` to plan -> `negotiate script` for the specific conversation ->
`negotiate counter` to put it in writing -> `track update <id> --status
accepted` when you sign.
