# Carriers

Notes on each carrier: tracking-number formats (Session 2) and API details
(added as each carrier's client lands, Sessions 3-5).

## Tracking-number formats

Implemented in `custom_components/porchcast/tracking.py`. Written down
2026-11-20, from well-known format rules. The carrier APIs aren't reachable from
the cloud sessions, and the formats weren't checked against carrier docs. Check
them against real numbers with `live_check.py` once each carrier's API is in.

| Format | Carrier(s) to try, in order | Check digit |
| --- | --- | --- |
| `1Z` + 16 letters/digits | UPS | UPS mod 10: letters map to `(ord - ord('A') + 2) % 10`; odd positions ×1, even ×2 |
| 12 digits | FedEx | mod 11, weights 1, 3, 7 repeating from the right; result mod 10 |
| 15 digits | FedEx | not checked |
| 22 digits starting `96` | FedEx | not checked |
| 22 digits starting `91`-`95` (IMpb) | USPS, then FedEx | GS1 mod 10 (weights 3, 1 from the right) |
| `420` + 5 or 9-digit ZIP + IMpb (30 or 34 digits) | as IMpb; the prefix is dropped | GS1 on the IMpb part |
| 20 digits, GS1 valid | USPS, then FedEx | GS1 mod 10 |
| 20 digits, GS1 invalid | FedEx | none |
| `AA` + 9 digits + `AA` (UPU S10) | USPS | UPU mod 11, weights 8 6 4 2 3 5 9 7; 10 → 0, 11 → 5 |
| `ups:`, `fedex:` or `usps:` + 6-40 letters/digits with at least one digit | the named carrier only | none |

- **Unchecked FedEx formats** are accepted by length because I couldn't confirm
  their check-digit rules; rejecting a real number is worse than a failed
  lookup. Tighten this once real numbers have been seen.
- **Ambiguous numbers** (IMpb, 20-digit) list USPS first: most of them are
  USPS, and FedEx ground economy hands packages to USPS with IMpb numbers.
  Session 4's fallback tries them in order.
- **Spaces and hyphens**: a number may be split into groups of up to 6
  characters (up to 8 groups). A joined number must pass a check digit, so an
  unchecked format is matched only as a single token. Tokens containing `/`,
  `@` or `=`, or starting with `www.`, are skipped (URLs, emails).
- **Hyphens** count as group separators: a hyphenated token must pass a
  check digit too.
- **Prefixes** are read in text order with the other numbers (so the first
  number still wins). The number may follow the colon directly or after one
  space. A prefix inside a URL is ignored.
- **Where the number is found**: the summary first, then the notes. The first
  number wins.
