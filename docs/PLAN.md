# Vision: evidence-first onchain research

Research checked 18 November 2026. Engineering plan, not legal advice or authorization to process taxpayer data.

## Decision

Build a small, verifiable investigator workbench before attempting a government tax system. Version 1 joins a bounded public-chain reader, a searchable local index, sourced contract reference labels, and a separate synthetic FIFO reconciliation demonstration. It does **not** identify people or decide tax liability. No country pack is approved. The next investment should buy evidence quality, coverage and independent verification, not a more confident narrative.

The source concept's strongest insight is the separation of deterministic calculations from explanations. Its production ambition depends on legal access, reliable reporting feeds, complete basis records and country-specific rules. This repository is a foundation for testing those components, not delivery of the entire agency platform described in the concept.

## What the official sources support

1. **Public-chain extraction is technically available, but bounded.** Ethereum exposes JSON-RPC methods for blocks, receipts and logs, including a finalized-block selector. Vision uses those interfaces to retain explicit block/hash coverage and receipt outcomes rather than equating one address query with full financial history. This is an implementation choice based on the [Ethereum JSON-RPC documentation](https://ethereum.org/developers/docs/apis/json-rpc/).
2. **A token-shaped event is not a valuation.** ERC-20 specifies indexed sender/recipient fields and an integer value for Transfer. Name, symbol and decimals are optional. Vision therefore retains raw units and never assumes an unknown token has 18 decimals. A matching event shape alone does not establish legitimacy, market value or beneficial ownership. The latter cautions are engineering inferences, not additional guarantees of the [ERC-20 specification](https://eips.ethereum.org/EIPS/eip-20).
3. **Identity and jurisdiction are distinct data products.** CARF includes provider due diligence for identifying users and relevant tax jurisdictions, with reporting and exchange arrangements. It is not a public lookup API for identifying a wallet's owner. Vision's implication: do not infer a person, residency or a lawful right to inspect a return from an address or counterparty. See the [OECD CARF introduction](https://www.oecd.org/en/publications/international-standards-for-automatic-exchange-of-information-in-tax-matters_896d79d1-en/full-report/component-5.html).
4. **A schema is not access.** OECD's CARF XML format is primarily for exchange between tax administrations and may also be used for domestic reporting where allowed. Building an XML parser would not grant access to those records. A future adapter needs an authorized data controller, jurisdiction-specific implementation review and an approved destination. See the [OECD XML announcement](https://www.oecd.org/en/about/news/announcements/2024/10/crypto-asset-reporting-framework-and-amended-common-reporting-standard-oecd-releases-it-format-for-transmitting-information-and-issues-interpretative-guidance.html).
5. **One FIFO engine is not a global tax engine.** HMRC's individual cryptoassets guidance describes section 104 pooling, same-day matching and acquisition-within-30-days matching for relevant tokens. This is sufficient to reject substituting Vision's illustrative FIFO for UK tax calculations. It is not a complete statement of UK law or a production pack specification. See [HMRC CRYPTO22200](https://www.gov.uk/hmrc-internal-manuals/cryptoassets-manual/crypto22200).

No universal CARF commencement date or country rollout promise is assumed here. Counsel must verify operative local legislation, reporting periods, exchange partners and approved uses at onboarding.

## Scope map

| Capability | Version 1 boundary | What is required next |
|---|---|---|
| Chain crawling | Ethereum mainnet; bounded finalized block range, explicit resumable historical windows; top-level native transfers and ERC-20-shaped logs | Production scheduling, provider quotas, independent reconciliation, trace support and explicit per-chain adapters |
| Search | Records present in the local index; explicit dataset and coverage | Paginated historical ingestion, coverage ledger, indexed query plans and retention-aware search |
| Identifiers | Chain-qualified accounts and source transaction/log identities | Cross-chain asset mappings with versioned provenance, never symbol-only joins |
| Labels | Synthetic examples and sourced public contract reference labels; not owner attribution | Licensed label provenance, rights review, timestamps, confidence, disputes and expiry |
| Identity graph | No real-person resolution | Authorized provider attribution, evidence link types, human corroboration, case-level access and correction |
| PnL demonstration | Synthetic acquisition/disposal/income records; exact decimal FIFO; USD; explicit periods and source prices | Complete opening basis, fees, transfers, corporate actions, multiple wallets, FX and reviewed classification |
| Tax packs | Fictional VISION-DEMO-FIFO only, no tax due | Named country/counsel, versioned statutes and guidance, golden cases, effective dates and signed approval |
| Casework | Research workflow, evidence review and export; no assessment or notice | Identity-aware authorization, immutable external audit custody, authorized retention and independent security review |
| LLM | Not required for v1 calculations | Optional case-scoped cited explanations with evaluation gates and approved hosting, never runtime tax law |

A zero-result crawl means only that no supported match was returned for the selected range. It cannot establish an inactive wallet, absence of income, full asset history or compliance. Native internal transfers, fees, NFTs, DeFi semantics, off-chain exchanges and unlinked wallets remain outside the crawler's coverage. Live chain data and fictional financial examples must remain visibly separate; a crawl must never silently feed the synthetic FIFO as if transfers were purchases or disposals.

## Data and procurement architecture

Maintain separate evidence classes: raw observations, normalized events, sourced labels, asserted identity links, reviewed economic classifications, valuations, deterministic calculations and officer decisions. Every derived value should carry its source identifiers and transformation/pack version. Corrections must supersede records, not silently rewrite their history.

**Build:** the canonical schema, coverage ledger, deterministic transformation/reconciliation contracts, rule-pack interface, evidence export and operator workflow.

**Evaluate licensing rather than scraping:** historical indexers, internal-transfer traces, price feeds and commercial attribution. This is a proposed procurement strategy, not a claim about any vendor's accuracy or license. Assess each provider on export/retention rights, redistribution restrictions, regional hosting, pricing/quotas, historical backfills, token coverage, corrections, source transparency and cancellation costs. Run the same held-out corpus against at least two independent providers where possible. A vendor label is an attributed assertion, not proof of the actions of all its counterparties.

**Do not procure by demo alone:** contractually define measurable missing-record rates, provenance availability, outage behavior and correction turnaround. Chain RPC can supply observations; it cannot supply an investor's unknown exchange opening cost basis. Market price is not a substitute for documented acquisition cost. A transfer between two addresses is not automatically a sale, reward or common-ownership link.

## Proposed 30/60/90-day gates

These are project milestones after a staffed kickoff, not promises that a production government platform will be ready in 90 days. Each gate has a named owner and can stop the next phase.

### Days 1–30: establish the permitted problem

Product owner and tax counsel select one jurisdiction, one user group, one tax/event scope and one decision the product assists. Privacy/security owners document permitted source classes, purpose, retention, access, residency and breach handling. Engineers document API contracts, block/chain coverage and unsupported events. Procurement obtains permitted sample exports rather than real bulk taxpayer feeds.

**Gate A, signed by counsel, privacy lead and product owner:** approved scope; written data gateway for each proposed nonpublic feed; prohibited uses; licensed fixture rights; threat model; owner for each country rule. Without these, continue synthetic/public-contract testing only. Do not import real identities or returns.

### Days 31–60: make completeness measurable

Build resumable ingestion with a per-chain block-range ledger, rate limits, backoff, cancellation and reorg/finalization validation. Add source snapshots and correction versions. Build only the economic event types approved at Gate A; unknown classifications remain unresolved. Prepare a country-pack design separately from the fictional FIFO and require counsel-reviewed worked examples before implementation is treated as law.

**Gate B, signed by engineering and independent verification leads:** repeated ingestion is idempotent; no silent range gaps in the selected test corpus; two-source disagreements are visible; every displayed quantity has a resolvable source; all missing price/basis cases block conclusions; schemas and migrations reproduce from clean setup. Publish exact denominators and unresolved rates, not a headline “accuracy” alone.

### Days 61–90: blind validation and deployment decision

Freeze engine and pack candidate versions. Run an independently held blind corpus, compare to independently prepared ground truth, and let investigators review evidence usability without seeing model-generated conclusions first. Rehearse backup/restore, correction, access revocation, export verification and incident response in an isolated test tenancy. Investigate every discrepancy and rerun on a fresh held-out set after material tuning.

**Gate C, signed by counsel, independent verifier, security lead and accountable sponsor:** all safety invariants pass; an approved pack passes every mandatory counsel example; complete lineage for all exported calculations; no critical/high unresolved security defect; measured accuracy and coverage meet thresholds fixed before testing. A proposed reconstruction target is at least 95% exact matches on supported, fully evidenced cases, with the unsupported share separately published. This is a proposed target, not an achieved result. Passing permits a separately approved limited pilot, not automated notices, penalties, collection or criminal decisions.

## Golden-set protocol

- Start with at least 100–200 independently authored synthetic or lawfully anonymized cases. A production evaluation additionally needs representative authorized historical cases; the repository's unit fixtures are not evidence of field performance.
- Stratify by supported event type, time boundary, asset precision, source completeness, account/chain, price availability, fees and loss cases. Include intentionally unsupported events and corrupted records. Prevent duplicated wallets or case families leaking across development and blind splits.
- Two qualified reviewers prepare classifications and expected calculations independently. Adjudicate differences before freezing ground truth. Record exact sources, rule versions, expected cents/rounding method and rationale. Do not let the implementation generate its own answer key.
- Hold back a sealed 30% case-family split, controlled by a reviewer outside feature development. Define metrics and tolerances before the run. Separate ingestion recall, classification agreement, arithmetic exactness, unresolved coverage and human case-acceptance rates.
- Test invariants as well as totals: asset/unit conservation; order/tie handling; currency separation; duplicate-source rejection; missing-basis blocking; sign-preserving losses; replay-identical hashes; source correction changing hashes; superseded data never reported as current.
- Report confidence intervals and counts, all exclusions, the size of each subgroup and the failure inventory. Do not convert a small clean synthetic result into an enforcement precision claim. Reserve a random low-signal sample for later authorized selection evaluation.

## Safety and access boundary

V1 is a local research tool, not a government deployment. Keep it off the public Internet and never load real taxpayers, KYC files, financial account identifiers or personal ownership allegations into its demo workflow. Public contract references are descriptions of contracts, not accusations or person profiles. Use server-side provider configuration; do not accept arbitrary URLs from the browser. Limit request sizes, ranges, concurrency and retries; redact credentials in every failure path. Never request private wallet keys or send blockchain transactions.

Before nonpublic data: require single-country tenancy, authenticated individual users, least-privilege case-level roles, MFA/SSO, encryption and agency-approved key custody, network isolation, audit export to independent append-only custody, retention/deletion controls, authorized backup locations, penetration testing and access reviews. A local SHA-256 hash detects changed content when compared with a trusted prior value; it neither authenticates an upstream source nor makes a SQLite record immutable. The country owner must approve those controls and all source/recipient permissions.

No risk score may independently cause adverse treatment. No LLM may identify a person, reinterpret law, assess liability or send a notice. Decisions and corrections require authorized human review with provenance and a contestable record.

## Acceptance checks and release honesty

1. A clean checkout starts using documented commands and no hidden credentials; the synthetic workflow runs offline.
2. Crawling rejects unsupported chains, malformed addresses/ranges, unfinalized blocks, changed block hashes and mismatched receipts; ignores failed transfers; deduplicates self-transfers. Provider faults never become a successful empty dataset.
3. Token quantities remain raw when decimals are not verified. Contract labels have source/type and never propagate to users as identity claims.
4. Search, filters, navigation, repeated button clicks, clear/cancel and export are exercised against the backend; include empty/error states and narrow screens. Record what was actually tested.
5. Reconciliation verifies exact decimal FIFO, pre-period opening lots, income basis, signed losses/differences, duplicate identifiers/source references, missing prices/basis and snapshot boundaries. Blocked computations expose no partial totals.
6. Evidence export retains source records, hashes, coverage, mode, calculation version and unresolved limitations. Reimport/replay reproduces the same result; changing source/price provenance changes the content hash.
7. Run unit, integration, UI and live-provider smoke stages separately. A mocked adapter pass does not prove live connectivity; a one-range live pass does not prove historical coverage. Report passed, failed, skipped and blocked stages for the exact published commit.

See the release's test report/README for observed results. This roadmap defines acceptance targets; it does not claim they have all been met. Broader chains, public production hosting, licensed feeds, live identity matching and country tax computation each require an explicit follow-on scope and gate.
