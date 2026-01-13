# Economics (token dynamics)

Each knowledge group maintains an internal credit ledger (balances).
Credits can be:
- minted by admins (`mint`)
- spent by buyers (`purchase`)

## Offers
An offer references an encrypted package. The seller defines:
- price
- splits (basis points) among recipients
- optional parent royalties (basis points to parent offer sellers)

On purchase:
- the buyer authorizes debiting their balance via a signature
- the chain applies distribution deterministically
- a sealed key is granted to the buyer (recorded on-chain)

## Production monetization
This repo provides the internal mechanics. Bridging to fiat is an integration:
- accept external payments
- mint credits to buyer pubkeys
- optionally redeem credits to off-chain payouts
