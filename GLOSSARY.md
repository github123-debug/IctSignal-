# ICT Signal Commercial Context

This context covers the commercial delivery of ordered ICT market signals to paying customers.

## Language

**Customer Account**:
The paying commercial relationship that owns a signal service subscription. In V1, each Customer Account has exactly one User.
_Avoid_: Customer, client, account

**User**:
The person who signs in and manages a Customer Account. A User is an operator of the product, not the billing relationship itself.
_Avoid_: Customer, member

**Managed Instance**:
An isolated signal service assigned to one Customer Account, with its own configuration, runtime state, signal history, and notification credentials.
_Avoid_: Tenant, scanner process

**Signal Service**:
The product that scans market data and delivers informational signal notifications without placing or managing trades.
_Avoid_: Trading bot, auto-trader

**Signal**:
A notification emitted only after the configured liquidity touch, BOS confirmation, and FVG retracement sequence completes in order.
_Avoid_: Trade, order, recommendation

**Signal Profile**:
The customer-owned selection of scan universe and notification preferences used by a Managed Instance. Commercial V1 permits one active Signal Profile per Customer Account.
_Avoid_: Environment, settings file, strategy

**Customer Portal**:
The authenticated product interface where a User manages the Customer Account, Signal Profile, subscription status, and Signal history.
_Avoid_: Dashboard, scanner UI

**Platform Bot**:
The Telegram bot operated by the product and shared as the delivery identity for all Customer Accounts, while each account has a separately bound destination.
_Avoid_: User bot, customer bot

**Subscription**:
The time-bounded commercial entitlement that permits a Customer Account to operate its Managed Instance.
_Avoid_: License, membership

**Telegram Destination**:
The single private Telegram chat bound to a Customer Account for delivery by the Platform Bot. Rebinding replaces the previous destination.
_Avoid_: Chat ID, recipient list

**Signal Profile Version**:
An immutable snapshot of a Signal Profile that is either a draft or the active published configuration. A Managed Instance always runs one complete published version.
_Avoid_: Settings update, environment version

**Live Baseline**:
The current closed-market state from which a newly started or restored scan begins observing future sequences without emitting earlier historical patterns.
_Avoid_: Backfill, replay point
